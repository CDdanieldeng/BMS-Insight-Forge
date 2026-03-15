"""Module-specific search query enhancement for retriever."""

import re
import time
import uuid
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

from generation.key_questions import get_questions_for_module
from shared.llm_client import complete
from generation.stage_metrics import stage_scope

logger = setup_logging("retriever")

_QUERY_TRACE_DIR = (
    Path(__file__).resolve().parents[1] / "logs" / "query_enhance_llm"
)


def _normalize_label(label: str) -> str:
    return " ".join((label or "").strip().lower().split())


def _write_query_trace_file(
    *,
    module: str,
    mode: str,
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
    final_query: str,
) -> None:
    """Persist query-enhancer prompts and output for auditing/debugging."""
    try:
        _QUERY_TRACE_DIR.mkdir(parents=True, exist_ok=True)
        module_slug = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "_",
            (module or "").strip().lower(),
        ).strip("_")
        if not module_slug:
            module_slug = "module"
        file_name = (
            f"{time.strftime('%Y%m%d_%H%M%S')}_{module_slug}_{mode}_{uuid.uuid4().hex[:8]}.txt"
        )
        file_path = _QUERY_TRACE_DIR / file_name
        text = (
            f"module: {module}\n"
            f"mode: {mode}\n"
            f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            "\n=== SYSTEM PROMPT ===\n"
            + (system_prompt or "")
            + "\n\n=== USER PROMPT ===\n"
            + (user_prompt or "")
            + "\n\n=== LLM RAW RESPONSE ===\n"
            + (llm_raw_response or "")
            + "\n\n=== FINAL QUERY ===\n"
            + (final_query or "")
            + "\n"
        )
        file_path.write_text(text, encoding="utf-8")
        logger.info("Query enhancer trace written module=%s path=%s", module, file_path)
    except Exception as e:
        logger.warning("Failed to write query enhancer trace module=%s err=%s", module, e)


def _module_table_structure_prompt(
    module: str,
    columns: list[Any],
    indexes: list[Any],
) -> tuple[str, str, str]:
    """
    Return module-specific prompt tuple: (mode, system, user).
    """
    normalized_module = _normalize_label(module)

    if normalized_module == "customer segmentation":
        system = """You are a query enhancer for pharmaceutical business planning.
Your task is to convert ONLY table structure signals into a concise retrieval query.
The query should guide search in source materials for evidence needed by each (column, row-index) pair.
Focus on customer segmentation analysis in pharma: patient/HCP segments, treatment journey, unmet needs, drivers/barriers, value potential, channel preference, and strategic implications.
Output ONLY one concise English search query, no explanation."""
        user = (
            f"Module: {module}\n"
            "Business context: We are preparing a business plan for a pharmaceutical company.\n"
            f"Table columns: {columns}\n"
            f"Table row indexes: {indexes}\n"
            "Generate the search query now:"
        )
        return "customer_segmentation_table_only", system, user

    if normalized_module == "messaging strategy":
        system = """You are a query enhancer for pharmaceutical go-to-market planning.
Your task is to convert ONLY table structure signals into a concise retrieval query.
The query should guide search in source materials for evidence needed by each (column, row-index) pair.
Focus on messaging strategy in pharma: target/prioritized segments, behavior drivers/barriers, desired behavior change, differentiated benefit, reason-to-believe, and business objectives.
Output ONLY one concise English search query, no explanation."""
        user = (
            f"Module: {module}\n"
            "Business context: We are preparing a business plan for a pharmaceutical company.\n"
            f"Table columns: {columns}\n"
            f"Table row indexes: {indexes}\n"
            "Generate the search query now:"
        )
        return "messaging_strategy_table_only", system, user

    if normalized_module == "swot analysis":
        system = """You are a query enhancer for pharmaceutical business planning.
Your task is to convert the SWOT table structure into a concise retrieval query.
SWOT tables use ONLY the four column names as the guide: Strengths, Weaknesses, Opportunities, Threats.
Do NOT use row indexes. Focus search on finding evidence for each of the four SWOT quadrants.
Output ONLY one concise English search query, no explanation."""
        user = (
            f"Module: {module}\n"
            "Business context: We are preparing a business plan for a pharmaceutical company.\n"
            f"Table columns (use these as the main guide): {columns}\n"
            "Generate the search query now:"
        )
        return "swot_table_only", system, user

    system = """You are a search query enhancer. Given the business key questions and table structure.
Output a single, concise search query (in English) that would help retrieve relevant content to answer these questions and fill the table.
Output ONLY the search query, no explanation."""
    questions = get_questions_for_module(module)
    user = f"""Key business questions:
{chr(10).join(f'- {q}' for q in questions)}

Table columns: {columns}
Table row indexes: {indexes}

Generate search query:"""
    return "generic", system, user


def enhance_query(module: str, table_structure: dict[str, Any]) -> str:
    """
    Build LLM-enhanced search query.

    - customer segmentation / messaging strategy:
      Keep key business questions as-is, only enhance table-structure part.
    - other modules:
      Use generic question+table enhancement.
    """
    with stage_scope("query_enhancement"):
        columns = table_structure.get("columns", [])
        indexes = table_structure.get("indexes", [])
        questions = get_questions_for_module(module)
        normalized_module = _normalize_label(module)
        mode, system, user = _module_table_structure_prompt(module, columns, indexes)

        llm_raw = ""
        final_query = ""
        try:
            start = time.perf_counter()
            llm_raw = complete(system, user, max_tokens=180)
            table_query = llm_raw.strip().strip('"').strip("'")

            if normalized_module in {"customer segmentation", "messaging strategy"}:
                question_query = "; ".join(q.strip() for q in questions if q and q.strip())
                final_query = "; ".join(part for part in [question_query, table_query] if part).strip()
            elif normalized_module == "swot analysis":
                question_query = "; ".join(q.strip() for q in questions if q and q.strip())
                final_query = "; ".join(part for part in [question_query, table_query] if part).strip()
            else:
                final_query = table_query

            logger.info(
                "Enhance query done module=%s mode=%s questions=%d columns=%d indexes=%d result_len=%d elapsed_ms=%d",
                module,
                mode,
                len(questions),
                len(columns),
                len(indexes),
                len(final_query),
                int((time.perf_counter() - start) * 1000),
            )
            return final_query
        except Exception as e:
            logger.warning("LLM enhance query failed, using fallback module=%s err=%s", module, e)
            if normalized_module in {"customer segmentation", "messaging strategy", "swot analysis"}:
                final_query = "; ".join(q.strip() for q in questions if q and q.strip())
            else:
                final_query = " ".join(questions[:2]) if questions else ""
            return final_query
        finally:
            _write_query_trace_file(
                module=module,
                mode=mode,
                system_prompt=system,
                user_prompt=user,
                llm_raw_response=llm_raw,
                final_query=final_query,
            )
