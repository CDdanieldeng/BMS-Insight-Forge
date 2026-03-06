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
from generation.pipeline_config import load_pipeline_config
from generation.query_enhancer import enhance_query
from generation.segment_extractor import extract_segment_names
from generation.slide_prompts import get_prompt_builder
from generation.stage_metrics import run_scope, stage_scope
from generation.evidence_pipeline import run_evidence_pipeline

logger = setup_logging("generation")

_KEY_ANSWERS_TRACE_DIR = (
    Path(__file__).resolve().parents[1] / "logs" / "key_question_llm"
)
_FILL_TRACE_DIR = (
    Path(__file__).resolve().parents[1] / "logs" / "slide_fill_llm"
)
_SEGMENT_HEADER_TRACE_DIR = (
    Path(__file__).resolve().parents[1] / "logs" / "segment_header_extraction_llm"
)

# Matches placeholder column names like "Segment 1", "segment 3", "SEGMENT 4"
_SEGMENT_PLACEHOLDER_RE = re.compile(r"^segment\s+\d+$", re.IGNORECASE)

# Module-level cache: module_name -> extracted segment names.
# Populated on the first slide that triggers extraction; reused on subsequent
# slides of the same module within the same backend session.
_segment_name_cache: dict[str, list[str]] = {}

# Module-level cache: slide_idx -> generated table metadata.
# Used to provide prior slide table outputs as context for downstream slides.
_slide_table_cache: dict[int, dict[str, Any]] = {}

_MESSAGING_STRATEGY_SLIDE3_INDEXES = [
    "target/prioritized segment",
    "drivers/barriers",
    "desired behavior change",
    "differentiated competitive benefit",
    "reason to believe",
    "business objective",
]


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


def _write_segment_header_trace_file(
    *,
    module: str,
    n_segments: int,
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
) -> None:
    """
    Persist segment-header extraction prompt/response for debugging.
    """
    try:
        _SEGMENT_HEADER_TRACE_DIR.mkdir(parents=True, exist_ok=True)
        module_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (module or "").strip().lower()).strip("_")
        if not module_slug:
            module_slug = "module"
        file_name = (
            f"{time.strftime('%Y%m%d_%H%M%S')}_{module_slug}_segments{n_segments}_{uuid.uuid4().hex[:8]}.txt"
        )
        file_path = _SEGMENT_HEADER_TRACE_DIR / file_name

        text = (
            f"module: {module}\n"
            f"segments_requested: {n_segments}\n"
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
            "Segment header trace file written module=%s segments=%d path=%s",
            module,
            n_segments,
            file_path,
        )
    except Exception as e:
        logger.warning(
            "Failed to write segment header trace file module=%s segments=%d err=%s",
            module,
            n_segments,
            e,
        )


def _should_write_fill_trace(slide_idx: int, module: str) -> bool:
    """Enable fill trace persistence for all slides/modules."""
    return True


def _has_placeholder_columns(columns: list[str]) -> bool:
    """
    Return True if ALL non-empty column headers are generic placeholders
    like 'Segment 1', 'Segment 2', etc. — meaning they need to be replaced
    with real names extracted from the uploaded documents.
    """
    data_cols = [c.strip() for c in columns if c.strip()]
    return bool(data_cols) and all(_SEGMENT_PLACEHOLDER_RE.match(c) for c in data_cols)


def _normalize_label(label: str) -> str:
    return " ".join((label or "").strip().lower().split())


def _is_messaging_strategy_slide3(module: str, indexes: list[str]) -> bool:
    if _normalize_label(module) != "messaging strategy":
        return False
    return [_normalize_label(i) for i in indexes] == _MESSAGING_STRATEGY_SLIDE3_INDEXES


def _format_cached_table_context(cached: dict[str, Any]) -> str:
    slide_idx = int(cached.get("slide_idx", -1))
    module = str(cached.get("module", ""))
    headers = [str(h) for h in (cached.get("column_headers") or [])]
    indexes = [str(i) for i in (cached.get("indexes") or [])]
    table_data = cached.get("table_data") or []

    lines: list[str] = [
        f"Slide {slide_idx} ({module})",
        f"Columns: {headers}",
    ]
    for row_idx, row_label in enumerate(indexes):
        row_values = table_data[row_idx] if row_idx < len(table_data) else []
        lines.append(f'- {row_label}: {row_values}')
    return "\n".join(lines)


def _build_prior_table_primary_context(current_slide_idx: int) -> str:
    """Return formatted context from the two latest slides before current slide."""
    prior_slides = sorted(idx for idx in _slide_table_cache if idx < current_slide_idx)[-2:]
    if not prior_slides:
        return ""
    return "\n\n".join(_format_cached_table_context(_slide_table_cache[idx]) for idx in prior_slides)


def _is_high_priority(value: str) -> bool:
    return bool(re.match(r"^\s*high\b", (value or "").strip(), flags=re.IGNORECASE))


