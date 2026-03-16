"""LangChain LCEL agent for Customer Segmentation.

Combines segment identification and table content generation into a single
coordinated pass:

  Step 1 – classify_maturity: determine whether uploaded files are
             totally_raw, semi_raw, or mature.
  Step 2 – extract_segments (mature) or synthesize_segments (raw/semi_raw):
             produce 2–n_segments mutually exclusive HCP segment names.
  Step 3 – generate_table: populate slide 1 table cells using the same
             row-level extraction rules as modules/customer_segmentation/slides/slide1.py.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from shared.logging_config import setup_logging
from generation.stage_metrics import record_llm_usage, stage_scope

logger = setup_logging("cs_agent_generation")

MIN_SEGMENTS = 2
MISSING_PROPOSED_SEGMENT_HEADER = "proposed segment can not be found in given files"
NOT_FOUND_CELL_TEXT = "Not found in provided materials."
_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# Prompt-size guard for segment naming steps.
# If estimated prompt tokens exceed this budget, we switch from full-document
# context to retrieval snippets to avoid context-window errors.
_SEGMENT_PROMPT_TOKEN_BUDGET_OPENAI = int(
    os.getenv("CS_SEGMENT_PROMPT_TOKEN_BUDGET_OPENAI", "50000")
)
_SEGMENT_PROMPT_TOKEN_BUDGET_QWEN = int(
    os.getenv("CS_SEGMENT_PROMPT_TOKEN_BUDGET_QWEN", "18000")
)

_CS_AGENT_TRACE_DIR = (
    Path(__file__).resolve().parents[2] / "logs" / "cs_agent_llm"
)

# ---------------------------------------------------------------------------
# Token accounting helper for LangChain responses
# ---------------------------------------------------------------------------

def _record_langchain_usage(msg: Any, elapsed_ms: int) -> None:
    """Extract token counts from a LangChain AIMessage and forward to stage metrics."""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model = (
        os.getenv("QWEN_MODEL", "qwen-max")
        if provider == "qwen"
        else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )
    prompt_tokens = completion_tokens = total_tokens = None

    usage_meta = getattr(msg, "usage_metadata", None)
    if isinstance(usage_meta, dict):
        prompt_tokens = usage_meta.get("input_tokens")
        completion_tokens = usage_meta.get("output_tokens")
        total_tokens = usage_meta.get("total_tokens")

    if prompt_tokens is None:
        token_usage = (getattr(msg, "response_metadata", {}) or {}).get("token_usage") or {}
        prompt_tokens = token_usage.get("prompt_tokens")
        completion_tokens = token_usage.get("completion_tokens")
        total_tokens = token_usage.get("total_tokens")

    record_llm_usage(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        elapsed_ms=elapsed_ms,
    )


def _estimate_tokens_for_prompt(text: str) -> int:
    """
    Conservative prompt token estimate that handles mixed EN/CN text.

    - CJK characters are treated roughly as 1 token each.
    - Remaining characters are treated as ~1 token per 3.5 chars.
    """
    cleaned = text or ""
    if not cleaned:
        return 0
    cjk_chars = len(_CJK_CHAR_RE.findall(cleaned))
    non_cjk_chars = max(0, len(cleaned) - cjk_chars)
    return int(cjk_chars + (non_cjk_chars / 3.5))


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def _build_langchain_llm(
    max_tokens: int | None = None,
    temperature: float = 0.0,
) -> ChatOpenAI:
    """Build a LangChain ChatOpenAI client from env, reusing SSL config."""
    verify_env = os.getenv("LLM_SSL_VERIFY", "true").strip().lower()
    ca_bundle = (
        os.getenv("LLM_CA_BUNDLE")
        or os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
    )
    timeout = float(os.getenv("LLM_HTTP_TIMEOUT", "180"))

    verify: bool | str = True
    if verify_env in {"0", "false", "no", "off"}:
        verify = False
    elif ca_bundle:
        verify = ca_bundle

    http_client = httpx.Client(timeout=timeout, verify=verify)

    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "qwen":
        kwargs: dict[str, Any] = dict(
            api_key=os.getenv("QWEN_API_KEY", ""),
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            model=os.getenv("QWEN_MODEL", "qwen-max"),
            temperature=temperature,
            http_client=http_client,
        )
    else:
        kwargs = dict(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=temperature,
            http_client=http_client,
        )

    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    return ChatOpenAI(**kwargs)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM = """\
You are a document analyst for pharmaceutical commercial strategy.

Classify the uploaded materials into EXACTLY one of three categories:

- "totally_raw": contains only raw research data — e.g. interview transcripts,
  observational notes, survey verbatims — with no prior human analysis.
- "semi_raw": contains some human analysis or summary commentary but does NOT
  clearly identify named HCP customer segments.
- "mature": contains completed human analysis that explicitly names and describes
  distinct HCP customer segments.

Return ONLY valid JSON with no markdown fences:
{{"maturity": "totally_raw"|"semi_raw"|"mature", "reasoning": "<one sentence>"}}"""

_CLASSIFY_USER = """\
Uploaded material:
{content}

