"""
Recall: retrieve candidate chunks from vector store by similarity.
"""

from __future__ import annotations

from typing import Any


def recall(
    query_embedding: list[float],
    file_ids: list[str] | None = None,
    facet: str | None = None,
    top_k: int = 50,
) -> list[dict[str, Any]]:
    """
    Retrieve top-k candidate chunks by embedding similarity.

    Args:
        query_embedding: Query vector from embed().
        file_ids: Optional filter to specific file IDs.
        facet: Optional document facet filter.
        top_k: Number of candidates to return.

    Returns:
        List of chunk dicts with keys like "text", "file_id", "score", "metadata".
    """
    # TODO: Implement vector search (e.g. Qdrant, Pinecone, pgvector, Chroma)
    return []


def recall_by_query_text(
    query: str,
    file_ids: list[str] | None = None,
    facet: str | None = None,
    top_k: int = 50,
) -> list[dict[str, Any]]:
    """
    Convenience: embed query and run recall in one call.

    Args:
        query: Natural language query.
        file_ids: Optional file filter.
        facet: Optional facet filter.
        top_k: Number of candidates.

    Returns:
        List of retrieved chunk dicts.
    """
    from .embedding import embed

    vec = embed([query])[0]
    return recall(query_embedding=vec, file_ids=file_ids, facet=facet, top_k=top_k)