def _extract_prioritized_segments_from_customer_segmentation(
    current_slide_idx: int,
) -> list[str]:
    """
    Extract prioritized segment names from the latest prior customer segmentation
    slide that contains a 'Segment Prioritization' row.
    """
    candidate_slides = sorted(idx for idx in _slide_table_cache if idx < current_slide_idx)
    for idx in reversed(candidate_slides):
        cached = _slide_table_cache[idx]
        if _normalize_label(str(cached.get("module", ""))) != "customer segmentation":
            continue

        headers = [str(h).strip() for h in (cached.get("column_headers") or []) if str(h).strip()]
        row_labels = [str(r).strip() for r in (cached.get("indexes") or [])]
        table_data = cached.get("table_data") or []
        normalized_rows = [_normalize_label(r) for r in row_labels]
        if "segment prioritization" not in normalized_rows:
            continue

        row_idx = normalized_rows.index("segment prioritization")
        if row_idx >= len(table_data):
            continue
        row_values = table_data[row_idx] or []

        prioritized: list[str] = []
        for col_idx, cell in enumerate(row_values):
            if not _is_high_priority(str(cell)):
                continue
            if col_idx < len(headers):
                prioritized.append(headers[col_idx])

        if prioritized:
            return prioritized
    return []

# Lazy imports to avoid circular deps
def _retriever_search(
    file_ids: list[str],
    query: str,
    module: str = "",
    table_structure: dict[str, Any] | None = None,
    top_k: int = 50,
) -> str:
    from retriever.router import _chunk_store
    start = time.perf_counter()
    all_chunks = []
    found = 0
    for fid in file_ids:
        if fid in _chunk_store:
            all_chunks.extend(_chunk_store[fid])
            found += 1
    config = load_pipeline_config()
    pipeline_result = run_evidence_pipeline(
        file_ids=file_ids,
        module=module,
        table_structure=table_structure or {},
        seed_query=query,
        config=config,
        top_k_fallback=top_k,
    )
    combined = pipeline_result.context_text
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "Retriever search done file_ids=%d found=%d total_chunks=%d query_len=%d content_len=%d degraded=%s metrics=%s elapsed_ms=%d",
        len(file_ids),
        found,
        len(all_chunks),
        len(query or ""),
        len(combined),
        pipeline_result.degraded,
        pipeline_result.metrics,
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


