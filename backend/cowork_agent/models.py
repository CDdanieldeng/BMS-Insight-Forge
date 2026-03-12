"""Typed models for CS cowork conversational workflow."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    INIT = "INIT"
    LOAD_TEMPLATE_CONTEXT = "LOAD_TEMPLATE_CONTEXT"
    WAITING_FOR_SUPPORT_FILES = "WAITING_FOR_SUPPORT_FILES"
    WAITING_FOR_WEB_PERMISSION = "WAITING_FOR_WEB_PERMISSION"
    FILE_PREPROCESSING = "FILE_PREPROCESSING"
    RETRIEVING_EVIDENCE = "RETRIEVING_EVIDENCE"
    DRAFTING_CONTENT = "DRAFTING_CONTENT"
    REVIEWING_WITH_USER = "REVIEWING_WITH_USER"
    READY_FOR_PPT_FILL = "READY_FOR_PPT_FILL"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class ConversationPhase(str, Enum):
    """Internal hidden phase — never surfaced directly to the user."""
    CONTEXT_DISCOVERY = "context_discovery"
    HYPOTHESIS_BUILDING = "hypothesis_building"
    REFINEMENT = "refinement"
    CONVERGENCE = "convergence"
    READY = "ready"


class SegmentationBrief(BaseModel):
    """Evolving working memory for the agreed segmentation guidance."""
    business_objective: str | None = None
    segmentation_lens: str | None = None
    lens_rationale: str | None = None
    key_principles: list[str] = Field(default_factory=list)
    segment_names: list[str] = Field(default_factory=list)


class EventType(str, Enum):
    USER_MESSAGE = "USER_MESSAGE"
    FILES_ATTACHED = "FILES_ATTACHED"
    WEB_PERMISSION_GRANTED = "WEB_PERMISSION_GRANTED"
    CONFIRM_PPT_FILL = "CONFIRM_PPT_FILL"
    END_CONVERSATION = "END_CONVERSATION"
    UNKNOWN = "UNKNOWN"


class ChatMessage(BaseModel):
    role: str
    content: str


class TemplateMetadata(BaseModel):
    slide_idx: int
    row_indexes: list[str] = Field(default_factory=list)
    segment_columns: list[str] = Field(default_factory=list)


class UploadedFileMeta(BaseModel):
    file_id: str
    filename: str = ""
    preprocessing_status: str = "pending"


class DirectUploadedDoc(BaseModel):
    filename: str
    markdown_content: str
    source: str = "cowork_direct_upload"


class WorkingDraft(BaseModel):
    table_data: list[list[str]] = Field(default_factory=list)
    column_headers: list[str] = Field(default_factory=list)
    evidence_summary: str = ""


class CoworkSessionState(BaseModel):
    session_id: str
    module_name: str
    current_state: WorkflowState = WorkflowState.INIT
    template_metadata: TemplateMetadata | None = None
    uploaded_files: list[UploadedFileMeta] = Field(default_factory=list)
    direct_uploaded_docs: list[DirectUploadedDoc] = Field(default_factory=list)
    working_draft: WorkingDraft = Field(default_factory=WorkingDraft)
    missing_info_summary: str = ""
    row_completion_status: dict[str, bool] = Field(default_factory=dict)
    web_search_enabled: bool = False
    history: list[ChatMessage] = Field(default_factory=list)
    last_error: str | None = None
    conversation_phase: ConversationPhase = ConversationPhase.CONTEXT_DISCOVERY
    segmentation_brief: SegmentationBrief = Field(default_factory=SegmentationBrief)


class CoworkWorkflowMetadata(BaseModel):
    session_id: str
    module_name: str
    state: WorkflowState
    missing_info_summary: str = ""
    suggested_action: str = ""
    detected_intent: str = "unknown"
    next_step_recommendation: str = ""
    ready_for_ppt_fill: bool = False
    confidence: float | None = None


class CoworkTurnRequest(BaseModel):
    session_id: str
    module: str
    slide_idx: int
    file_ids: list[str] = Field(default_factory=list)
    table_structure: dict[str, Any] = Field(default_factory=dict)
    user_message: str
    conversation_history: list[dict[str, str]] | None = None
    allow_web_search: bool = False
    action: str | None = None


class CoworkTurnResponse(BaseModel):
    assistant_message: str
    workflow: CoworkWorkflowMetadata
    draft_table_data: list[list[str]] = Field(default_factory=list)
    draft_column_headers: list[str] = Field(default_factory=list)
    ppt_fill_payload: dict[str, Any] | None = None


class CoworkUploadResponse(BaseModel):
    session_id: str
    uploaded_count: int
    total_docs_in_memory: int
    filenames: list[str] = Field(default_factory=list)

