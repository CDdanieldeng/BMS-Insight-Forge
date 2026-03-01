"""Orchestrator: coordinates retriever, fill engine, and LLM."""

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

from generation.key_questions import get_questions_for_module
from generation.llm_client import complete
from generation.slide_prompts import get_prompt_builder

logger = setup_logging("generation")

_KEY_ANSWERS_TRACE_DIR = (
    Path(__file__).resolve().parents[1] / "logs" / "key_question_llm"
)
_FILL_TRACE_DIR = (
    Path(__file__).resolve().parents[1] / "logs" / "slide_fill_llm"
)

# Matches placeholder column names like "Segment 1", "segment 3", "SEGMENT 4"
_SEGMENT_PLACEHOLDER_RE = re.compile(r"^segment\s+\d+$", re.IGNORECASE)

# Module-level cache: module_name -> extracted segment names.
# Populated on the first slide that triggers extraction; reused on subsequent
# slides of the same module within the same backend session.
_segment_name_cache: dict[str, list[str]] = {}


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean-like environment variable with a safe default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _use_retriever() -> bool:
    """Whether to use BM25 retriever before LLM prompting."""
    return _env_flag("USE_RETRIEVER", default=True)


def _write_key_answers_trace_file(
    module: str,
    questions: list[str],
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
) -> None:
    """
    Persist key-question LLM trace to a text file for debugging/auditing.
    Includes questions, full prompts, and raw model output.
    """
    try:
        _KEY_ANSWERS_TRACE_DIR.mkdir(parents=True, exist_ok=True)
        module_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (module or "").strip().lower()).strip("_")
        if not module_slug:
            module_slug = "module"
        file_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{module_slug}_{uuid.uuid4().hex[:8]}.txt"
        file_path = _KEY_ANSWERS_TRACE_DIR / file_name

        text = (
            f"module: {module}\n"
            f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"questions_count: {len(questions)}\n\n"
            "=== KEY BUSINESS QUESTIONS ===\n"
            + ("\n".join(f"- {q}" for q in questions) if questions else "(none)")
            + "\n\n=== SYSTEM PROMPT ===\n"
            + (system_prompt or "")
            + "\n\n=== USER PROMPT ===\n"
            + (user_prompt or "")
            + "\n\n=== LLM RAW RESPONSE ===\n"
            + (llm_raw_response or "")
            + "\n"
        )

        file_path.write_text(text, encoding="utf-8")
        logger.info("Key answers trace file written module=%s path=%s", module, file_path)
    except Exception as e:
        logger.warning("Failed to write key answers trace file module=%s err=%s", module, e)


def _write_fill_trace_file(
    *,
    slide_idx: int,
    module: str,
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
) -> None:
    """
    Persist fill trace for debugging LLM prompt/response.
    """
    try:
        _FILL_TRACE_DIR.mkdir(parents=True, exist_ok=True)
        module_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (module or "").strip().lower()).strip("_")
        if not module_slug:
            module_slug = "module"
        file_name = (
            f"{time.strftime('%Y%m%d_%H%M%S')}_{module_slug}_slide{slide_idx}_{uuid.uuid4().hex[:8]}.txt"
        )
        file_path = _FILL_TRACE_DIR / file_name

        text = (
            f"module: {module}\n"
            f"slide_idx: {slide_idx}\n"
            f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            "\n=== SYSTEM PROMPT ===\n"
            + (system_prompt or "")
            + "\n\n=== USER PROMPT ===\n"
            + (user_prompt or "")
            + "\n\n=== LLM RAW RESPONSE ===\n"
            + (llm_raw_response or "")
            + "\n"
        )
        file_path.write_text(text, encoding="utf-8")
        logger.info(
            "Fill trace file written module=%s slide_idx=%d path=%s",
            module,
            slide_idx,
            file_path,
        )
    except Exception as e:
        logger.warning(
            "Failed to write fill trace file module=%s slide_idx=%d err=%s",
            module,
            slide_idx,
            e,
        )