Classify the maturity now:"""


_EXTRACT_SYSTEM = """\
You are a pharmaceutical commercial strategy analyst.

The uploaded materials already contain completed HCP customer segment analysis.
Your task is to extract the segment names EXACTLY as they appear — do not rename,
merge, or invent new ones.

Rules:
- Return between {min_segments} and {n_segments} HCP segment names.
- HCPs only: physicians, specialists, prescribers, clinical decision makers.
- No payers, regulators, procurement bodies, government stakeholders, or patients.
- Names must be concise (< 5 words), neutral, and easy to remember.
Good Examples of Segment Names:
- Pioneer
- Considerate Performer
- Safe Player
- Traditionalist

Return ONLY a valid JSON flat array of segment name strings. Only return the segment in English
No markdown, no explanation, no extra keys."""

_EXTRACT_USER = """\
Number of segments to return: between {min_segments} and {n_segments}

Uploaded material:
{content}

Extract the segment names now:"""


_SYNTHESIZE_SYSTEM = """\
You are a pharmaceutical commercial strategy analyst.

Analyze the uploaded material and identify HCP customer segments relevant for
promoting the product discussed.

Customers refer only to HCPs (e.g., physicians, specialists, prescribers,
clinical decision makers). Do NOT create segments for payers, regulators,
procurement bodies, government stakeholders, or patients.

SEGMENTATION GUIDELINES

Customer segmentation groups stakeholders with similar behaviors, attitudes,
motivations, and barriers to understand how to influence behavior and drive
adoption.

Segments should explain:
- what HCPs currently do
- why they behave this way
- how their behavior could potentially change

Segments must primarily differ by key_distinguishing_traits, such as:

Attitudes / beliefs
  Mindset toward disease management, treatment innovation, evidence expectations,
  or clinical philosophy.

Behaviors
  Observable treatment decisions such as therapy choice, sequencing, switching
  patterns, or adoption timing.

Drivers and barriers
  Factors influencing treatment decisions (e.g., efficacy expectations, safety
  concerns, operational constraints, access barriers).

Supporting context (secondary only): demographics, practice environment, or
hospital characteristics. These may describe segments but must NOT be the
primary basis of segmentation.

TRAITS SOURCING RULES (CRITICAL)

1. SOURCE VERIFICATION: Before adding any trait, ask:
   "Does the source material explicitly state that HCPs following [this specific
   treatment algorithm / behavior pattern] exhibit this trait?"
   If the answer is NO, exclude the trait.

2. NO INFERENCE: Do not deduce traits logically. Only include traits explicitly stated.

3. NO GENERALIZATION: Do not take attributes from general summary tables unless
   the material explicitly links them to this segment archetype.

4. PAGE-ANCHORED: Each trait should correspond to a specific reference in the
   material where this segment's characteristics are described.

NAMING RULES
- Concise and descriptive (< 5 words each)
- Mutually exclusive and collectively exhaustive across identified HCPs
- Respectful and neutral

Your goal is to identify between {min_segments} and {n_segments} distinct,
mutually exclusive HCP segments.

Return ONLY a valid JSON flat array of segment name strings.
No markdown, no explanation, no extra keys."""

_SYNTHESIZE_USER = """\
Number of segments to return: between {min_segments} and {n_segments}

Uploaded material:
{content}

Identify the HCP segments now:"""


_SYNTHESIZE_WITH_METHODOLOGY_SYSTEM = """\
You are a pharmaceutical commercial strategy analyst.

Analyze the uploaded research material and identify HCP customer segments, \
guided by a segmentation methodology agreed with the business team.

SEGMENTATION METHODOLOGY GUIDE (APPLY THIS APPROACH)
{methodology}

GENERAL SEGMENTATION GUIDELINES

Customers refer only to HCPs (physicians, specialists, prescribers, clinical decision makers). \
Do NOT create segments for payers, regulators, procurement bodies, government stakeholders, or patients.

SOURCING RULES (CRITICAL)
1. Only include segment distinctions explicitly supported by the source material.
2. Do not logically deduce traits not stated in the documents.
3. The methodology guide is a search lens — it tells you what to look for; \
evidence must come from the uploaded materials.

NAMING RULES
- Concise and descriptive (< 5 words each)
- Mutually exclusive and collectively exhaustive across the identified HCPs
- Respectful and neutral
- Names should reflect the segmentation lens described in the methodology guide; \
candidate directions mentioned there are examples to inspire naming, not fixed labels

Your goal is to identify between {min_segments} and {n_segments} distinct, \
mutually exclusive HCP segments that best match the methodology guide and the evidence.

Return ONLY a valid JSON flat array of segment name strings.
No markdown, no explanation, no extra keys."""

_SYNTHESIZE_WITH_METHODOLOGY_USER = """\
Number of segments to return: between {min_segments} and {n_segments}

Uploaded material:
{content}

