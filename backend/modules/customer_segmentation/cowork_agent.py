"""Customer Segmentation cowork agent (starter consultant)."""

from __future__ import annotations

import re
from typing import Any

from modules.cowork.adapters import (
    ExistingDraftingService,
    ExistingFilePreparationService,
    ExistingPPTFillAdapter,
    ExistingRetrievalService,
    ExistingTemplateService,
    StubWebSearchService,
)
from modules.cowork.event_interpreter import interpret_event
from modules.cowork.interfaces import (
    DraftingService,
    FilePreparationService,
    PPTFillAdapter,
    RetrievalService,
    TemplateService,
    WebSearchServicePlaceholder,
)
from modules.cowork.llm_agent import generate_conversation_summary, generate_conversational_turn
from modules.cowork.models import (
    ChatMessage,
    ConversationPhase,
    CoworkSessionState,
    CoworkTurnRequest,
    CoworkTurnResponse,
    CoworkWorkflowMetadata,
    DirectUploadedDoc,
    EventType,
    SegmentationBrief,
    WorkflowState,
)
from modules.cowork.session_store import InMemorySessionStore, SessionStore
from modules.cowork.workflow import next_state


class CustomerSegmentationCoworkAgent:
    """Starter consultant for Customer Segmentation: gather brief, files, segment names."""

    def __init__(
        self,
        *,
        session_store: SessionStore | None = None,
        template_service: TemplateService | None = None,
        file_prep_service: FilePreparationService | None = None,
        retrieval_service: RetrievalService | None = None,
        drafting_service: DraftingService | None = None,
        web_search_service: WebSearchServicePlaceholder | None = None,
        ppt_fill_adapter: PPTFillAdapter | None = None,
    ) -> None:
        self.session_store = session_store or InMemorySessionStore()
        self.template_service = template_service or ExistingTemplateService()
        self.file_prep_service = file_prep_service or ExistingFilePreparationService()
        self.retrieval_service = retrieval_service or ExistingRetrievalService()
        self.drafting_service = drafting_service or ExistingDraftingService()
        self.web_search_service = web_search_service or StubWebSearchService()
        self.ppt_fill_adapter = ppt_fill_adapter or ExistingPPTFillAdapter()

    # ------------------------------------------------------------------ #
    # Session management                                                   #
    # ------------------------------------------------------------------ #

    def _load_or_create_session(self, req: CoworkTurnRequest) -> CoworkSessionState:
        existing = self.session_store.get(req.session_id)
        if existing:
            return existing
        return CoworkSessionState(session_id=req.session_id, module_name=req.module)

    def ensure_session(self, session_id: str, module: str) -> CoworkSessionState:
        existing = self.session_store.get(session_id)
        if existing:
            existing.module_name = module
            self.session_store.upsert(existing)
            return existing
        state = CoworkSessionState(session_id=session_id, module_name=module)
        self.session_store.upsert(state)
        return state

    def store_direct_upload_docs(
        self,
        *,
        session_id: str,
        module: str,
        docs: list[DirectUploadedDoc],
    ) -> CoworkSessionState:
        session = self.ensure_session(session_id, module)
        session.direct_uploaded_docs.extend(docs)
        session.direct_uploaded_docs = session.direct_uploaded_docs[-12:]
        session.missing_info_summary = (
            f"{len(session.direct_uploaded_docs)} cowork file(s) are now available in direct agent memory."
        )
        self.session_store.upsert(session)
        return session

    # ------------------------------------------------------------------ #
    # Brief management                                                     #
    # ------------------------------------------------------------------ #

    def _update_brief(
        self,
        session: CoworkSessionState,
        brief_update: Any,
        phase_assessment: str | None,
    ) -> None:
        """Apply LLM-provided brief updates and advance the conversation phase."""
        if brief_update and isinstance(brief_update, dict):
            brief = session.segmentation_brief
            if brief_update.get("business_objective"):
                brief.business_objective = str(brief_update["business_objective"])
            if brief_update.get("segmentation_lens"):
                brief.segmentation_lens = str(brief_update["segmentation_lens"])
            if brief_update.get("lens_rationale"):
                brief.lens_rationale = str(brief_update["lens_rationale"])
            if isinstance(brief_update.get("key_principles"), list):
                brief.key_principles = [str(p) for p in brief_update["key_principles"] if p]
            if isinstance(brief_update.get("segment_names"), list):
                names = [str(n).strip() for n in brief_update["segment_names"] if str(n).strip()]
                if len(names) >= 2:
                    brief.segment_names = names
                    if not self._segments_identified(session.working_draft.column_headers):
                        session.working_draft.column_headers = names

        if phase_assessment and isinstance(phase_assessment, str):
            try:
                session.conversation_phase = ConversationPhase(phase_assessment)
            except ValueError:
                pass

    # ------------------------------------------------------------------ #
    # Small helpers                                                        #
    # ------------------------------------------------------------------ #

    def _is_skip_signal(self, text: str) -> bool:
        msg = (text or "").strip().lower()
        if not msg:
            return False
        skip_tokens = {
            "skip", "skip it", "skip this", "no more info", "no more information",
            "not sure", "dont know", "don't know", "cannot provide", "can't provide", "no data",
        }
        return any(token in msg for token in skip_tokens)

    def _is_placeholder_segment_name(self, value: str) -> bool:
        return bool(re.match(r"^\s*segment\s+\d+\s*$", (value or ""), flags=re.IGNORECASE))

    def _segments_identified(self, headers: list[str]) -> bool:
        cleaned = [str(h).strip() for h in headers if str(h).strip()]
        if not cleaned:
            return False
        return not all(self._is_placeholder_segment_name(h) for h in cleaned)

    def _fill_not_provided_for_missing(
        self,
        *,
        table_data: list[list[str]],
        expected_rows: int,
        expected_cols: int,
    ) -> list[list[str]]:
        normalized: list[list[str]] = []
        for row in table_data[:expected_rows]:
            row_vals = [str(v).strip() for v in row[:expected_cols]]
            while len(row_vals) < expected_cols:
                row_vals.append("")
            normalized.append(row_vals)
        while len(normalized) < expected_rows:
            normalized.append([""] * expected_cols)
        for r_idx in range(expected_rows):
            for c_idx in range(expected_cols):
                if not normalized[r_idx][c_idx]:
                    normalized[r_idx][c_idx] = "Not provided"
        return normalized

    def _direct_docs_context(self, session: CoworkSessionState, max_chars: int = 14000) -> str:
        docs = session.direct_uploaded_docs[-8:]
        if not docs:
            return ""
        docs_with_content = [d for d in docs if (d.markdown_content or "").strip()]
        if not docs_with_content:
            return ""
        per_doc_budget = max(350, max_chars // len(docs_with_content))
        blocks: list[str] = []
        used = 0
        for doc in docs_with_content:
            header = f"[Cowork Upload] {doc.filename}\n"
            body = (doc.markdown_content or "").strip()
            remaining = max_chars - used
            if remaining <= 0:
                break
            doc_budget = min(per_doc_budget, remaining)
            chunk = body[: max(0, doc_budget - len(header))]
            block = header + chunk
            blocks.append(block)
            used += len(block)
        return "\n\n---\n\n".join(blocks)

    # ------------------------------------------------------------------ #
    # Main turn handler                                                    #
    # ------------------------------------------------------------------ #

    def handle_turn(self, req: CoworkTurnRequest) -> CoworkTurnResponse:
        session = self._load_or_create_session(req)
        session.module_name = req.module
        session.web_search_enabled = bool(req.allow_web_search)

        # Interpret event early so we can handle END_CONVERSATION before appending
        event = interpret_event(
            user_message=req.user_message,
            has_files=bool(req.file_ids),
            allow_web_search=req.allow_web_search,
            action=req.action,
        )

        # Load template once per session
        if session.template_metadata is None:
            session.current_state = WorkflowState.LOAD_TEMPLATE_CONTEXT
            session.template_metadata = self.template_service.load(req.slide_idx, req.table_structure)
            session.row_completion_status = {
                row: False for row in session.template_metadata.row_indexes
            }

        # --- End conversation: generate summary and return ---
        if event == EventType.END_CONVERSATION:
            summary = generate_conversation_summary(session)
            session.history.append(
                ChatMessage(role="assistant", content=summary)
            )
            self.session_store.upsert(session)
            # Use segment names from draft or brief for fill-slide guidance
            segment_names = (
                session.working_draft.column_headers
                or session.segmentation_brief.segment_names
            )
            return CoworkTurnResponse(
                assistant_message=summary,
                workflow=CoworkWorkflowMetadata(
                    session_id=session.session_id,
                    module_name=session.module_name,
                    state=session.current_state,
                    missing_info_summary="",
                    suggested_action="",
                    detected_intent="end_conversation",
                    next_step_recommendation="",
                    ready_for_ppt_fill=False,
                    confidence=None,
                ),
                draft_table_data=session.working_draft.table_data,
                draft_column_headers=segment_names,
                ppt_fill_payload=None,
                thinking=None,
            )

        session.history.append(ChatMessage(role="user", content=req.user_message))
        skip_requested = self._is_skip_signal(req.user_message)

        # --- Functional event branches (file ingestion, confirm fill) ---
        evidence_text = self._direct_docs_context(session, max_chars=3200)

        if event == EventType.FILES_ATTACHED:
            session.current_state = WorkflowState.FILE_PREPROCESSING
            session.uploaded_files = self.file_prep_service.preprocess(req.file_ids)
            session.current_state = WorkflowState.RETRIEVING_EVIDENCE
            retrieved_text = self.retrieval_service.retrieve(
                module=req.module,
                file_ids=req.file_ids,
                table_structure=req.table_structure,
                user_message=req.user_message,
            )
            evidence_text = (
                f"{evidence_text}\n\n---\n\n{retrieved_text}"
                if evidence_text and retrieved_text
                else (retrieved_text or evidence_text)
            )
            session.current_state = WorkflowState.DRAFTING_CONTENT
            table_data, headers = self.drafting_service.draft(
                slide_idx=req.slide_idx,
                module=req.module,
                file_ids=req.file_ids,
                table_structure=req.table_structure,
            )
            session.working_draft.table_data = table_data
            if headers:
                session.working_draft.column_headers = headers
                session.segmentation_brief.segment_names = headers
            session.current_state = WorkflowState.REVIEWING_WITH_USER

        elif event == EventType.WEB_PERMISSION_GRANTED and not req.file_ids:
            session.current_state = WorkflowState.WAITING_FOR_WEB_PERMISSION
            evidence_text = self.web_search_service.search(req.user_message)
            session.current_state = WorkflowState.RETRIEVING_EVIDENCE
            session.missing_info_summary = (
                "No support files uploaded yet. Web search is placeholder-only in this iteration."
            )

        elif event == EventType.CONFIRM_PPT_FILL and session.working_draft.table_data:
            session.current_state = WorkflowState.READY_FOR_PPT_FILL

        # --- Skip signal: pad draft with placeholders and signal readiness ---
        has_draft = bool(session.working_draft.table_data)
        if skip_requested and session.template_metadata is not None:
            expected_rows = len(session.template_metadata.row_indexes)
            expected_cols = max(
                len(session.working_draft.column_headers),
                len(session.template_metadata.segment_columns),
                len((req.table_structure.get("columns") or [])[1:]),
                1,
            )
            if not session.working_draft.column_headers:
                if session.template_metadata.segment_columns:
                    session.working_draft.column_headers = list(session.template_metadata.segment_columns)
                else:
                    session.working_draft.column_headers = [
                        f"Segment {i + 1}" for i in range(expected_cols)
                    ]
            session.working_draft.table_data = self._fill_not_provided_for_missing(
                table_data=session.working_draft.table_data,
                expected_rows=expected_rows,
                expected_cols=expected_cols,
            )
            has_draft = True
            session.conversation_phase = ConversationPhase.READY
            session.missing_info_summary = (
                "User chose to skip missing inputs. Remaining cells were marked as Not provided."
            )

        has_draft = bool(session.working_draft.table_data)
        segments_identified = self._segments_identified(session.working_draft.column_headers)

        # Advance workflow guardrail state
        session.current_state = next_state(session.current_state, event, has_draft=has_draft)

        # --- LLM consultant turn ---
        llm_turn = generate_conversational_turn(
            session=session,
            user_message=req.user_message,
            evidence_text=evidence_text,
            missing_info_summary=session.missing_info_summary,
            ready_for_ppt_fill=(session.current_state == WorkflowState.READY_FOR_PPT_FILL),
            segments_identified=segments_identified,
        )

        # Apply brief updates from LLM (may update segment names / column headers / phase)
        self._update_brief(session, llm_turn.get("brief_update"), llm_turn.get("phase_assessment"))

        # Re-evaluate after brief update (LLM may have named segments this turn)
        segments_identified = self._segments_identified(session.working_draft.column_headers)

        # Determine readiness for PPT fill
        ready_for_ppt_fill = session.current_state == WorkflowState.READY_FOR_PPT_FILL or (
            has_draft and "ready" in req.user_message.lower()
        )
        if session.conversation_phase == ConversationPhase.READY and has_draft and segments_identified:
            ready_for_ppt_fill = True
        if not segments_identified:
            ready_for_ppt_fill = False
        if skip_requested and has_draft:
            ready_for_ppt_fill = segments_identified
        if ready_for_ppt_fill:
            session.current_state = WorkflowState.READY_FOR_PPT_FILL

        assistant_message = str(llm_turn.get("response_text", "")).strip() or (
            "I have your latest input. Let's keep building the segmentation brief together — "
            "share any context that would help sharpen the direction."
        )
        session.history.append(ChatMessage(role="assistant", content=assistant_message))

        ppt_payload = None
        if ready_for_ppt_fill and session.working_draft.table_data:
            ppt_payload = self.ppt_fill_adapter.build_payload(
                slide_idx=req.slide_idx,
                table_data=session.working_draft.table_data,
                column_headers=session.working_draft.column_headers,
            )

        workflow = CoworkWorkflowMetadata(
            session_id=session.session_id,
            module_name=session.module_name,
            state=session.current_state,
            missing_info_summary=str(
                llm_turn.get("missing_info_summary") or session.missing_info_summary or ""
            ),
            suggested_action=str(llm_turn.get("suggested_action") or ""),
            detected_intent=str(llm_turn.get("detected_intent") or "unknown"),
            next_step_recommendation=str(llm_turn.get("next_step_recommendation") or ""),
            ready_for_ppt_fill=ready_for_ppt_fill,
            confidence=(
                float(llm_turn["confidence"])
                if isinstance(llm_turn.get("confidence"), (int, float))
                else None
            ),
        )

        self.session_store.upsert(session)
        return CoworkTurnResponse(
            assistant_message=assistant_message,
            thinking=str(llm_turn.get("thinking", "")).strip() or None,
            workflow=workflow,
            draft_table_data=session.working_draft.table_data,
            draft_column_headers=session.working_draft.column_headers,
            ppt_fill_payload=ppt_payload,
        )