def _should_write_fill_trace(slide_idx: int, module: str) -> bool:
    """Only trace Customer Segmentation slide 1 unless explicitly expanded."""
    return slide_idx == 1 and (module or "").strip().lower() == "customer segmentation"


def _has_placeholder_columns(columns: list[str]) -> bool:
    """
    Return True if ALL non-empty column headers are generic placeholders
    like 'Segment 1', 'Segment 2', etc. — meaning they need to be replaced
    with real names extracted from the uploaded documents.
    """
    data_cols = [c.strip() for c in columns if c.strip()]
    return bool(data_cols) and all(_SEGMENT_PLACEHOLDER_RE.match(c) for c in data_cols)

# Lazy imports to avoid circular deps
def _retriever_search(file_ids: list[str], query: str, top_k: int = 50) -> str:
    from retriever.chunker import bm25_retrieve
    from retriever.router import _chunk_store
    start = time.perf_counter()
    all_chunks: list[str] = []
    found = 0
    for fid in file_ids:
        if fid in _chunk_store:
            all_chunks.extend(_chunk_store[fid])
            found += 1
    relevant = bm25_retrieve(all_chunks, query, top_k=top_k)
    combined = "\n\n---\n\n".join(relevant)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "Retriever search done file_ids=%d found=%d total_chunks=%d returned=%d query_len=%d content_len=%d elapsed_ms=%d",
        len(file_ids),
        found,
        len(all_chunks),
        len(relevant),
        len(query or ""),
        len(combined),
        elapsed_ms,
    )
    return combined


def _full_markdown_context(file_ids: list[str]) -> str:
    """
    Return full cleaned markdown for all file_ids in original upload order.
    """
    from retriever.router import _store

    start = time.perf_counter()
    texts: list[str] = []
    found = 0
    for fid in file_ids:
        text = _store.get(fid)
        if text:
            texts.append(text.strip())
            found += 1

    combined = "\n\n---\n\n".join(t for t in texts if t)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "Full markdown context done file_ids=%d found=%d content_len=%d elapsed_ms=%d",
        len(file_ids),
        found,
        len(combined),
        elapsed_ms,
    )
    return combined


def _get_context_content(file_ids: list[str], query: str, top_k: int = 50) -> str:
    """
    Select context source based on USE_RETRIEVER toggle.
    USE_RETRIEVER=true  -> BM25 top-k chunks (current default flow)
    USE_RETRIEVER=false -> full cleaned markdown content
    """
    if _use_retriever():
        return _retriever_search(file_ids, query, top_k=top_k)
    return _full_markdown_context(file_ids)


def enhance_query(module: str, table_structure: dict[str, Any]) -> str:
    """
    Build LLM-enhanced search query from key questions and table structure.
    """
    questions = get_questions_for_module(module)
    columns = table_structure.get("columns", [])
    indexes = table_structure.get("indexes", [])

    system = """You are a search query enhancer. Given the business key questions and table structure.
Output a single, concise search query (in English) that would help retrieve relevant content to answer these questions and fill the table.
Output ONLY the search query, no explanation."""

    user = f"""Key business questions:
{chr(10).join(f'- {q}' for q in questions)}

Table columns: {columns}
Table row indexes: {indexes}

Generate search query:"""

    try:
        start = time.perf_counter()
        query = complete(system, user, max_tokens=120)
        result = query.strip().strip('"').strip("'")
        logger.info(
            "Enhance query done module=%s questions=%d columns=%d indexes=%d result_len=%d elapsed_ms=%d",
            module,
            len(questions),
            len(columns),
            len(indexes),
            len(result),
            int((time.perf_counter() - start) * 1000),
        )
        return result
    except Exception as e:
        logger.warning("LLM enhance query failed, using fallback: %s", e)
        return " ".join(questions[:2]) if questions else ""


