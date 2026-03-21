"""Shared string normalization for modules, slides, and generation."""

import re


def normalize_label(label: str) -> str:
    """Normalize row/module label for comparison (lowercase, collapsed whitespace)."""
    return " ".join((label or "").strip().lower().split())


# Matches placeholder column names like "Segment 1", "segment 3", "SEGMENT 4"
SEGMENT_PLACEHOLDER_RE = re.compile(r"^segment\s+\d+$", re.IGNORECASE)


def has_placeholder_columns(columns: list[str]) -> bool:
    """
    Return True if ALL non-empty column headers are generic placeholders
    like 'Segment 1', 'Segment 2', etc. — meaning they need to be replaced
    with real names extracted from the uploaded documents.
    """
    data_cols = [c.strip() for c in columns if c.strip()]
    return bool(data_cols) and all(SEGMENT_PLACEHOLDER_RE.match(c) for c in data_cols)
