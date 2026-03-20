"""Orchestrator: coordinates retriever, fill engine, and LLM."""

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

from generation.context_provider import (
    get_context_content,
    get_full_markdown_context,
)
from generation.module_handlers import (
    is_messaging_strategy_slide3,
    merge_context_for_slide,
    postprocess_table_for_slide,
)
from generation.utils import has_placeholder_columns, normalize_label
from generation.segment_extractor import extract_segment_names
from generation.stage_metrics import run_scope, stage_scope
from generation.table_generator import generate_table_content
from generation.session_cache import (
    get_segment_names,
    set_segment_names,
    set_slide_table,
)
from generation.trace_writer import (
    write_fill_trace,
    write_key_answers_trace,
    write_segment_header_trace,
)
from shared.llm_client import complete

logger = setup_logging("generation")


def _should_write_fill_trace(slide_idx: int, module: str) -> bool:
    """Enable fill trace persistence for all slides/modules."""
    return True


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
            questions: list[str] = []
            if not questions:
                logger.info("Key answers skipped module=%s reason=no_questions", module)
                return []

        with stage_scope("key_question_retrieval"):
            content = get_context_content(
                file_ids,
                query="; ".join(questions[:3]),
                module=module,
                table_structure={"columns": [], "indexes": questions},
            )
            if not content:
                logger.info(
                    "Key answers fallback module=%s reason=no_context_content questions=%d",
                    module,
                    len(questions),
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
                write_key_answers_trace(
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
    cowork_guidance: dict[str, Any] | None = None,
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
        is_ms_slide3 = is_messaging_strategy_slide3(module, indexes)
        _is_cs = normalize_label(module) == "customer segmentation"
        is_swot = normalize_label(module) == "swot analysis"

        # ── Customer Segmentation Agent path ──────────────────────────────────
        # When the CS module has placeholder columns (first CS slide), delegate
        # the entire segment-identification + table-generation pipeline to the
        # CustomerSegmentationAgent.  Subsequent CS slides hit the cache path
        # below and continue through the standard retrieval flow.
        # When cowork_guidance is provided (from End conversation summary), the
        # agent uses the methodology guide to drive segment identification from data.
        if has_placeholder_columns(placeholder_cols) and not is_ms_slide3 and _is_cs:
            with stage_scope("customer_segmentation_agent"):
                use_cowork = bool(cowork_guidance and cowork_guidance.get("summary"))
                if use_cowork:
                    logger.info(
                        "CS agent: using cowork methodology guidance module=%s",
                        module,
                    )
                if get_segment_names(module, slide_idx) is not None and not use_cowork:
                    # Cache hit: reuse segments (only valid for slide_idx > cached slide).
                    segment_names = get_segment_names(module, slide_idx)
                    logger.info(
                        "CS agent: reusing cached segment names module=%s names=%s",
                        module,
                        segment_names,
                    )
                else:
                    from modules._registry import get_module
                    provider = get_module(module)
                    agent = provider.get_table_fill_agent() if provider else None
                    if not agent:
                        raise RuntimeError(
                            f"No table fill agent for module {module!r}; "
                            "CustomerSegmentationProvider should be registered."
                        )
                    n_segments = len(placeholder_cols)
                    logger.info(
                        "CS agent: placeholder columns detected (%d), launching agent module=%s",
                        n_segments,
                        module,
                    )
                    fill_trace: dict[str, Any] | None = (
                        {} if _should_write_fill_trace(slide_idx, module) else None
                    )
                    agent_result = agent.run(
                        file_ids=file_ids,
                        n_segments=n_segments,
                        indexes=indexes,
                        module=module,
                        trace_capture=fill_trace,
                        cowork_guidance=cowork_guidance if use_cowork else None,
                    )
                    segment_names = agent_result["segment_names"]
                    table_data = agent_result["table_data"]
                    set_segment_names(module, segment_names, slide_idx)
                    logger.info(
                        "CS agent: done module=%s maturity=%s facet_cache_hit=%s segments=%s rows=%d",
                        module,
                        agent_result.get("maturity"),
                        agent_result.get("facet_cache_hit"),
                        segment_names,
                        len(table_data),
                    )

                    with stage_scope("trace_persist"):
                        if fill_trace is not None:
                            write_fill_trace(
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

                    with stage_scope("cache_update"):
                        set_slide_table(slide_idx, {
                            "slide_idx": slide_idx,
                            "module": module,
                            "column_headers": segment_names,
                            "indexes": indexes,
                            "table_data": table_data,
                        })

                    return {"table_data": table_data, "column_headers": segment_names}

        # ── Standard segment name resolution (non-CS or CS cache hit) ─────────
        if has_placeholder_columns(placeholder_cols) and not is_ms_slide3:
            with stage_scope("segment_name_resolution"):
                if get_segment_names(module, slide_idx) is not None:
                    segment_names = get_segment_names(module, slide_idx)
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
                    segment_seed_content = get_full_markdown_context(file_ids)
                    segment_names = extract_segment_names(
                        segment_seed_content,
                        n_segments,
                        module,
                        trace_writer=write_segment_header_trace,
                    )
                    set_segment_names(module, segment_names, slide_idx)
                    logger.info(
                        "Extracted and cached segment names for module=%s: %s",
                        module,
                        segment_names,
                    )

        effective_table_structure = table_structure
        if segment_names:
            effective_table_structure = dict(table_structure)
            effective_table_structure["columns"] = [""] + segment_names

        with stage_scope("context_retrieval"):
            content = get_context_content(
                file_ids,
                query="",
                module=module,
                table_structure=effective_table_structure,
            )
            logger.info("Context prepared chars=%d", len(content))

        # ── Context composition for MS slide 3 / SWOT ─────────────────────────────
        content = merge_context_for_slide(module, slide_idx, indexes, content)

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
        if is_ms_slide3:
            with stage_scope("messaging_strategy_slide3_postprocess"):
                table_data = postprocess_table_for_slide(module, slide_idx, table_data, indexes)

        with stage_scope("trace_persist"):
            if fill_trace is not None:
                write_fill_trace(
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
            set_slide_table(slide_idx, {
                "slide_idx": slide_idx,
                "module": module,
                "column_headers": effective_headers,
                "indexes": indexes,
                "table_data": table_data,
            })

        # For Messaging Strategy slide 3, preserve original PPT placeholder headers.
        response_headers = None if is_ms_slide3 else segment_names
        return {"table_data": table_data, "column_headers": response_headers}