def extract_segment_names(
    retriever_content: str,
    n_segments: int,
    module: str,
) -> list[str]:
    """
    Use LLM to identify real customer segment names from uploaded documents.
    Returns exactly n_segments names. Falls back to generic names if content
    is insufficient.
    """
    system = f"""You are a business analyst specialising in customer segmentation.
Identify the {n_segments} most distinct customer segments described in the provided content.
Return ONLY a JSON array of {n_segments} short, specific segment name strings.
Each name should be 2–5 words (e.g. "Community Oncologists", "Academic KOLs", "PCPs").
If the content does not clearly describe segments, invent plausible placeholder names.
Output ONLY valid JSON, no explanation."""

    user = f"""Module: {module}
Number of segments needed: {n_segments}

Content from uploaded documents:
{retriever_content}

Return a JSON array of exactly {n_segments} segment names:"""

    try:
        start = time.perf_counter()
        raw = complete(system, user, max_tokens=150).strip()
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if m:
                raw = m.group(1)
        names = json.loads(raw)
        if not isinstance(names, list):
            raise ValueError("Expected a JSON list")
        # Ensure exactly n_segments entries
        names = [str(n).strip() for n in names[:n_segments]]
        while len(names) < n_segments:
            names.append(f"Segment {len(names) + 1}")
        logger.info(
            "Segment extraction done module=%s n=%d names=%s elapsed_ms=%d",
            module,
            n_segments,
            names,
            int((time.perf_counter() - start) * 1000),
        )
        return names
    except Exception as e:
        logger.warning("Segment extraction failed, using fallbacks: %s", e)
        return [f"Segment {i}" for i in range(1, n_segments + 1)]


def generate_table_content(
    module: str,
    table_structure: dict[str, Any],
    retriever_content: str,
    segment_names: list[str] | None = None,
    trace_capture: dict[str, Any] | None = None,
) -> list[list[str]]:
    """
    Use LLM to generate table cell values from retriever content and table structure.

    If a slide-specific prompt builder is registered for *module* it is used;
    otherwise falls back to the generic business-analyst prompt.

    If segment_names is provided they replace placeholder column headers in the
    prompt so the LLM generates content specific to each real segment.

    Returns 2D list: rows of cell values (excluding header row and index column).
    """
    columns = table_structure.get("columns", [])
    indexes = table_structure.get("indexes", [])

    # Determine effective column labels for the LLM prompt
    if segment_names:
        effective_columns = [""] + segment_names  # col 0 is the row-label corner
    else:
        effective_columns = columns

    data_columns = [c for c in effective_columns if c and c.strip()]
    if not data_columns:
        data_columns = effective_columns[1:] if len(effective_columns) > 1 else effective_columns

    retriever_chars_in_prompt = 0

    # ── Try slide-specific prompt builder ────────────────────────────────────
    prompt_builder = get_prompt_builder(module)
    if prompt_builder is not None:
        logger.info("Using slide-specific prompt for module=%s", module)
        system, user = prompt_builder(
            retriever_content,
            indexes,
            data_columns,
        )
        retriever_chars_in_prompt = len(retriever_content or "")
    else:
        # ── Generic fallback prompt ───────────────────────────────────────────
        questions = get_questions_for_module(module)
        context_for_prompt = retriever_content
        retriever_chars_in_prompt = len(context_for_prompt)
        system = (
            "You are a business analyst. Fill the table based on the provided context "
            "and key business questions.\n"
            "Output a JSON array of arrays. Each inner array is one row of data "
            "(excluding the header row).\n"
            "The number of values per row must match the number of data columns.\n"
            "Use concise, professional language. If context is insufficient, "
            "provide reasonable placeholder text.\n"
            "Output ONLY valid JSON, no markdown or explanation."
        )
        user = (
            f"Context from support documents:\n{context_for_prompt}\n\n"
            f"Key business questions for {module}:\n"
            + "\n".join(f"- {q}" for q in questions)
            + f"\n\nTable structure:\n"
            f"- Column headers (segments): {effective_columns}\n"
            f"- Row labels (attributes): {indexes}\n\n"
            "Generate table data as JSON array of arrays. "
            "Example format: [[\"val1\",\"val2\"],[\"val1\",\"val2\"],...]\n"
            "Each inner array corresponds to one row label. "
            "Values correspond to each segment column.\n"
            f"Number of rows = {len(indexes)}, "
            f"number of values per row = {len(data_columns)}\n"
            "IMPORTANT: Be concise and direct."
        )

    if trace_capture is not None:
        trace_capture["system_prompt"] = system
        trace_capture["user_prompt"] = user

    # Cap output: ~80 tokens per cell × rows × cols, with a buffer
    _max_out = min(4000, max(1500, len(indexes) * len(data_columns) * 80))
    logger.info(
        "LLM prompt context module=%s retriever_chars_in_prompt=%d retriever_total_chars=%d",
        module,
        retriever_chars_in_prompt,
        len(retriever_content or ""),
    )

    try:
        start = time.perf_counter()
        raw_response = complete(system, user, max_tokens=_max_out)
        if trace_capture is not None:
            trace_capture["llm_raw_response"] = raw_response

        raw = raw_response.strip()
        if "```" in raw:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if match:
                raw = match.group(1)

        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Expected list of lists")

        result = []
        for row in data:
            if isinstance(row, list):
                result.append([str(c) for c in row])
            else:
                result.append([str(row)])

        logger.info(
            "Table generation done module=%s rows=%d data_cols=%d context_len=%d elapsed_ms=%d",
            module,
            len(result),
            len(data_columns),
            len(retriever_content),
            int((time.perf_counter() - start) * 1000),
        )
        return result
    except Exception as e:
        logger.exception("LLM table generation failed: %s", e)
        raise


