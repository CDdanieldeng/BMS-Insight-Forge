"""Strict evidence judge on compressed snippets."""

from __future__ import annotations

import re
from typing import Any


def _field_type_from_row(row_definition: str) -> str:
    lowered = (row_definition or "").lower()
    if "demographic" in lowered or "age" in lowered or "gender" in lowered:
        return "demographics"
    if "preference" in lowered or "channel" in lowered or "interaction" in lowered:
        return "preferences"
    if "environment" in lowered or "volume" in lowered or "ecosystem" in lowered:
        return "environment"
    return "generic"


def _segment_match(text: str, segment_terms: list[str]) -> bool:
    if not segment_terms:
        return True
    lowered = (text or "").lower()
    return any(term.lower() in lowered for term in segment_terms)


def judge_snippet(
    snippet: dict[str, Any],
    *,
    row_definition: str,
    segment_terms: list[str],
) -> tuple[bool, str]:
    """Return (accepted, reason)."""
    text = str(snippet.get("text", "")).strip()
    lowered = text.lower()
    field_type = _field_type_from_row(row_definition)

    if not text:
        return False, "empty_snippet"
    if not _segment_match(text, segment_terms):
        return False, "segment_not_explicit"

    if field_type == "demographics":
        if not re.search(r"\b(age|aged|male|female|gender)\b", lowered):
            return False, "demographics_not_explicit"
    elif field_type == "preferences":
        if not re.search(r"\b(prefer|preference|channel|wechat|weixin|conference|journal|rep)\b", lowered):
            return False, "preference_not_explicit"
    elif field_type == "environment":
        if not re.search(r"\b(environment|market|volume|patients?|ecosystem|setting|hospital)\b", lowered):
            return False, "environment_not_explicit"
        if re.search(r"\d", lowered) and not re.search(r"\b(%|per month|monthly|patients?|times?|yearly)\b", lowered):
            return False, "number_without_unit"

    return True, "accepted"
