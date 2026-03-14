"""Agent for user feedback: adjust segment names and table content."""

import json
import re
from typing import Any

from shared.logging_config import setup_logging

from generation.llm_client import complete
from generation.orchestrator import _get_context_content
from generation.query_enhancer import enhance_query
from generation.slide_prompts import get_prompt_builder
from generation.stage_metrics import run_scope, stage_scope

logger = setup_logging("generation")


def _concise_assistant_message(text: str) -> str:
    """Keep assistant chat reply concise and readable for the UI."""
    raw = " ".join(str(text or "").strip().split())
    if not raw:
        return ""
    # Keep at most first 2 sentence-like chunks.
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", raw) if p.strip()]
    concise = " ".join(parts[:2]) if parts else raw
    # Hard cap for very verbose generations.
    if len(concise) > 180:
        concise = concise[:177].rstrip() + "..."
    return concise


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
    conversation_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Update segment headers + table content using:
    1) uploaded file context
    2) slide-specific prompt rules
    3) user feedback + current table as reference
    """
    with run_scope(
        operation="apply_feedback",
        module=module,
        metadata={"file_ids_count": len(file_ids)},
    ):
        return _apply_feedback_inner(
            module=module,
            current_content=current_content,
            table_structure=table_structure,
            user_message=user_message,
            file_ids=file_ids,
            current_column_headers=current_column_headers,
            conversation_history=conversation_history,
        )


def _apply_feedback_inner(
    module: str,
    current_content: list[list[str]],
    table_structure: dict[str, Any],
    user_message: str,
    file_ids: list[str],
    current_column_headers: list[str] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
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

    with stage_scope("feedback_routing"):
        need_uploaded_context = _feedback_needs_uploaded_context(
            module=module,
            user_message=user_message,
            current_content=current_content,
            current_headers=existing_headers,
        )

    if need_uploaded_context and file_ids:
        # enhance_query uses stage_scope("query_enhancement") internally
        query = f"{enhance_query(module, table_structure)}; user feedback: {user_message}".strip("; ")
        context = _get_context_content(
            file_ids,
            query=query,
            top_k=60,
            module=module,
            table_structure=table_structure,
        )
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
        + "Your assistant response must be concise: max 2 short sentences (<=180 chars), polite and professional.\n"
        + "Output ONLY valid JSON object with exactly these keys:\n"
        + '{"column_headers": ["..."], "table_data": [["..."]], "assistant_message": "..."}'
    )

    safe_history = conversation_history or []
    history_lines: list[str] = []
    for msg in safe_history[-12:]:
        role = str(msg.get("role", "")).strip().lower()
        content = str(msg.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            history_lines.append(f"{role}: {content}")
    history_block = "\n".join(history_lines) if history_lines else "(none)"

    user = f"""{base_user}

Current table data (JSON):
{json.dumps(current_content, ensure_ascii=False)}

Current segment headers: {existing_headers}

Conversation history for this slide only:
{history_block}

User feedback:
{user_message}

Rules:
- Return exactly {len(existing_headers)} column headers.
- Return exactly {len(indexes)} rows in table_data.
- Each row in table_data must contain exactly {len(existing_headers)} values.
- assistant_message should clearly explain what changed in this round.
- assistant_message must be <=2 short sentences and <=180 characters.
- Keep language concise, polite, professional, and warm.