Following the methodology guide above, identify the HCP segments now:"""


# The table generation prompt is delegated to slide1.build_prompts() to keep
# a single source of truth for extraction rules used in both initial generation
# and the feedback path.

# ---------------------------------------------------------------------------
# Table repair helper
# ---------------------------------------------------------------------------

def _repair_table(data: list, segments: list[str]) -> list[list[str]]:
    """Repair LLM output where segment values were merged into fewer cells.

    The LLM sometimes outputs rows like:
      ["Pioneer: x. Considerate Performer: y. Safe Player: z. Traditionalist: w.", ...]
    instead of the correct:
      ["x", "y", "z", "w"]

    Two failure modes are handled:
    1. Wrong column count  — len(row) != len(segments)
    2. Multi-segment cells — a single cell contains content for more than one segment
       (detected by finding >1 known segment-name prefix inside one cell)

    Repair strategy: flatten all cells in the row into one text blob, split on
    "<SegmentName>:" boundaries, and redistribute one chunk per segment column.
    """
    import re

    n = len(segments)
    split_pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(s) for s in segments) + r")\s*:\s*"
    )

    def _needs_repair(row: list) -> bool:
        if len(row) != n:
            return True
        for cell in row:
            found = split_pattern.findall(str(cell))
            if len(found) > 1:
                return True
        return False

    def _split_row(row: list) -> list[str]:
        blob = " ".join(str(c) for c in row)
        parts = split_pattern.split(blob)
        # parts = [pre_text, seg_name, seg_content, seg_name, seg_content, ...]
        seg_map: dict[str, str] = {}
        i = 1
        while i < len(parts) - 1:
            name = parts[i].strip()
            content = parts[i + 1].strip().strip(".")
            if name in set(segments):
                seg_map[name] = content
            i += 2
        return [seg_map.get(seg, NOT_FOUND_CELL_TEXT) for seg in segments]

    repaired: list[list[str]] = []
    for row in data:
        if not isinstance(row, list):
            repaired.append([NOT_FOUND_CELL_TEXT] * n)
            continue
        if _needs_repair(row):
            repaired.append(_split_row(row))
        else:
            repaired.append([str(c) for c in row])
    return repaired


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _ensure_unique_headers(headers: list[str]) -> list[str]:
    """Keep table headers unique to avoid downstream column ambiguity."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for header in headers:
        key = _normalize_text(header)
        count = seen.get(key, 0) + 1
        seen[key] = count
        if count == 1:
            out.append(header)
        else:
            out.append(f"{header} ({count})")
    return out


def _mark_segments_missing_in_uploaded_files(
    segments: list[str],
    content: str,
) -> list[str]:
    """Replace segment headers when names are not evidenced in uploaded files."""
    normalized_content = _normalize_text(content)
    resolved: list[str] = []
    for seg in segments:
        normalized_seg = _normalize_text(seg)
        if normalized_seg and normalized_seg in normalized_content:
            resolved.append(seg)
        else:
            resolved.append(MISSING_PROPOSED_SEGMENT_HEADER)
    return _ensure_unique_headers(resolved)


# ---------------------------------------------------------------------------
# Trace writer
# ---------------------------------------------------------------------------

