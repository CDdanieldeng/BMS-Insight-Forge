"""LangChain LCEL agent for Customer Segmentation.

Combines segment identification and table content generation into a single
coordinated pass:

  Step 1 – classify_maturity: determine whether uploaded files are
             totally_raw, semi_raw, or mature.
  Step 2 – extract_segments (mature) or synthesize_segments (raw/semi_raw):
             produce 2–n_segments mutually exclusive HCP segment names.
  Step 3 – generate_table: populate slide 1 table cells using the same
             row-level extraction rules as slide_prompts/customer_segmentation/slide1.py.
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
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from shared.logging_config import setup_logging
from generation.stage_metrics import stage_scope

logger = setup_logging("generation")

MIN_SEGMENTS = 2

_CS_AGENT_TRACE_DIR = (
    Path(__file__).resolve().parents[1] / "logs" / "cs_agent_llm"
)

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

Return ONLY a valid JSON flat array of segment name strings.
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


# The table generation prompt is delegated to slide1.build_prompts() to keep
# a single source of truth for extraction rules used in both initial generation
# and the feedback path.

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

        # Chains for each step using LCEL pipe operator
        self._classify_chain = self._classify_prompt | self._classify_llm | StrOutputParser()
        self._extract_chain = self._extract_prompt | self._segment_llm | StrOutputParser()
        self._synthesize_chain = self._synthesize_prompt | self._segment_llm | StrOutputParser()

    # ------------------------------------------------------------------
    # Step helpers
    # ------------------------------------------------------------------

    def _classify(self, content: str, module: str) -> str:
        """Classify file maturity. Returns 'totally_raw', 'semi_raw', or 'mature'."""
        with stage_scope("cs_agent_classify_maturity"):
            raw = ""
            try:
                start = time.perf_counter()
                raw = self._classify_chain.invoke({"content": content})
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
                raw = self._extract_chain.invoke({
                    "content": content,
                    "n_segments": n_segments,
                    "min_segments": MIN_SEGMENTS,
                })
                _write_agent_trace(
                    step="extract_segments",
                    module=module,
                    system_prompt=_EXTRACT_SYSTEM.format(n_segments=n_segments, min_segments=MIN_SEGMENTS),
                    user_prompt=_EXTRACT_USER.format(
                        content=content[:200] + "...",
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
                raw = self._synthesize_chain.invoke({
                    "content": content,
                    "n_segments": n_segments,
                    "min_segments": MIN_SEGMENTS,
                })
                _write_agent_trace(
                    step="synthesize_segments",
                    module=module,
                    system_prompt=_SYNTHESIZE_SYSTEM.format(n_segments=n_segments, min_segments=MIN_SEGMENTS),
                    user_prompt=_SYNTHESIZE_USER.format(
                        content=content[:200] + "...",
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

    def _generate_table(
        self,
        content: str,
        segments: list[str],
        indexes: list[str],
        module: str,
        trace_capture: dict[str, Any] | None = None,
    ) -> list[list[str]]:
        """Step 3: generate slide table content using slide1 prompt rules."""
        from generation.slide_prompts.customer_segmentation.slide1 import build_prompts

        with stage_scope("cs_agent_generate_table"):
            if not content.strip():
                logger.warning(
                    "CS agent: empty context for table generation module=%s rows=%d cols=%d",
                    module,
                    len(indexes),
                    len(segments),
                )
                return [
                    ["Not found in provided materials." for _ in segments]
                    for _ in indexes
                ]

            system_prompt, user_prompt = build_prompts(content, indexes, segments)

            if trace_capture is not None:
                trace_capture["system_prompt"] = system_prompt
                trace_capture["user_prompt"] = user_prompt

            _max_tokens = min(4000, max(1500, len(indexes) * len(segments) * 80))
            table_prompt = ChatPromptTemplate.from_messages([
                ("system", "{system}"),
                ("human", "{user}"),
            ])
            table_llm = _build_langchain_llm(max_tokens=_max_tokens)
            table_chain = table_prompt | table_llm | StrOutputParser()

            raw = ""
            try:
                start = time.perf_counter()
                raw = table_chain.invoke({"system": system_prompt, "user": user_prompt})

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

                result: list[list[str]] = []
                for row in data:
                    if isinstance(row, list):
                        result.append([str(c) for c in row])
                    else:
                        result.append([str(row)])

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
        content: str,
        n_segments: int,
        indexes: list[str],
        module: str = "customer segmentation",
        trace_capture: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Run the full CS agent pipeline.

        Returns:
            {
              "segment_names": list[str],   # 2 ≤ len ≤ n_segments
              "table_data":    list[list[str]],
              "maturity":      str,          # for observability
            }
        """
        start = time.perf_counter()
        logger.info(
            "CS agent run start module=%s n_segments=%d indexes=%d content_len=%d",
            module,
            n_segments,
            len(indexes),
            len(content),
        )

        # Step 1: classify maturity
        maturity = self._classify(content, module)

        # Step 2: get segment names based on maturity
        if maturity == "mature":
            segments = self._extract_segments(content, n_segments, module)
        else:
            segments = self._synthesize_segments(content, n_segments, module)

        # Enforce constraints: 2 ≤ count ≤ n_segments
        segments = [s for s in segments if s][:n_segments]
        while len(segments) < MIN_SEGMENTS:
            segments.append(f"Segment {len(segments) + 1}")

        logger.info(
            "CS agent segments resolved module=%s maturity=%s segments=%s",
            module,
            maturity,
            segments,
        )

        # Step 3: generate table content
        table_data = self._generate_table(
            content, segments, indexes, module, trace_capture=trace_capture
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "CS agent run done module=%s maturity=%s segments=%s rows=%d elapsed_ms=%d",
            module,
            maturity,
            segments,
            len(table_data),
            elapsed_ms,
        )

        return {
            "segment_names": segments,
            "table_data": table_data,
            "maturity": maturity,
        }
