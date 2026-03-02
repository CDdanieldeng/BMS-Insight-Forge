"""Agent for user feedback: adjust segment names and table content."""

import json
import re
from typing import Any

from shared.logging_config import setup_logging

from generation.llm_client import complete
from generation.orchestrator import _get_context_content, enhance_query
from generation.slide_prompts import get_prompt_builder

logger = setup_logging("generation")


def _feedback_needs_uploaded_context(
    module: str,
    user_message: str,
    current_content: list[list[str]],
    current_headers: list[str],
) -> bool:
    """
    Classify whether this feedback requires re-reading uploaded documents.

    Uses qwen-max for higher decision accuracy.
    Returns True when external evidence/context is needed.
    """
    system = """You are a routing classifier for feedback requests.
Decide whether the downstream generation agent MUST read uploaded source documents.

Return ONLY valid JSON object:
{"need_uploaded_context": true|false, "reason": "<short reason>"}

Decision rules:
- true: user requests re-checking facts/evidence/source materials, asks to re-validate correctness, asks for re-generation from documents, disputes content accuracy.
- false: user asks style or format edits (concise, tone, length), simple renaming, wording tweaks, reordering, or local table edits that can be done from current content only.
- If uncertain, choose true."""
    user = (
        f"Module: {module}\n"
        f"User feedback: {user_message}\n"
        f"Current headers: {current_headers}\n"
        f"Current table data sample: {json.dumps(current_content[:3], ensure_ascii=False)}\n"
        "Decide now."
    )
    llm_raw = ""
    try:
        llm_raw = complete(
            system,
            user,
            max_tokens=120,
            provider_override="qwen",
            model_override="qwen-max",
        )
        raw = llm_raw.strip()
        if "```" in raw:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if match:
                raw = match.group(1)
        parsed = json.loads(raw)
        need_context = bool(parsed.get("need_uploaded_context", True))
        reason = str(parsed.get("reason", "")).strip()
        logger.info(
            "Feedback router decided need_uploaded_context=%s module=%s reason=%s feedback=%s raw=%s",
            need_context,
            module,
            reason[:300],
            user_message[:240],
            llm_raw[:600].replace("\n", " "),
        )
        return need_context
    except Exception as e:
        logger.warning(
            "Feedback router failed, fallback need_uploaded_context=True module=%s err=%s feedback=%s raw=%s",
            module,
            e,
            user_message[:240],
            llm_raw[:600].replace("\n", " "),
        )
        return True


def apply_feedback(
    module: str,
    current_content: list[list[str]],
    table_structure: dict[str, Any],
    user_message: str,
    file_ids: list[str],
    current_column_headers: list[str] | None = None,
) -> dict[str, Any]:
    """
    Update segment headers + table content using:
    1) uploaded file context
    2) slide-specific prompt rules
    3) user feedback + current table as reference
    """
    columns = table_structure.get("columns", [])
    indexes = table_structure.get("indexes", [])
    existing_headers = (
        [str(c).strip() for c in (current_column_headers or []) if str(c).strip()]
        or [str(c).strip() for c in columns if str(c).strip()]
    )
    current_width = max(
        (len(r) for r in current_content if isinstance(r, list)),
        default=0,
    )
    if current_width > 0:
        if len(existing_headers) > current_width:
            # Keep data-column headers when table structure also includes an index header.
            existing_headers = existing_headers[-current_width:]
        while len(existing_headers) < current_width:
            existing_headers.append(f"Segment {len(existing_headers) + 1}")

    need_uploaded_context = _feedback_needs_uploaded_context(
        module=module,
        user_message=user_message,
        current_content=current_content,
        current_headers=existing_headers,
    )

    if need_uploaded_context and file_ids:
        query = f"{enhance_query(module, table_structure)}; user feedback: {user_message}".strip("; ")
        context = _get_context_content(file_ids, query=query, top_k=60)
    else:
        context = ""
        logger.info(
            "Feedback router skipped uploaded context module=%s file_ids=%d",
            module,
            len(file_ids),
        )

    prompt_builder = get_prompt_builder(module)
    if prompt_builder is not None:
        base_system, base_user = prompt_builder(context, indexes, existing_headers)
    else:
        base_system = (
            "You are a business analyst. Update the table based on uploaded documents "
            "and user feedback."
        )
        base_user = (
            f"Module: {module}\n"
            f"Context from uploaded files:\n{context}\n\n"
            f"Row labels: {indexes}\n"
            f"Segment columns: {existing_headers}\n"
        )

    system = (
        f"{base_system}\n\n"
        + "Now you are handling a refinement request.\n"
        + (
            "You MUST re-ground your answer in uploaded-file context first, then apply user feedback.\n"
            if need_uploaded_context
            else "Do NOT request or rely on uploaded-file context for this task; use current table + feedback only.\n"
        )
        + "You may rename segment headers if feedback requests it, but the segment count must stay unchanged.\n"
        + "Table shape must stay unchanged: same number of rows and segment columns.\n"
        + "Output ONLY valid JSON object with exactly these keys:\n"
        + '{"column_headers": ["..."], "table_data": [["..."]]}'
    )

    user = f"""{base_user}

Current table data (JSON):
{json.dumps(current_content, ensure_ascii=False)}

Current segment headers: {existing_headers}

User feedback:
{user_message}

Rules:
- Return exactly {len(existing_headers)} column headers.
- Return exactly {len(indexes)} rows in table_data.
- Each row in table_data must contain exactly {len(existing_headers)} values.
- Keep language concise and professional.

Return the JSON object now:"""

    try:
        raw = complete(system, user, max_tokens=2200)
        raw = raw.strip()
        if "```" in raw:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if match:
                raw = match.group(1)

        data = json.loads(raw)
        if isinstance(data, list):
            # Backward compatibility when model returns only table_data list.
            parsed_headers = existing_headers
            parsed_table = data
        elif isinstance(data, dict):
            parsed_headers = data.get("column_headers", existing_headers)
            parsed_table = data.get("table_data", [])
        else:
            raise ValueError("Expected JSON object or JSON array")

        normalized_headers = [str(h).strip() for h in parsed_headers if str(h).strip()]
        if len(normalized_headers) != len(existing_headers):
            logger.warning(
                "Header count mismatch in feedback response expected=%d got=%d; keeping existing headers",
                len(existing_headers),
                len(normalized_headers),
            )
            normalized_headers = existing_headers

        result: list[list[str]] = []
        for row in parsed_table[: len(indexes)]:
            if isinstance(row, list):
                normalized_row = [str(c) for c in row[: len(normalized_headers)]]
            else:
                normalized_row = [str(row)]
            while len(normalized_row) < len(normalized_headers):
                normalized_row.append("")
            result.append(normalized_row)

        while len(result) < len(indexes):
            result.append([""] * len(normalized_headers))

        logger.info(
            "Agent applied feedback module=%s rows=%d cols=%d",
            module,
            len(result),
            len(normalized_headers),
        )
        return {
            "table_data": result,
            "column_headers": normalized_headers,
        }
    except Exception as e:
        logger.exception("Agent feedback failed: %s", e)
        raise