def _write_agent_trace(
    *,
    step: str,
    module: str,
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        _CS_AGENT_TRACE_DIR.mkdir(parents=True, exist_ok=True)
        module_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (module or "").strip().lower()).strip("_") or "module"
        file_name = (
            f"{time.strftime('%Y%m%d_%H%M%S')}_{module_slug}_{step}_{uuid.uuid4().hex[:8]}.txt"
        )
        file_path = _CS_AGENT_TRACE_DIR / file_name
        extra_block = ""
        if extra:
            extra_block = "\n=== EXTRA ===\n" + json.dumps(extra, ensure_ascii=False, indent=2)
        text = (
            f"step: {step}\n"
            f"module: {module}\n"
            f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{extra_block}"
            "\n=== SYSTEM PROMPT ===\n"
            + (system_prompt or "")
            + "\n\n=== USER PROMPT ===\n"
            + (user_prompt or "")
            + "\n\n=== LLM RAW RESPONSE ===\n"
            + (llm_raw_response or "")
            + "\n"
        )
        file_path.write_text(text, encoding="utf-8")
        logger.info("CS agent trace written step=%s module=%s path=%s", step, module, file_path)
    except Exception as e:
        logger.warning("CS agent trace write failed step=%s module=%s err=%s", step, module, e)


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class CustomerSegmentationAgent:
    """
    LangChain LCEL-based agent that combines segment identification and
    table content generation for the Customer Segmentation module.

    Step 1: classify file maturity (totally_raw | semi_raw | mature)
    Step 2: extract existing segments (mature) OR synthesize segments (raw/semi_raw)
    Step 3: generate slide 1 table content using the identified segments
    """

    def __init__(self) -> None:
        self._classify_llm = _build_langchain_llm(max_tokens=200)
        self._segment_llm = _build_langchain_llm(max_tokens=300)
        self._table_llm = _build_langchain_llm(max_tokens=4000)

        self._classify_prompt = ChatPromptTemplate.from_messages([
            ("system", _CLASSIFY_SYSTEM),
            ("human", _CLASSIFY_USER),
        ])
        self._extract_prompt = ChatPromptTemplate.from_messages([
            ("system", _EXTRACT_SYSTEM),
            ("human", _EXTRACT_USER),
        ])
        self._synthesize_prompt = ChatPromptTemplate.from_messages([
            ("system", _SYNTHESIZE_SYSTEM),
            ("human", _SYNTHESIZE_USER),
        ])
        self._synthesize_with_methodology_prompt = ChatPromptTemplate.from_messages([
            ("system", _SYNTHESIZE_WITH_METHODOLOGY_SYSTEM),
            ("human", _SYNTHESIZE_WITH_METHODOLOGY_USER),
        ])

    def _segment_prompt_budget(self) -> int:
        provider = os.getenv("LLM_PROVIDER", "openai").lower()
        if provider == "qwen":
            return _SEGMENT_PROMPT_TOKEN_BUDGET_QWEN
        return _SEGMENT_PROMPT_TOKEN_BUDGET_OPENAI

    def _would_exceed_segment_prompt_budget(self, system_prompt: str, user_prompt: str) -> bool:
        estimated = _estimate_tokens_for_prompt(system_prompt) + _estimate_tokens_for_prompt(user_prompt)
        budget = self._segment_prompt_budget()
        exceeds = estimated > budget
        logger.info(
            "CS agent prompt budget check estimated_tokens=%d budget=%d exceeds=%s",
            estimated,
            budget,
            exceeds,
        )
        return exceeds

    def _truncate_content_for_budget(
        self,
        *,
        content: str,
        system_prompt: str,
        user_template: str,
        user_template_args: dict[str, Any],
    ) -> str:
        """
        Last-resort truncation to prevent context-window overflow.

        Keeps prompt shell intact and clips only the document content.
        """
        budget = self._segment_prompt_budget()
        fixed_user = user_template.format(content="", **user_template_args)
        overhead = _estimate_tokens_for_prompt(system_prompt) + _estimate_tokens_for_prompt(fixed_user)
        available_for_content = max(1000, budget - overhead)
        estimated_content_tokens = _estimate_tokens_for_prompt(content)
        if estimated_content_tokens <= available_for_content:
            return content

        keep_ratio = available_for_content / max(1, estimated_content_tokens)
        keep_chars = max(1200, int(len(content) * keep_ratio))
        clipped = content[:keep_chars].rstrip()
        logger.warning(
            "CS agent: truncating content for prompt budget estimated_content_tokens=%d allowed_content_tokens=%d original_chars=%d kept_chars=%d",
            estimated_content_tokens,
            available_for_content,
            len(content),
            len(clipped),
        )
        return clipped + "\n\n[Content truncated to fit context window.]"

    # ------------------------------------------------------------------
    # Retrieval helper
    # ------------------------------------------------------------------

    def _retrieve_context(
        self,
        file_ids: list[str],
        query: str,
        table_structure: dict[str, Any] | None = None,
        module: str = "customer segmentation",
    ) -> str:
        """Return relevant context for the given query using the evidence pipeline."""
        from retriever.evidence_pipeline import run_evidence_pipeline
        from retriever.pipeline_config import load_pipeline_config

        config = load_pipeline_config()
        result = run_evidence_pipeline(
            file_ids=file_ids,
            module=module,
            table_structure=table_structure or {},
            seed_query=query,
            config=config,
        )
        logger.info(
            "CS agent: retrieved context file_ids=%d query_len=%d content_len=%d degraded=%s",
            len(file_ids),
            len(query),
            len(result.context_text),
            result.degraded,
        )
        return result.context_text


    # ------------------------------------------------------------------
    # Step helpers
    # ------------------------------------------------------------------

    def _classify(self, content: str, module: str) -> str:
        """Classify file maturity. Returns 'totally_raw', 'semi_raw', or 'mature'."""
        with stage_scope("cs_agent_classify_maturity"):
            raw = ""
            try:
                start = time.perf_counter()
                _msg = (self._classify_prompt | self._classify_llm).invoke({"content": content})
                _record_langchain_usage(_msg, elapsed_ms=int((time.perf_counter() - start) * 1000))
                raw = _msg.content if hasattr(_msg, "content") else str(_msg)
                _write_agent_trace(
                    step="classify_maturity",
                    module=module,
                    system_prompt=_CLASSIFY_SYSTEM,
                    user_prompt=_CLASSIFY_USER.format(content=content[:200] + "..."),
                    llm_raw_response=raw,
                )
                cleaned = raw.strip()
                if "```" in cleaned:
                    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
                    if m:
                        cleaned = m.group(1)
                parsed = json.loads(cleaned)
                maturity = str(parsed.get("maturity", "")).strip().lower()
                if maturity not in {"totally_raw", "semi_raw", "mature"}:
                    logger.warning(
                        "CS agent: unexpected maturity value '%s', defaulting to semi_raw", maturity
                    )
                    maturity = "semi_raw"
                logger.info(
                    "CS agent classify done module=%s maturity=%s reasoning=%s elapsed_ms=%d",
                    module,
                    maturity,
                    str(parsed.get("reasoning", ""))[:200],
                    int((time.perf_counter() - start) * 1000),
                )
                return maturity
            except Exception as exc:
                logger.warning(
                    "CS agent classify failed, defaulting to semi_raw module=%s err=%s raw=%s",
                    module,
                    exc,
                    raw[:400],
                )
                return "semi_raw"

    def _parse_segment_list(self, raw: str, n_segments: int, module: str) -> list[str]:
        """Parse a JSON segment name list from raw LLM output."""
        cleaned = raw.strip()
        if "```" in cleaned:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
            if m:
                cleaned = m.group(1)
        names = json.loads(cleaned)
        if not isinstance(names, list):
            raise ValueError("Expected a JSON list")
        names = [str(n).strip() for n in names if str(n).strip()]
        return names[:n_segments]

    def _extract_segments(
        self, content: str, n_segments: int, module: str
    ) -> list[str]:
        """Step 2a: extract segment names from mature files."""
        with stage_scope("cs_agent_extract_segments"):
            raw = ""
            try:
                start = time.perf_counter()
                _msg = (self._extract_prompt | self._segment_llm).invoke({
                    "content": content,
                    "n_segments": n_segments,
                    "min_segments": MIN_SEGMENTS,
                })
                _record_langchain_usage(_msg, elapsed_ms=int((time.perf_counter() - start) * 1000))
                raw = _msg.content if hasattr(_msg, "content") else str(_msg)
                _write_agent_trace(
                    step="extract_segments",
                    module=module,
                    system_prompt=_EXTRACT_SYSTEM.format(n_segments=n_segments, min_segments=MIN_SEGMENTS),
                    user_prompt=_EXTRACT_USER.format(
                        content=content,
                        n_segments=n_segments,
                        min_segments=MIN_SEGMENTS,
                    ),
                    llm_raw_response=raw,
                    extra={"n_segments": n_segments},
                )
                names = self._parse_segment_list(raw, n_segments, module)
                logger.info(
                    "CS agent extract done module=%s names=%s elapsed_ms=%d",
                    module,
                    names,
                    int((time.perf_counter() - start) * 1000),
                )
                return names
            except Exception as exc:
                logger.warning(
                    "CS agent extract failed module=%s err=%s raw=%s",
                    module,
                    exc,
                    raw[:400],
                )
                return []

    def _synthesize_segments(
        self, content: str, n_segments: int, module: str
    ) -> list[str]:
        """Step 2b: synthesize segment names for raw/semi_raw files."""
        with stage_scope("cs_agent_synthesize_segments"):
            raw = ""
            try:
                start = time.perf_counter()
                _msg = (self._synthesize_prompt | self._segment_llm).invoke({
                    "content": content,
                    "n_segments": n_segments,
                    "min_segments": MIN_SEGMENTS,
                })
                _record_langchain_usage(_msg, elapsed_ms=int((time.perf_counter() - start) * 1000))
                raw = _msg.content if hasattr(_msg, "content") else str(_msg)
                _write_agent_trace(
                    step="synthesize_segments",
                    module=module,
                    system_prompt=_SYNTHESIZE_SYSTEM.format(n_segments=n_segments, min_segments=MIN_SEGMENTS),
                    user_prompt=_SYNTHESIZE_USER.format(
                        content=content,
                        n_segments=n_segments,
                        min_segments=MIN_SEGMENTS,
                    ),
                    llm_raw_response=raw,
                    extra={"n_segments": n_segments},
                )
                names = self._parse_segment_list(raw, n_segments, module)
                logger.info(
                    "CS agent synthesize done module=%s names=%s elapsed_ms=%d",
                    module,
                    names,
                    int((time.perf_counter() - start) * 1000),
                )
                return names
            except Exception as exc:
                logger.warning(
                    "CS agent synthesize failed module=%s err=%s raw=%s",
                    module,
                    exc,
                    raw[:400],
                )
                return []

    def _synthesize_with_methodology(
        self, content: str, n_segments: int, module: str, methodology: str
    ) -> list[str]:
        """Step 2 (methodology-guided): identify segment names from data guided by cowork methodology."""
        with stage_scope("cs_agent_synthesize_with_methodology"):
            raw = ""
            try:
                start = time.perf_counter()
                rendered_system = _SYNTHESIZE_WITH_METHODOLOGY_SYSTEM.format(
                    methodology=methodology.strip(),
                    min_segments=MIN_SEGMENTS,
                    n_segments=n_segments,
                )
                _msg = (self._synthesize_with_methodology_prompt | self._segment_llm).invoke({
                    "methodology": methodology.strip(),
                    "content": content,
                    "n_segments": n_segments,
                    "min_segments": MIN_SEGMENTS,
                })
                _record_langchain_usage(_msg, elapsed_ms=int((time.perf_counter() - start) * 1000))
                raw = _msg.content if hasattr(_msg, "content") else str(_msg)
                _write_agent_trace(
                    step="synthesize_with_methodology",
                    module=module,
                    system_prompt=rendered_system,
                    user_prompt=_SYNTHESIZE_WITH_METHODOLOGY_USER.format(
                        content=content,
                        n_segments=n_segments,
                        min_segments=MIN_SEGMENTS,
                    ),
                    llm_raw_response=raw,
                    extra={
                        "n_segments": n_segments,
                        "methodology_len": len(methodology),
                        "content_len": len(content),  # actual chars passed to LLM (trace shows truncated)
                    },
                )
                names = self._parse_segment_list(raw, n_segments, module)
                logger.info(
                    "CS agent methodology-guided synthesize done module=%s names=%s elapsed_ms=%d",
                    module,
                    names,
                    int((time.perf_counter() - start) * 1000),
                )
                return names
            except Exception as exc:
                logger.warning(
                    "CS agent methodology-guided synthesize failed module=%s err=%s raw=%s; "
                    "falling back to standard synthesize",
                    module,
                    exc,
                    raw[:400],
                )
                return []

    def _generate_table(
        self,
        file_ids: list[str],
        segments: list[str],
        indexes: list[str],
        module: str,
        trace_capture: dict[str, Any] | None = None,
        cowork_summary: str | None = None,
    ) -> list[list[str]]:
        """Step 3: generate slide table content using slide1 prompt rules.

        Retrieves relevant context via the evidence pipeline (facet-gated
        hybrid retrieval) rather than dumping all file content, keeping the
        prompt within the model's token limit regardless of how many files
        are uploaded.
        """
        from modules.customer_segmentation.slides.slide1 import build_prompts

        with stage_scope("cs_agent_generate_table"):
            # Build a targeted retrieval query from the known segments and row labels.
            query = (
                f"HCP customer segment {' '.join(segments[:4])} "
                f"{' '.join(indexes[:6])}"
            )
            table_structure: dict[str, Any] = {
                "columns": [""] + segments,
                "indexes": indexes,
            }
            content = self._retrieve_context(
                file_ids, query, table_structure=table_structure, module=module
            )

            if not content.strip():
                logger.warning(
                    "CS agent: empty context for table generation module=%s rows=%d cols=%d",
                    module,
                    len(indexes),
                    len(segments),
                )
                return [
                    [NOT_FOUND_CELL_TEXT for _ in segments]
                    for _ in indexes
                ]

            system_prompt, user_prompt = build_prompts(
                content, indexes, segments, cowork_summary=cowork_summary
            )

            if trace_capture is not None:
                trace_capture["system_prompt"] = system_prompt
                trace_capture["user_prompt"] = user_prompt

            _max_tokens = min(4000, max(1500, len(indexes) * len(segments) * 80))
            table_prompt = ChatPromptTemplate.from_messages([
                ("system", "{system}"),
                ("human", "{user}"),
            ])
            table_llm = _build_langchain_llm(max_tokens=_max_tokens)
            table_chain = table_prompt | table_llm

            raw = ""
            try:
                start = time.perf_counter()
                _msg = table_chain.invoke({"system": system_prompt, "user": user_prompt})
                _record_langchain_usage(_msg, elapsed_ms=int((time.perf_counter() - start) * 1000))
                raw = _msg.content if hasattr(_msg, "content") else str(_msg)

                if trace_capture is not None:
                    trace_capture["llm_raw_response"] = raw

                _write_agent_trace(
                    step="generate_table",
                    module=module,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    llm_raw_response=raw,
                    extra={"segments": segments, "indexes": indexes},
                )

                cleaned = raw.strip()
                if "```" in cleaned:
                    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
                    if m:
                        cleaned = m.group(1)

                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError:
                    m = re.search(r"\[[\s\S]*\]", cleaned)
                    if not m:
                        raise
                    data = json.loads(m.group(0))

                if not isinstance(data, list):
                    raise ValueError("Expected list of lists from table generation")

                result = _repair_table(data, segments)

                logger.info(
                    "CS agent table done module=%s rows=%d cols=%d elapsed_ms=%d",
                    module,
                    len(result),
                    len(segments),
                    int((time.perf_counter() - start) * 1000),
                )
                return result

            except Exception as exc:
                logger.exception(
                    "CS agent table generation failed module=%s err=%s raw=%s",
                    module,
                    exc,
                    raw[:400],
                )
                raise

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        file_ids: list[str],
        n_segments: int,
        indexes: list[str],
        module: str = "customer segmentation",
        trace_capture: dict[str, Any] | None = None,
        cowork_guidance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Run the full CS agent pipeline.

        All steps use targeted retrieval via the evidence pipeline rather than
        receiving a pre-built full-content dump, keeping every LLM call within
        the model's token limit regardless of how many files are uploaded.

        When cowork_guidance is provided (from End conversation summary), its
        methodology guide steers segment synthesis from the uploaded data instead
        of locking in provisional names agreed during the conversation.

        Step 0: doc-level facet cache lookup — skips steps 1+2 for mature files.
        Step 1: classify maturity (only on cache miss, uses broad retrieval).
        Step 2: extract/synthesize segment names (uses targeted retrieval);
                methodology-guided when cowork_guidance is present.
        Step 3: generate table (always, uses segment+row-label targeted retrieval).

        Returns:
            {
              "segment_names": list[str],   # 2 ≤ len ≤ n_segments
              "table_data":    list[list[str]],
              "maturity":      str,          # for observability
              "facet_cache_hit": bool,
            }
        """
        start = time.perf_counter()
        logger.info(
            "CS agent run start module=%s n_segments=%d indexes=%d file_ids=%s cowork_guidance=%s",
            module,
            n_segments,
            len(indexes),
            file_ids,
            bool(cowork_guidance),
        )

        facet_cache_hit = False
        maturity = "totally_raw"
        maturity_from_cache = False
        segments: list[str] = []

        # ── Cowork guidance path: use methodology to guide segment synthesis ──
        # When a cowork summary (methodology guide) is present, use it to steer
        # segment identification from the uploaded data rather than locking in
        # provisional names agreed during the conversation.
        if cowork_guidance and cowork_guidance.get("summary"):
            methodology = cowork_guidance["summary"]
            facet_cache_hit = True
            maturity = "cowork_guided"

            # Use full document content for methodology-guided synthesis so the LLM sees
            # all segment definitions; retrieval returns only top-k snippets and often
            # misses key content (e.g. only [evidence:1] from the first page).
            from generation.context_provider import get_full_markdown_context

            synth_content = get_full_markdown_context(file_ids)
            if not synth_content or not synth_content.strip():
                # Fallback to retrieval if full content unavailable (e.g. _store empty).
                logger.warning(
                    "CS agent: get_full_markdown_context returned empty, falling back to retrieval file_ids=%s",
                    file_ids,
                )
                synth_content = self._retrieve_context(
                    file_ids,
                    "HCP physician prescriber behaviors attitudes barriers drivers treatment patterns segmentation",
                    module=module,
                )
            rendered_system = _SYNTHESIZE_WITH_METHODOLOGY_SYSTEM.format(
                methodology=methodology.strip(),
                min_segments=MIN_SEGMENTS,
                n_segments=n_segments,
            )
            rendered_user = _SYNTHESIZE_WITH_METHODOLOGY_USER.format(
                content=synth_content,
                n_segments=n_segments,
                min_segments=MIN_SEGMENTS,
            )
            if self._would_exceed_segment_prompt_budget(rendered_system, rendered_user):
                logger.warning(
                    "CS agent: methodology synthesis prompt too large; switching to retrieval context file_ids=%s",
                    file_ids,
                )
                synth_content = self._retrieve_context(
                    file_ids,
                    "HCP physician prescriber behaviors attitudes barriers drivers treatment patterns segmentation",
                    module=module,
                )
                synth_content = self._truncate_content_for_budget(
                    content=synth_content,
                    system_prompt=rendered_system,
                    user_template=_SYNTHESIZE_WITH_METHODOLOGY_USER,
                    user_template_args={
                        "n_segments": n_segments,
                        "min_segments": MIN_SEGMENTS,
                    },
                )

            segments = self._synthesize_with_methodology(
                synth_content, n_segments, module, methodology
            )

            # Fall back to any candidate directions from the brief if synthesis fails.
            if not segments and cowork_guidance.get("segment_names"):
                seg_names = cowork_guidance["segment_names"]
                segments = [str(s).strip() for s in seg_names if str(s).strip()][:n_segments]
                logger.info(
                    "CS agent: methodology synthesis failed, falling back to candidate directions=%s",
                    segments,
                )

            # Enforce constraints: 2 ≤ count ≤ n_segments
            segments = [s for s in segments if s][:n_segments]
            while len(segments) < MIN_SEGMENTS:
                segments.append(f"Segment {len(segments) + 1}")
            # Do NOT call _mark_segments_missing_in_uploaded_files here: methodology-guided
            # synthesis produces inferred labels (e.g. "Efficacy-Driven Pioneer") that
            # summarize evidence conceptually; they are not verbatim strings from the docs.

            logger.info(
                "CS agent: cowork methodology-guided segments resolved module=%s segments=%s",
                module,
                segments,
            )
            table_data = self._generate_table(
                file_ids,
                segments,
                indexes,
                module,
                trace_capture=trace_capture,
                cowork_summary=methodology,
            )
            return {
                "segment_names": segments,
                "table_data": table_data,
                "maturity": maturity,
                "facet_cache_hit": facet_cache_hit,
            }

        # ── Step 0: check doc-level facet cache ───────────────────────────
        # Highest-maturity file (optionally filtered by topic) wins and
        # provides a maturity hint; segments are always generated per run.
        if file_ids:
            with stage_scope("cs_agent_doc_facet_lookup"):
                try:
                    from retriever.doc_facet_cache import get_doc_facet_cache
                    cache = get_doc_facet_cache()
                    cached_maturity = cache.get_best_maturity(
                        file_ids, topic_preference="customer segmentation"
                    )
                    has_any_entry = any(cache.get(fid) is not None for fid in file_ids)
                    if has_any_entry:
                        maturity_from_cache = True
                        facet_cache_hit = True
                        maturity = cached_maturity
                        logger.info(
                            "CS agent: doc facet cache hit module=%s maturity=%s",
                            module,
                            maturity,
                        )
                except Exception as exc:
                    logger.warning(
                        "CS agent: doc facet cache lookup failed module=%s err=%s; falling back to LLM classify",
                        module,
                        exc,
                    )

        # ── Steps 1 + 2: classify + segment names ──────────────────────────
        if not maturity_from_cache:
            # Retrieve a broad sample sufficient for maturity classification.
            classify_content = self._retrieve_context(
                file_ids,
                "HCP customer segmentation analysis segment names maturity",
                module=module,
            )
            maturity = self._classify(classify_content, module)

        if maturity == "mature":
            from generation.context_provider import get_full_markdown_context

            extract_content = get_full_markdown_context(file_ids)
            if not extract_content or not extract_content.strip():
                logger.warning(
                    "CS agent: get_full_markdown_context returned empty for extract, falling back to retrieval file_ids=%s",
                    file_ids,
                )
                extract_content = self._retrieve_context(
                    file_ids,
                    "HCP segment names customer segmentation",
                    module=module,
                )
            rendered_system = _EXTRACT_SYSTEM.format(
                n_segments=n_segments, min_segments=MIN_SEGMENTS
            )
            rendered_user = _EXTRACT_USER.format(
                content=extract_content,
                n_segments=n_segments,
                min_segments=MIN_SEGMENTS,
            )
            if self._would_exceed_segment_prompt_budget(rendered_system, rendered_user):
                logger.warning(
                    "CS agent: extract prompt too large; switching to retrieval context file_ids=%s",
                    file_ids,
                )
                extract_content = self._retrieve_context(
                    file_ids,
                    "HCP segment names customer segmentation",
                    module=module,
                )
                extract_content = self._truncate_content_for_budget(
                    content=extract_content,
                    system_prompt=rendered_system,
                    user_template=_EXTRACT_USER,
                    user_template_args={
                        "n_segments": n_segments,
                        "min_segments": MIN_SEGMENTS,
                    },
                )
            segments = self._extract_segments(extract_content, n_segments, module)
        else:
            from generation.context_provider import get_full_markdown_context

            synth_content = get_full_markdown_context(file_ids)
            if not synth_content or not synth_content.strip():
                logger.warning(
                    "CS agent: get_full_markdown_context returned empty for synthesize, falling back to retrieval file_ids=%s",
                    file_ids,
                )
                synth_content = self._retrieve_context(
                    file_ids,
                    "HCP physician prescriber behaviors attitudes barriers drivers treatment patterns",
                    module=module,
                )
            rendered_system = _SYNTHESIZE_SYSTEM.format(
                n_segments=n_segments, min_segments=MIN_SEGMENTS
            )
            rendered_user = _SYNTHESIZE_USER.format(
                content=synth_content,
                n_segments=n_segments,
                min_segments=MIN_SEGMENTS,
            )
            if self._would_exceed_segment_prompt_budget(rendered_system, rendered_user):
                logger.warning(
                    "CS agent: synthesize prompt too large; switching to retrieval context file_ids=%s",
                    file_ids,
                )
                synth_content = self._retrieve_context(
                    file_ids,
                    "HCP physician prescriber behaviors attitudes barriers drivers treatment patterns",
                    module=module,
                )
                synth_content = self._truncate_content_for_budget(
                    content=synth_content,
                    system_prompt=rendered_system,
                    user_template=_SYNTHESIZE_USER,
                    user_template_args={
                        "n_segments": n_segments,
                        "min_segments": MIN_SEGMENTS,
                    },
                )
            segments = self._synthesize_segments(synth_content, n_segments, module)

        # Enforce constraints: 2 ≤ count ≤ n_segments
        segments = [s for s in segments if s][:n_segments]
        while len(segments) < MIN_SEGMENTS:
            segments.append(f"Segment {len(segments) + 1}")

        logger.info(
            "CS agent segments resolved module=%s maturity=%s facet_cache_hit=%s segments=%s",
            module,
            maturity,
            facet_cache_hit,
            segments,
        )

        # ── Step 3: generate table content (always required) ──────────────
        # _generate_table performs its own targeted retrieval internally.
        table_data = self._generate_table(
            file_ids, segments, indexes, module, trace_capture=trace_capture
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "CS agent run done module=%s maturity=%s facet_cache_hit=%s segments=%s rows=%d elapsed_ms=%d",
            module,
            maturity,
            facet_cache_hit,
            segments,
            len(table_data),
            elapsed_ms,
        )

        return {
            "segment_names": segments,
            "table_data": table_data,
            "maturity": maturity,
            "facet_cache_hit": facet_cache_hit,
        }