def generate_key_question_answers(module: str, file_ids: list[str]) -> list[dict[str, str]]:
    """
    Answer key business questions using retriever content and LLM.
    Returns [{"question": "...", "answer": "..."}, ...]
    """
    questions = get_questions_for_module(module)
    if not questions:
        logger.info("Key answers skipped module=%s reason=no_questions", module)
        return []

    content = _get_context_content(file_ids, query="; ".join(questions[:3]))
    if not content:
        logger.info(
            "Key answers fallback module=%s reason=no_context_content questions=%d use_retriever=%s",
            module,
            len(questions),
            _use_retriever(),
        )
        return [{"question": q, "answer": "No relevant content found in uploaded files."} for q in questions]

    system = """You are a business analyst. Answer each key business question using only the provided context.
Return ONLY valid JSON array. Each item must be:
{"question":"<exact question>", "answer":"<concise answer>"}
If context is insufficient, use this exact phrase: Insufficient evidence in uploaded documents."""

    user = f"""Module: {module}
Questions:
{chr(10).join(f'- {q}' for q in questions)}

Context:
{content}
"""

    try:
        start = time.perf_counter()
        raw_response = complete(system, user, max_tokens=1600)
        _write_key_answers_trace_file(
            module=module,
            questions=questions,
            system_prompt=system,
            user_prompt=user,
            llm_raw_response=raw_response,
        )
        logger.info(
            "Key answers LLM raw response module=%s response_len=%d response_text=%s",
            module,
            len(raw_response or ""),
            (raw_response or "")[:4000],
        )
        raw = raw_response.strip()
        if "```" in raw:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if match:
                raw = match.group(1)

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("Expected a JSON list")

        result: list[dict[str, str]] = []
        for i, item in enumerate(parsed):
            q = questions[i] if i < len(questions) else ""
            if isinstance(item, dict):
                question = str(item.get("question", q) or q)
                answer = str(item.get("answer", "")).strip() or "Insufficient evidence in uploaded documents."
            else:
                question = q
                answer = str(item).strip() or "Insufficient evidence in uploaded documents."
            result.append({"question": question, "answer": answer})

        # Ensure all configured questions have an answer row.
        if len(result) < len(questions):
            answered = {r["question"] for r in result}
            for q in questions:
                if q not in answered:
                    result.append(
                        {
                            "question": q,
                            "answer": "Insufficient evidence in uploaded documents.",
                        }
                    )

        logger.info(
            "Key answers done module=%s questions=%d answers=%d context_len=%d elapsed_ms=%d",
            module,
            len(questions),
            len(result),
            len(content),
            int((time.perf_counter() - start) * 1000),
        )
        return result
    except Exception as e:
        logger.exception("Key question answering failed: %s", e)
        return [{"question": q, "answer": "Answer generation failed."} for q in questions]


