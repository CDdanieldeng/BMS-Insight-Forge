"""
Rerank: score and reorder recall candidates for relevance.
"""

from __future__ import annotations

from typing import Any


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """
    Rerank candidate chunks by relevance to the query.

    Uses a cross-encoder or LLM-based reranker for better precision.

    Args:
        query: User query or search intent.
        candidates: Chunks from recall step (each has "text" and optional metadata).
        top_k: Number of top results to return after reranking.

    Returns:
        Reordered subset of candidates with added "rerank_score" if applicable.
    """
    # TODO: Implement with cross-encoder (e.g. BAAI/bge-reranker) or LLM
    return candidates[:top_k]
