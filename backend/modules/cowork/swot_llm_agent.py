"""LLM layer for SWOT cowork agent — simple conversational turns."""

from __future__ import annotations

from modules.cowork.models import ChatMessage
from modules.cowork.swot_prompt_builder import build_swot_prompts, build_swot_summary_prompt
from shared.llm_client import complete


def generate_swot_turn(
    *,
    history: list[ChatMessage],
    user_message: str,
    cs_summary: str | None = None,
    cs_table_text: str | None = None,
    uploaded_docs_text: str | None = None,
) -> str:
    """Generate a single conversational response for SWOT cowork."""
    system, user = build_swot_prompts(
        history=history,
        user_message=user_message,
        cs_summary=cs_summary,
        cs_table_text=cs_table_text,
        uploaded_docs_text=uploaded_docs_text,
    )
    raw = complete(system, user, max_tokens=600)
    text = (raw or "").strip()
    if not text:
        return (
            "I'm here to align with you on what to emphasise in the SWOT analysis. "
            "Share any priorities or focus areas, or upload your market definition and "
            "competitor analysis files so we can work from that context."
        )
    return text


def generate_swot_summary(history: list[ChatMessage]) -> str:
    """Generate end-of-conversation summary for SWOT cowork."""
    system, user = build_swot_summary_prompt(history=history)
    raw = complete(system, user, max_tokens=500)
    text = (raw or "").strip()
    if not text:
        return (
            "Summary not available. The conversation covered SWOT analysis emphasis and "
            "priorities; review the chat history above for details."
        )
    return text