def run_fill(
    slide_idx: int,
    module: str,
    file_ids: list[str],
    table_structure: dict[str, Any],
) -> dict[str, Any]:
    """
    Orchestrate: enhance query -> retriever -> (optionally) extract segments
    -> generate table content.

    Returns:
        {
          "table_data":     list[list[str]],   # cell values (no header, no index col)
          "column_headers": list[str] | None,  # real segment names, or None if
                                               # columns were not placeholders
        }
    """
    start = time.perf_counter()
    columns = table_structure.get("columns", [])
    indexes = table_structure.get("indexes", [])
    logger.info(
        "run_fill start slide_idx=%d module=%s file_ids=%d table_rows=%d table_cols=%d",
        slide_idx,
        module,
        len(file_ids),
        len(indexes),
        len(columns),
    )

    use_retriever = _use_retriever()
    if use_retriever:
        query = enhance_query(module, table_structure)
        logger.info("Enhanced query: %s", query[:100])
    else:
        query = ""
        logger.info("Retriever disabled (USE_RETRIEVER=false), skipping query enhancement")

    content = _get_context_content(file_ids, query)
    logger.info(
        "Context prepared chars=%d mode=%s",
        len(content),
        "retriever" if use_retriever else "full_markdown",
    )

    # ── Segment name extraction ────────────────────────────────────────────
    # Column headers like "Segment 1", "Segment 2" are placeholders.
    # The cache is checked first: the first slide of a module triggers LLM
    # extraction; every subsequent slide of the same module reuses the result,
    # keeping all slides consistent and saving one LLM call per extra slide.
    segment_names: list[str] | None = None
    placeholder_cols = [c.strip() for c in columns if c.strip()]

    if _has_placeholder_columns(placeholder_cols):
        if module in _segment_name_cache:
            segment_names = _segment_name_cache[module]
            logger.info(
                "Reusing cached segment names for module=%s: %s",
                module,
                segment_names,
            )
        else:
            n_segments = len(placeholder_cols)
            logger.info(
                "Placeholder columns detected (%d). Extracting real segment names.",
                n_segments,
            )
            segment_names = extract_segment_names(content, n_segments, module)
            _segment_name_cache[module] = segment_names
            logger.info(
                "Extracted and cached segment names for module=%s: %s",
                module,
                segment_names,
            )

    # ── Table content generation ───────────────────────────────────────────
    fill_trace: dict[str, Any] | None = {} if _should_write_fill_trace(slide_idx, module) else None
    table_data = generate_table_content(
        module,
        table_structure,
        content,
        segment_names=segment_names,
        trace_capture=fill_trace,
    )

    if fill_trace is not None:
        _write_fill_trace_file(
            slide_idx=slide_idx,
            module=module,
            system_prompt=str(fill_trace.get("system_prompt", "")),
            user_prompt=str(fill_trace.get("user_prompt", "")),
            llm_raw_response=str(fill_trace.get("llm_raw_response", "")),
        )

    logger.info(
        "run_fill done slide_idx=%d module=%s output_rows=%d column_headers=%s elapsed_ms=%d",
        slide_idx,
        module,
        len(table_data),
        segment_names,
        int((time.perf_counter() - start) * 1000),
    )
    return {"table_data": table_data, "column_headers": segment_names}
