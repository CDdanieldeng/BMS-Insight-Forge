"""Shared parser normalization and lightweight heuristics."""

from __future__ import annotations

import re
from typing import Iterable

_SEGMENT_TERMS = {
    "pioneer",
    "safe player",
    "traditionalist",
    "considerate performer",
    "segment",
}

_NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*confidential\b", flags=re.IGNORECASE),
    re.compile(r"^\s*page\s+\d+(\s*/\s*\d+)?\s*$", flags=re.IGNORECASE),
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),
    re.compile(r"^\s*table of contents\s*$", flags=re.IGNORECASE),
    re.compile(r"^\s*contents\s*$", flags=re.IGNORECASE),
]


def estimate_tokens(text: str) -> int:
    """Cheap token estimate suitable for chunk policy thresholds."""
    if not text:
        return 0
    return max(1, int(len(text.split()) * 1.3))


def normalize_whitespace(text: str) -> str:
    """Normalize line endings and trim noisy blank lines."""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def dedupe_lines(text: str) -> str:
    """Drop immediate duplicated lines (common in converted docs)."""
    lines = []
    prev = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            prev = ""
            continue
        if line == prev:
            continue
        lines.append(line)
        prev = line
    return "\n".join(lines).strip()


def is_noise_line(line: str) -> bool:
    """Detect obvious boilerplate/footer lines without LLM usage."""
    candidate = (line or "").strip()
    if not candidate:
        return False
    for pattern in _NOISE_LINE_PATTERNS:
        if pattern.search(candidate):
            return True
    if len(candidate) <= 3 and candidate.isdigit():
        return True
    if "all rights reserved" in candidate.lower():
        return True
    return False


def p0_clean_lines(lines: Iterable[str]) -> list[str]:
    """Apply low-cost line-level cleanup and dedupe."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for line in lines:
        c = (line or "").strip()
        if not c or is_noise_line(c):
            continue
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(c)
    return cleaned


def segment_hints_from_text(text: str) -> list[str]:
    """Extract segment markers from chunk text."""
    lowered = (text or "").lower()
    hints = [term for term in _SEGMENT_TERMS if term in lowered]
    return sorted(set(hints))


def keep_short_chunk(text: str, table_flag: bool) -> bool:
    """Whether a short chunk should still be kept."""
    if table_flag:
        return True
    lowered = (text or "").lower()
    if segment_hints_from_text(text):
        return True
    if re.search(r"\d", lowered):
        return True
    if re.search(r"\b(wechat|weixin|conference|congress|journal|publication|rep)\b", lowered):
        return True
    return False
