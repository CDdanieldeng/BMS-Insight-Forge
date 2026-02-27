"""Orchestrator: coordinates retriever, fill engine, and LLM."""

import json
import re
import time
from typing import Any

from shared.logging_config import setup_logging

from generation.key_questions import get_questions_for_module
from generation.llm_client import complete

logger = setup_logging("generation")

# Lazy imports to avoid circular deps
def _retriever_search(file_ids: list[str], query: str) -> str:
    from retriever.router import _store
    start = time.perf_counter()
    texts = []
    found = 0
    for fid in file_ids:
        if fid in _store:
            texts.append(_store[fid])
            found += 1
    combined = "\n\n---\n\n".join(texts)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "Retriever search done file_ids=%d found=%d query_len=%d content_len=%d elapsed_ms=%d",
        len(file_ids),
        found,
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
        query = complete(system, user)
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


def generate_table_content(
    module: str,
    table_structure: dict[str, Any],
    retriever_content: str,
) -> list[list[str]]:
    """
    Use LLM to generate table cell values from retriever content and table structure.
    Returns 2D list: rows of cell values (excluding header row and index column).
    """
    questions = get_questions_for_module(module)
    columns = table_structure.get("columns", [])
    indexes = table_structure.get("indexes", [])

    # Filter out empty column header
    data_columns = [c for c in columns if c and c.strip()]
    if not data_columns:
        data_columns = columns[1:] if len(columns) > 1 else columns

    system = """You are a business analyst. Fill the table based on the provided context and key business questions.
Output a JSON array of arrays. Each inner array is one row of data (excluding the header row).
The number of values per row must match the number of data columns.
Use concise, professional language. If context is insufficient, provide reasonable placeholder text.
Output ONLY valid JSON, no markdown or explanation."""

    user = f"""Context from support documents:
{retriever_content[:12000]}

Key business questions for {module}:
{chr(10).join(f'- {q}' for q in questions)}

Table structure:
- Column headers: {columns}
- Row labels (indexes): {indexes}

Generate table data as JSON array of arrays. Example format: [["val1","val2"],["val1","val2"],...]
Number of rows = {len(indexes)}, number of values per row = {len(data_columns)}"""

    try:
        start = time.perf_counter()
        raw = complete(system, user)
        # Extract JSON from response (handle markdown code blocks)
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

        logger.info("Generated table with %d rows", len(result))
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
{content[:14000]}
"""

    try:
        start = time.perf_counter()
        raw = complete(system, user).strip()
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
) -> list[list[str]]:
    """
    Orchestrate: enhance query -> retriever -> generate table content.
    """
    start = time.perf_counter()
    logger.info(
        "run_fill start slide_idx=%d module=%s file_ids=%d table_rows=%d table_cols=%d",
        slide_idx,
        module,
        len(file_ids),
        len(table_structure.get("indexes", [])),
        len(table_structure.get("columns", [])),
    )

    query = enhance_query(module, table_structure)
    logger.info("Enhanced query: %s", query[:100])

    content = _retriever_search(file_ids, query)
    logger.info("Retriever returned %d chars", len(content))

    table_data = generate_table_content(module, table_structure, content)
    logger.info(
        "run_fill done slide_idx=%d module=%s output_rows=%d elapsed_ms=%d",
        slide_idx,
        module,
        len(table_data),
        int((time.perf_counter() - start) * 1000),
    )
    return table_data
