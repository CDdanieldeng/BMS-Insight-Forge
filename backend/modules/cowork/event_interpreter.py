"""Interpret user inputs into workflow-friendly events."""

from __future__ import annotations

from modules.cowork.models import EventType


def interpret_event(
    *,
    user_message: str,
    has_files: bool,
    allow_web_search: bool,
    action: str | None,
) -> EventType:
    msg = (user_message or "").strip().lower()
    act = (action or "").strip().lower()
    if act == "confirm_ppt_fill":
        return EventType.CONFIRM_PPT_FILL
    if act == "end_conversation":
        return EventType.END_CONVERSATION
    if has_files:
        return EventType.FILES_ATTACHED
    if allow_web_search:
        return EventType.WEB_PERMISSION_GRANTED
    if msg:
        return EventType.USER_MESSAGE
    return EventType.UNKNOWN
