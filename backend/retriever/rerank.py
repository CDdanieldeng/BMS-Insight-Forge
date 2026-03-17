"""
Rerank / filter module for retrieval output.

Deduplication, low-quality filtering, header-only and noise filtering,
score-based sorting. Output: list of {chunk_id, text, metadata, score}.
"""

from __future__ import annotations

from typing import Any


def dedupe_by_chunk_id(
    items: list[dict[str, Any]],
    key: str = "chunk_id",
) -> list[dict[str, Any]]:
    """Remove duplicates by chunk_id, keep first occurrence."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        cid = item.get(key)
        if cid and cid not in seen:
            seen.add(cid)
            out.append(item)
    return out


def filter_low_quality(
    items: list[dict[str, Any]],
    *,
    min_text_len: int = 30,
    exclude_noise: bool = True,
) -> list[dict[str, Any]]:
    """Drop chunks that are too short or marked as noise."""
    out: list[dict[str, Any]] = []
    for item in items:
        text = (item.get("text") or "").strip()
        if len(text) < min_text_len:
            continue
        if exclude_noise and item.get("metadata", {}).get("noise_flag"):
            continue
        out.append(item)
    return out


def sort_by_score(
    items: list[dict[str, Any]],
    score_key: str = "score",
    descending: bool = True,
) -> list[dict[str, Any]]:
    """Sort by score. Items without score_key are placed at end."""
    def _score(item: dict[str, Any]) -> float:
        s = item.get(score_key)
        if s is None:
            return float("-inf") if descending else float("inf")
        try:
            return float(s)
        except (TypeError, ValueError):
            return float("-inf") if descending else float("inf")

    return sorted(items, key=_score, reverse=descending)
