"""LLM invocation layer for the consultant-style CS cowork agent."""

from __future__ import annotations

import json
import re
from typing import Any

from cowork_agent.prompt_builder import build_prompts, build_summary_prompt
from cowork_agent.models import CoworkSessionState
from generation.llm_client import complete


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1)
    data = json.loads(text)
    if isinstance(data, dict):
        return data
    raise ValueError("LLM response must be a JSON object")


_FALLBACK_RESPONSE: dict[str, Any] = {
    "response_text": (
        "To make the segmentation commercially useful, let's first align on what decision it needs "
        "to support this year. Could you share a bit about the therapeutic area and the main commercial "
        "priority — for example, defending an existing franchise, launching into a competitive space, "
        "or shifting prescribing behavior in a specific HCP segment?"
    ),
    "brief_update": None,
    "phase_assessment": "context_discovery",
    "detected_intent": "fallback",
    "missing_info_summary": "Business objective and segmentation lens not yet established.",
    "suggested_action": "clarify_commercial_objective",
    "confidence": 0.1,
}


def generate_conversational_turn(
    *,
    session: CoworkSessionState,
    user_message: str,
    evidence_text: str,
    missing_info_summary: str = "",
    ready_for_ppt_fill: bool = False,
    segments_identified: bool = False,
) -> dict[str, Any]:
    system, user = build_prompts(
        session=session,
        user_message=user_message,
        evidence_text=evidence_text,
        missing_info_summary=missing_info_summary,
        ready_for_ppt_fill=ready_for_ppt_fill,
        segments_identified=segments_identified,
    )
    raw = complete(system, user, max_tokens=1400)
    try:
        return _extract_json(raw)
    except Exception:
        return _FALLBACK_RESPONSE.copy()


def generate_conversation_summary(session: CoworkSessionState) -> str:
    """Generate an executive summary of the cowork conversation for Customer Segmentation."""
    system, user = build_summary_prompt(session)
    raw = complete(system, user, max_tokens=1200)
    text = (raw or "").strip()
    if not text:
        return (
            "Summary not available. The conversation covered Customer Segmentation planning; "
            "review the chat history above for details."
        )
    return text
