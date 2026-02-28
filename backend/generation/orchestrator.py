"""Orchestrator: coordinates retriever, fill engine, and LLM."""

import json
import re
import time
from typing import Any

from shared.logging_config import setup_logging

from generation.key_questions import get_questions_for_module
from generation.llm_client import complete
from generation.slide_prompts import get_prompt_builder

logger = setup_logging("generation")

# Matches placeholder column names like "Segment 1", "segment 3", "SEGMENT 4"
_SEGMENT_PLACEHOLDER_RE = re.compile(r"^segment\s+\d+$", re.IGNORECASE)

# Module-level cache: module_name -> extracted segment names.
# Populated on the first slide that triggers extraction; reused on subsequent
# slides of the same module within the same backend session.
_segment_name_cache: dict[str, list[str]] = {}


def _has_placeholder_columns(columns: list[str]) -> bool:
    """
    Return True if ALL non-empty column headers are generic placeholders
    like 'Segment 1', 'Segment 2', etc. — meaning they need to be replaced
    with real names extracted from the uploaded documents.
    """
    data_cols = [c.strip() for c in columns if c.strip()]
    return bool(data_cols) and all(_SEGMENT_PLACEHOLDER_RE.match(c) for c in data_cols)

# Lazy imports to avoid circular deps
def _retriever_search(file_ids: list[str], query: str, top_k: int = 16) -> str:
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

    # ── Try slide-specific prompt builder ────────────────────────────────────
    prompt_builder = get_prompt_builder(module)
    if prompt_builder is not None:
        logger.info("Using slide-specific prompt for module=%s", module)
        system, user = prompt_builder(
            retriever_content[:8000],
            indexes,
            data_columns,
        )
    else:
        # ── Generic fallback prompt ───────────────────────────────────────────
        questions = get_questions_for_module(module)
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
            f"Context from support documents:\n{retriever_content[:8000]}\n\n"
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
            "IMPORTANT: Each cell value MUST be 18 words or fewer. Be concise and direct."
        )

    # Cap output: ~80 tokens per cell × rows × cols, with a buffer
    _max_out = min(4000, max(1500, len(indexes) * len(data_columns) * 80))

    try:
        start = time.perf_counter()
        raw = complete(system, user, max_tokens=_max_out)
        raw = raw.strip()
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

    content = _retriever_search(file_ids, query="; ".join(questions[:3]))
    if not content:
        logger.info(
            "Key answers fallback module=%s reason=no_retriever_content questions=%d",
            module,
            len(questions),
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
{content[:8000]}
"""

    try:
        start = time.perf_counter()
        raw = complete(system, user, max_tokens=800).strip()
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

    query = enhance_query(module, table_structure)
    logger.info("Enhanced query: %s", query[:100])

    content = _retriever_search(file_ids, query)
    logger.info("Retriever returned %d chars", len(content))

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
    table_data = generate_table_content(
        module, table_structure, content, segment_names=segment_names
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
