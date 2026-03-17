"""Segment and slide table caches for generation pipeline context composition."""

import re
from typing import Any

# Module-level cache: module_name -> (segment_names, slide_idx).
# Populated on the first CS slide that triggers extraction; reused only on
# subsequent slides (slide_idx > cached_slide_idx) of the same module.
# This avoids reusing stale cache when user refreshes and re-runs slide 1.
_segment_name_cache: dict[str, tuple[list[str], int]] = {}

# Module-level cache: slide_idx -> generated table metadata.
# Used to provide prior slide table outputs as context for downstream slides.
_slide_table_cache: dict[int, dict[str, Any]] = {}


def _normalize_label(label: str) -> str:
    return " ".join((label or "").strip().lower().split())


def get_segment_names(module: str, current_slide_idx: int) -> list[str] | None:
    """
    Return cached segment names for module, or None if not cached or invalid.

    Cache is valid only when current_slide_idx > cached_slide_idx (i.e. we are
    on a later slide than the one that produced the cache). This ensures:
    - Slide 2+ can reuse segments from slide 1.
    - Refreshing and re-running slide 1 does NOT reuse stale cache.
    """
    entry = _segment_name_cache.get(module)
    if entry is None:
        return None
    names, cached_slide_idx = entry
    if current_slide_idx <= cached_slide_idx:
        return None
    return names


def set_segment_names(module: str, names: list[str], slide_idx: int) -> None:
    """Cache segment names for module, produced by the given slide_idx."""
    _segment_name_cache[module] = (names, slide_idx)


def clear_segment_names() -> None:
    """Clear all cached segment names."""
    _segment_name_cache.clear()


def get_slide_table(slide_idx: int) -> dict[str, Any] | None:
    """Return cached table metadata for slide_idx, or None."""
    return _slide_table_cache.get(slide_idx)


def set_slide_table(slide_idx: int, metadata: dict[str, Any]) -> None:
    """Cache table metadata for slide_idx."""
    _slide_table_cache[slide_idx] = metadata


def clear_slide_tables() -> None:
    """Clear all cached slide tables."""
    _slide_table_cache.clear()


def _format_cached_table_context(cached: dict[str, Any]) -> str:
    slide_idx = int(cached.get("slide_idx", -1))
    module = str(cached.get("module", ""))
    headers = [str(h) for h in (cached.get("column_headers") or [])]
    indexes = [str(i) for i in (cached.get("indexes") or [])]
    table_data = cached.get("table_data") or []

    lines: list[str] = [
        f"Slide {slide_idx} ({module})",
        f"Columns: {headers}",
    ]
    for row_idx, row_label in enumerate(indexes):
        row_values = table_data[row_idx] if row_idx < len(table_data) else []
        lines.append(f"- {row_label}: {row_values}")
    return "\n".join(lines)


def build_prior_table_primary_context(current_slide_idx: int) -> str:
    """Return formatted context from the two latest slides before current slide."""
    prior_slides = sorted(idx for idx in _slide_table_cache if idx < current_slide_idx)[-2:]
    if not prior_slides:
        return ""
    return "\n\n".join(_format_cached_table_context(_slide_table_cache[idx]) for idx in prior_slides)


def _is_high_priority(value: str) -> bool:
    return bool(re.match(r"^\s*high\b", (value or "").strip(), flags=re.IGNORECASE))


def extract_prioritized_segments_from_customer_segmentation(
    current_slide_idx: int,
) -> list[str]:
    """
    Extract prioritized segment names from the latest prior customer segmentation
    slide that contains a 'Segment Prioritization' row.
    """
    candidate_slides = sorted(idx for idx in _slide_table_cache if idx < current_slide_idx)
    for idx in reversed(candidate_slides):
        cached = _slide_table_cache[idx]
        if _normalize_label(str(cached.get("module", ""))) != "customer segmentation":
            continue

        headers = [str(h).strip() for h in (cached.get("column_headers") or []) if str(h).strip()]
        row_labels = [str(r).strip() for r in (cached.get("indexes") or [])]
        table_data = cached.get("table_data") or []
        normalized_rows = [_normalize_label(r) for r in row_labels]
        if "segment prioritization" not in normalized_rows:
            continue

        row_idx = normalized_rows.index("segment prioritization")
        if row_idx >= len(table_data):
            continue
        row_values = table_data[row_idx] or []

        prioritized: list[str] = []
        for col_idx, cell in enumerate(row_values):
            if not _is_high_priority(str(cell)):
                continue
            if col_idx < len(headers):
                prioritized.append(headers[col_idx])

        if prioritized:
            return prioritized
    return []