Return the JSON object now:"""

    try:
        with stage_scope("feedback_apply"):
            raw = complete(system, user, max_tokens=4000)
            raw = raw.strip()
            if "```" in raw:
                match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
                if match:
                    raw = match.group(1)

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # LLM truncated mid-JSON (hit token limit). Attempt to salvage
                # whatever rows were emitted before the cut-off.
                logger.warning(
                    "feedback_apply: JSON truncated by LLM, attempting partial recovery"
                )
                # Extract column_headers if present
                hdr_match = re.search(
                    r'"column_headers"\s*:\s*(\[[^\]]*\])', raw, re.DOTALL
                )
                # Extract every complete row already present in table_data
                rows_match = re.findall(r'\[[^\[\]]*\]', raw)
                # First match may be column_headers array itself; skip arrays of arrays
                extracted_rows = []
                for m in rows_match:
                    try:
                        parsed = json.loads(m)
                        if isinstance(parsed, list) and parsed and not isinstance(parsed[0], list):
                            extracted_rows.append(parsed)
                    except json.JSONDecodeError:
                        pass

                partial: dict[str, Any] = {}
                if hdr_match:
                    try:
                        partial["column_headers"] = json.loads(hdr_match.group(1))
                        # First row in extracted_rows may be the headers list; drop it
                        if extracted_rows and extracted_rows[0] == partial["column_headers"]:
                            extracted_rows = extracted_rows[1:]
                    except json.JSONDecodeError:
                        pass
                partial["table_data"] = extracted_rows
                partial["assistant_message"] = ""
                if not partial.get("column_headers") and not extracted_rows:
                    raise  # nothing salvageable – re-raise original error
                data = partial
            if isinstance(data, list):
                # Backward compatibility when model returns only table_data list.
                parsed_headers = existing_headers
                parsed_table = data
            elif isinstance(data, dict):
                parsed_headers = data.get("column_headers", existing_headers)
                parsed_table = data.get("table_data", [])
                assistant_message = str(data.get("assistant_message", "")).strip()
            else:
                raise ValueError("Expected JSON object or JSON array")
            if isinstance(data, list):
                assistant_message = ""

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
            assistant_message = _concise_assistant_message(assistant_message)
            if not assistant_message:
                assistant_message = (
                    "Thanks for your feedback. I have updated this slide while keeping "
                    "the original table structure unchanged."
                )
            return {
                "table_data": result,
                "column_headers": normalized_headers,
                "assistant_message": assistant_message,
            }
    except Exception as e:
        logger.exception("Agent feedback failed: %s", e)
        raise


def answer_question(  # decay: ask mode scheduled for removal
    module: str,
    current_content: list[list[str]],
    table_structure: dict[str, Any],
    user_message: str,
    file_ids: list[str],
    current_column_headers: list[str] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Answer user question in ask mode without modifying table content.

    This mode behaves like "ask-only": it uses uploaded files + current
    table snapshot to provide an answer, and never returns updated table data.
    """
    with run_scope(
        operation="answer_question",
        module=module,
        metadata={"file_ids_count": len(file_ids)},
    ):
        return _answer_question_inner(
            module=module,
            current_content=current_content,
            table_structure=table_structure,
            user_message=user_message,
            file_ids=file_ids,
            current_column_headers=current_column_headers,
            conversation_history=conversation_history,
        )


def _answer_question_inner(  # decay: ask mode scheduled for removal
    module: str,
    current_content: list[list[str]],
    table_structure: dict[str, Any],
    user_message: str,
    file_ids: list[str],
    current_column_headers: list[str] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
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
            existing_headers = existing_headers[-current_width:]
        while len(existing_headers) < current_width:
            existing_headers.append(f"Segment {len(existing_headers) + 1}")

    # enhance_query uses stage_scope("query_enhancement") internally
    query = f"{enhance_query(module, table_structure)}; user question: {user_message}".strip("; ")
    context = (
        _get_context_content(
            file_ids,
            query=query,
            top_k=60,
            module=module,
            table_structure=table_structure,
        )
        if file_ids
        else ""
    )

    safe_history = conversation_history or []
    history_lines: list[str] = []
    for msg in safe_history[-12:]:
        role = str(msg.get("role", "")).strip().lower()
        content = str(msg.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            history_lines.append(f"{role}: {content}")
    history_block = "\n".join(history_lines) if history_lines else "(none)"

    system = (  # decay: ask mode scheduled for removal
        "You are a business strategy copilot in ask-only mode.\n"
        "Your task is to answer the user's question using uploaded documents "
        "and the current slide table snapshot.\n"
        "Important: DO NOT propose or imply table edits unless user explicitly asks "
        "for recommendations; in ask-only mode we are not applying changes.\n"
        "If evidence is insufficient, state this clearly and suggest what data is missing.\n"
        "Keep answer concise, practical, and professional."
    )
    user = f"""Module: {module}
Uploaded context:
{context or "(no uploaded context found)"}

Current row labels: {indexes}
Current segment headers: {existing_headers}
Current table data (JSON):
{json.dumps(current_content, ensure_ascii=False)}

Conversation history:
{history_block}

User question:
{user_message}

Answer directly in plain text."""

    try:
        with stage_scope("answer_generation"):
            raw = complete(system, user, max_tokens=900)
            assistant_message = " ".join(str(raw or "").strip().split())
            if len(assistant_message) > 800:
                assistant_message = assistant_message[:797].rstrip() + "..."
            if not assistant_message:
                assistant_message = (
                    "I could not generate a reliable answer right now. "
                    "Please try rephrasing the question."
                )
            return {"assistant_message": assistant_message}
    except Exception as e:
        logger.exception("Ask-mode answer failed: %s", e)  # decay: ask mode scheduled for removal
        raise