def _get_context_content(
    file_ids: list[str],
    query: str,
    top_k: int = 50,
    module: str = "",
    table_structure: dict[str, Any] | None = None,
) -> str:
    """
    Select context source based on USE_RETRIEVER toggle.
    USE_RETRIEVER=true  -> BM25 top-k chunks (current default flow)
    USE_RETRIEVER=false -> full cleaned markdown content
    """
    if _use_retriever():
        return _retriever_search(
            file_ids,
            query,
            module=module,
            table_structure=table_structure,
            top_k=top_k,
        )
    return _full_markdown_context(file_ids)


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
    with stage_scope("table_content_generation"):
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

        # If context is empty (common after dev-server reload clears in-memory stores),
        # avoid calling LLM and return a deterministic matrix instead of raising 500.
        if not (retriever_content or "").strip():
            logger.warning(
                "Empty context for table generation module=%s rows=%d cols=%d; using Not found fallback",
                module,
                len(indexes),
                len(data_columns),
            )
            return [
                ["Not found in provided materials." for _ in data_columns]
                for _ in indexes
            ]

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

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Some models prepend/append prose around JSON. Try extracting the
                # first JSON array block before failing.
                match = re.search(r"\[[\s\S]*\]", raw)
                if not match:
                    raise
                data = json.loads(match.group(0))
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
    with run_scope(
        operation="generate_key_question_answers",
        module=module,
        metadata={"file_ids_count": len(file_ids)},
    ):
        with stage_scope("key_question_prepare"):
            questions = get_questions_for_module(module)
            if not questions:
                logger.info("Key answers skipped module=%s reason=no_questions", module)
                return []

        with stage_scope("key_question_retrieval"):
            content = _get_context_content(
                file_ids,
                query="; ".join(questions[:3]),
                module=module,
                table_structure={"columns": [], "indexes": questions},
            )
            if not content:
                logger.info(
                    "Key answers fallback module=%s reason=no_context_content questions=%d use_retriever=%s",
                    module,
                    len(questions),
                    _use_retriever(),
                )
                return [
                    {"question": q, "answer": "No relevant content found in uploaded files."}
                    for q in questions
                ]

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

        with stage_scope("key_question_answer_generation"):
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
                        answer = (
                            str(item.get("answer", "")).strip()
                            or "Insufficient evidence in uploaded documents."
                        )
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

    with run_scope(
        operation="run_fill",
        module=module,
        slide_idx=slide_idx,
        metadata={
            "file_ids_count": len(file_ids),
            "table_rows": len(indexes),
            "table_cols": len(columns),
        },
    ):
        # ── Segment name extraction (pre-query) ────────────────────────────────
        # Resolve placeholder headers before query enhancement so retrieval query
        # can include real segment semantics instead of "Segment 1/2/...".
        segment_names: list[str] | None = None
        placeholder_cols = [c.strip() for c in columns if c.strip()]
        is_ms_slide3 = _is_messaging_strategy_slide3(module, indexes)

        if _has_placeholder_columns(placeholder_cols) and not is_ms_slide3:
            with stage_scope("segment_name_resolution"):
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
                        "Placeholder columns detected (%d). Resolving segment names before query enhancement.",
                        n_segments,
                    )
                    segment_seed_content = _full_markdown_context(file_ids)
                    segment_names = extract_segment_names(
                        segment_seed_content,
                        n_segments,
                        module,
                        trace_writer=_write_segment_header_trace_file,
                    )
                    _segment_name_cache[module] = segment_names
                    logger.info(
                        "Extracted and cached segment names for module=%s: %s",
                        module,
                        segment_names,
                    )

        effective_table_structure = table_structure
        if segment_names:
            effective_table_structure = dict(table_structure)
            effective_table_structure["columns"] = [""] + segment_names

        use_retriever = _use_retriever()
        with stage_scope("query_preparation"):
            if use_retriever:
                query = enhance_query(module, effective_table_structure)
                logger.info("Enhanced query: %s", query[:100])
            else:
                query = ""
                logger.info("Retriever disabled (USE_RETRIEVER=false), skipping query enhancement")

        with stage_scope("context_retrieval"):
            content = _get_context_content(
                file_ids,
                query,
                module=module,
                table_structure=effective_table_structure,
            )
            logger.info(
                "Context prepared chars=%d mode=%s",
                len(content),
                "retriever" if use_retriever else "full_markdown",
            )

        # ── Context composition for Messaging Strategy slide 3 ───────────────────
        if is_ms_slide3:
            with stage_scope("context_merge_messaging_strategy_slide3"):
                prior_table_context = _build_prior_table_primary_context(slide_idx)
                uploaded_materials_context = content
                if prior_table_context:
                    content = (
                        "PRIMARY INPUT: PREVIOUS CUSTOMER SEGMENTATION TABLES\n"
                        f"{prior_table_context}\n\n"
                        "SECONDARY INPUT: UPLOADED MATERIALS\n"
                        f"{uploaded_materials_context}"
                    )
                    logger.info(
                        "Messaging Strategy slide3 context merged with prior tables slide_idx=%d prior_chars=%d uploaded_chars=%d merged_chars=%d",
                        slide_idx,
                        len(prior_table_context),
                        len(uploaded_materials_context),
                        len(content),
                    )
                else:
                    content = (
                        "PRIMARY INPUT: PREVIOUS CUSTOMER SEGMENTATION TABLES\n"
                        "(none)\n\n"
                        "SECONDARY INPUT: UPLOADED MATERIALS\n"
                        f"{uploaded_materials_context}"
                    )
                    logger.info(
                        "Messaging Strategy slide3 has no prior table cache slide_idx=%d; using uploaded materials as fallback",
                        slide_idx,
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

        # ── Hard post-process for Messaging Strategy slide 3 ───────────────────
        # Keep original placeholder headers and force row-1 to prioritized segment names.
        if is_ms_slide3:
            with stage_scope("messaging_strategy_slide3_postprocess"):
                prioritized_segments = _extract_prioritized_segments_from_customer_segmentation(slide_idx)
                normalized_indexes = [_normalize_label(i) for i in indexes]
                if "target/prioritized segment" in normalized_indexes and table_data:
                    target_row_idx = normalized_indexes.index("target/prioritized segment")
                    if target_row_idx < len(table_data):
                        col_count = len(table_data[target_row_idx])
                        if col_count > 0:
                            if prioritized_segments:
                                repeated = [
                                    prioritized_segments[i % len(prioritized_segments)]
                                    for i in range(col_count)
                                ]
                                table_data[target_row_idx] = repeated
                                logger.info(
                                    "Messaging Strategy slide3 prioritized segments applied slide_idx=%d segments=%s",
                                    slide_idx,
                                    prioritized_segments,
                                )
                            else:
                                logger.info(
                                    "Messaging Strategy slide3 prioritized segments unavailable slide_idx=%d; keeping model output",
                                    slide_idx,
                                )

        with stage_scope("trace_persist"):
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

        # Cache current slide output for downstream slide context composition.
        with stage_scope("cache_update"):
            effective_headers = segment_names or [c.strip() for c in columns if c.strip()]
            _slide_table_cache[slide_idx] = {
                "slide_idx": slide_idx,
                "module": module,
                "column_headers": effective_headers,
                "indexes": indexes,
                "table_data": table_data,
            }

        # For Messaging Strategy slide 3, preserve original PPT placeholder headers.
        response_headers = None if is_ms_slide3 else segment_names
        return {"table_data": table_data, "column_headers": response_headers}
