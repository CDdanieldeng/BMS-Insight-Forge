"""Simple orchestrator for SWOT cowork mode — conversational alignment only."""

from __future__ import annotations

from cowork_agent.event_interpreter import interpret_event
from cowork_agent.models import ChatMessage, DirectUploadedDoc, EventType
from cowork_agent.swot_llm_agent import generate_swot_summary, generate_swot_turn
from cowork_agent.swot_models import SwotCoworkSessionState


def _table_to_text(table_data: list[list[str]], headers: list[str] | None) -> str:
    """Convert table data to readable text for context."""
    if not table_data and not headers:
        return ""
    lines: list[str] = []
    if headers:
        lines.append(" | ".join(str(h) for h in headers))
    for row in table_data[:20]:
        lines.append(" | ".join(str(c) for c in row))
    return "\n".join(lines)


def _direct_docs_context(docs: list[DirectUploadedDoc], max_chars: int = 8000) -> str:
    """Build context string from uploaded documents."""
    if not docs:
        return ""
    blocks: list[str] = []
    used = 0
    per_doc = max(500, max_chars // len(docs))
    for doc in docs[-6:]:
        content = (doc.markdown_content or "").strip()
        if not content:
            continue
        chunk = content[: min(per_doc, max_chars - used)]
        blocks.append(f"[{doc.filename}]\n{chunk}")
        used += len(chunk)
        if used >= max_chars:
            break
    return "\n\n---\n\n".join(blocks)


class SwotCoworkOrchestrator:
    """Lightweight orchestrator for SWOT cowork — no drafting, no workflow states."""

    def __init__(self) -> None:
        self._sessions: dict[str, SwotCoworkSessionState] = {}

    def _load_or_create(self, session_id: str, module: str) -> SwotCoworkSessionState:
        existing = self._sessions.get(session_id)
        if existing:
            return existing
        state = SwotCoworkSessionState(session_id=session_id, module_name=module)
        self._sessions[session_id] = state
        return state

    def store_direct_upload_docs(
        self,
        *,
        session_id: str,
        module: str,
        docs: list[DirectUploadedDoc],
    ) -> SwotCoworkSessionState:
        session = self._load_or_create(session_id, module)
        session.direct_uploaded_docs.extend(docs)
        session.direct_uploaded_docs = session.direct_uploaded_docs[-10:]
        self._sessions[session_id] = session
        return session

    def handle_turn(self, req) -> dict:
        """Handle a SWOT cowork chat turn. Returns dict compatible with CoworkTurnResponse."""
        from cowork_agent.models import CoworkTurnRequest, CoworkTurnResponse, CoworkWorkflowMetadata

        session = self._load_or_create(req.session_id, req.module)

        # Build context from prior modules
        cs_summary = req.cs_cowork_summary if hasattr(req, "cs_cowork_summary") else None
        cs_table_text = ""
        if hasattr(req, "cs_filled_table") and req.cs_filled_table:
            headers = getattr(req, "cs_filled_headers", None) or []
            cs_table_text = _table_to_text(req.cs_filled_table, headers)

        uploaded_docs_text = _direct_docs_context(session.direct_uploaded_docs)

        event = interpret_event(
            user_message=req.user_message,
            has_files=bool(getattr(req, "file_ids", [])),
            allow_web_search=getattr(req, "allow_web_search", False),
            action=getattr(req, "action", None),
        )

        # End conversation: generate summary
        if event == EventType.END_CONVERSATION:
            summary = generate_swot_summary(session.history)
            session.history.append(ChatMessage(role="assistant", content=summary))
            self._sessions[req.session_id] = session
            return {
                "assistant_message": summary,
                "workflow": {
                    "session_id": session.session_id,
                    "module_name": session.module_name,
                    "state": "COMPLETED",
                    "missing_info_summary": "",
                    "suggested_action": "",
                    "detected_intent": "end_conversation",
                    "next_step_recommendation": "",
                    "ready_for_ppt_fill": False,
                    "confidence": None,
                },
                "draft_table_data": [],
                "draft_column_headers": [],
                "ppt_fill_payload": None,
                "thinking": None,
            }

        # Append user message and generate response
        session.history.append(ChatMessage(role="user", content=req.user_message))

        assistant_message = generate_swot_turn(
            history=session.history,
            user_message=req.user_message,
            cs_summary=cs_summary,
            cs_table_text=cs_table_text or None,
            uploaded_docs_text=uploaded_docs_text or None,
        )

        session.history.append(ChatMessage(role="assistant", content=assistant_message))
        self._sessions[req.session_id] = session

        return {
            "assistant_message": assistant_message,
            "workflow": {
                "session_id": session.session_id,
                "module_name": session.module_name,
                "state": "REVIEWING_WITH_USER",
                "missing_info_summary": "",
                "suggested_action": "",
                "detected_intent": "user_message",
                "next_step_recommendation": "",
                "ready_for_ppt_fill": False,
                "confidence": None,
            },
            "draft_table_data": [],
            "draft_column_headers": [],
            "ppt_fill_payload": None,
            "thinking": None,
        }
