"""Table content generation: LLM-based cell filling from retriever content."""

import json
import os
import re
import time
from typing import Any

from shared.logging_config import setup_logging

from shared.stage_metrics import stage_scope
from modules._slide_registry import get_prompt_builder
from shared.llm_client import complete

logger = setup_logging("generation")


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

        # SWOT: 4 columns (S,W,O,T), exactly 1 data row — different from CS segment tables
        is_swot = (module or "").strip().lower() == "swot analysis"
        if is_swot and not indexes:
            indexes = ["SWOT"]  # Exactly 1 row to fill

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
        elif is_swot:
            # ── SWOT: 4 columns, 1 data row — different from CS segment tables ─────
            # Content comes from Customer Segmentation (if in context) + uploaded files
            questions: list[str] = []
            context_for_prompt = retriever_content
            retriever_chars_in_prompt = len(context_for_prompt)
            col_guide = ", ".join(c for c in data_columns if c)
            system = (
                "You are a business analyst. Fill the SWOT table based on the provided context.\n"
                "The SWOT table has 4 columns (Strengths, Weaknesses, Opportunities, Threats) and exactly 1 data row. "
                "Unlike segment tables, there are no row indexes — the four column names are the ONLY guide.\n"
                "Synthesize content for each of the 4 cells from: (1) Customer Segmentation tables/summary if present, "
                "(2) uploaded market definition and competitor analysis documents.\n"
                "Output a JSON array with exactly ONE inner array of 4 values: [strengths_text, weaknesses_text, opportunities_text, threats_text].\n"
                "Use concise, professional language. If context is insufficient, provide reasonable placeholder text.\n"
                "Output ONLY valid JSON, no markdown or explanation."
            )
            user = (
                f"Context (Customer Segmentation + uploaded market/competitor documents):\n{context_for_prompt}\n\n"
                + (f"Key business questions for {module}:\n" + "\n".join(f"- {q}" for q in questions) + "\n\n" if questions else "")
                + f"Table columns (extract evidence for each): {col_guide}\n\n"
                "Generate exactly 1 row with 4 values. Format: [[\"strengths\",\"weaknesses\",\"opportunities\",\"threats\"]]"
            )
        else:
            # ── Generic fallback prompt ───────────────────────────────────────────
            questions: list[str] = []
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
            provider = os.getenv("LLM_PROVIDER", "openai").lower()
            model_override = "qwen-plus" if provider == "qwen" else None
            raw_response = complete(system, user, max_tokens=_max_out, model_override=model_override)
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
