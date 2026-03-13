"""Simplified models for SWOT cowork module."""

from __future__ import annotations

from pydantic import BaseModel, Field

from cowork_agent.models import ChatMessage, DirectUploadedDoc


class SwotCoworkSessionState(BaseModel):
    """Minimal session state for SWOT cowork — no workflow phases or drafting."""
    session_id: str
    module_name: str = "SWOT Analysis"
    history: list[ChatMessage] = Field(default_factory=list)
    direct_uploaded_docs: list[DirectUploadedDoc] = Field(default_factory=list)
