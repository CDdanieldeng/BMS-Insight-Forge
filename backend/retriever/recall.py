"""
Recall: retrieve candidate chunks from vector store by similarity.

Structured around a BaseRecaller ABC for easy extension; currently implements
CosineSimilarityRecaller for in-memory retrieval.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        raise ValueError("Vectors must have same dimension")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class BaseRecaller(ABC):
    """
    Abstract base for recall strategies. Subclass to add new backends
    (e.g. Qdrant, Pinecone, pgvector, Chroma).
    """

    @abstractmethod
    def recall(
        self,
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
        ...


class CosineSimilarityRecaller(BaseRecaller):
    """
    In-memory recaller using cosine similarity. Index chunks with embeddings,
    then retrieve top-k by similarity.
    """

    def __init__(self) -> None:
        self._chunks: list[dict[str, Any]] = []
        self._embeddings: list[list[float]] = []

    def index(self, chunks: list[dict[str, Any]], embeddings: list[list[float]]) -> None:
        """
        Index chunks with their embeddings for later retrieval.

        Args:
            chunks: List of chunk dicts (each with "text", optionally "file_id", "facet", etc.).
            embeddings: List of embedding vectors, one per chunk.
        """
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have same length")
        self._chunks.extend(chunks)
        self._embeddings.extend(embeddings)

    def clear(self) -> None:
        """Clear all indexed chunks."""
        self._chunks.clear()
        self._embeddings.clear()

    def recall(
        self,
        query_embedding: list[float],
        file_ids: list[str] | None = None,
        facet: str | None = None,
        top_k: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Retrieve top-k chunks by cosine similarity.
        """
        scored: list[tuple[float, dict[str, Any]]] = []
        for ch, emb in zip(self._chunks, self._embeddings):
            if file_ids is not None and ch.get("file_id") not in file_ids:
                continue
            if facet is not None and ch.get("facet") != facet:
                continue
            score = _cosine_similarity(query_embedding, emb)
            scored.append((score, {**ch, "score": score}))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ch for _, ch in scored[:top_k]]


def get_default_recaller() -> BaseRecaller:
    """Return the default recaller instance (CosineSimilarityRecaller)."""
    return CosineSimilarityRecaller()


_default_recaller = get_default_recaller()


def recall(
    query_embedding: list[float],
    file_ids: list[str] | None = None,
    facet: str | None = None,
    top_k: int = 50,
) -> list[dict[str, Any]]:
    """
    Retrieve top-k candidate chunks by embedding similarity.

    Uses the default recaller. For in-memory CosineSimilarityRecaller,
    index chunks first via get_default_recaller().index(...).
    """
    return _default_recaller.recall(
        query_embedding=query_embedding,
        file_ids=file_ids,
        facet=facet,
        top_k=top_k,
    )


def recall_by_query_text(
    query: str,
    file_ids: list[str] | None = None,
    facet: str | None = None,
    top_k: int = 50,
) -> list[dict[str, Any]]:
    """
    Convenience: embed query and run recall in one call.
    """
    from .embedding import embed

    vec = embed([query])[0]
    return recall(query_embedding=vec, file_ids=file_ids, facet=facet, top_k=top_k)


if __name__ == "__main__":
    # cd backend && python -m retriever.recall
    # Use synthetic embeddings so the test runs without network or sentence-transformers.
    # For integration test with real embeddings, run pytest tests/test_retriever_pipeline.py
    try:
        from .embedding import embed

        chunks = [
            {"text": "Battery management systems for electric vehicles", "file_id": "f1", "facet": "technical"},
            {"text": "Weather forecast for tomorrow", "file_id": "f2", "facet": "news"},
            {"text": "EV battery charging and thermal control", "file_id": "f1", "facet": "technical"},
        ]
        embeddings = embed([c["text"] for c in chunks])
        query_vec = embed(["electric vehicle battery management"])[0]
    except Exception:
        # Fallback: synthetic vectors. [1,0,0] and [0.9,0.1,0] are similar; [0,1,0] is not.
        chunks = [
            {"text": "chunk A (battery)", "file_id": "f1", "facet": "technical"},
            {"text": "chunk B (weather)", "file_id": "f2", "facet": "news"},
            {"text": "chunk C (EV battery)", "file_id": "f1", "facet": "technical"},
        ]
        embeddings = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.9, 0.1, 0.0]]
        query_vec = [1.0, 0.0, 0.0]

    recaller = CosineSimilarityRecaller()
    recaller.index(chunks, embeddings)

    results = recaller.recall(query_vec, top_k=2)
    assert len(results) == 2
    assert all("score" in r for r in results)
    assert results[0]["score"] >= results[1]["score"]
    # With real embeddings: battery-related; with synthetic: chunk A or C (both similar to query)
    assert results[0]["score"] > 0.5

    results_f1 = recaller.recall(query_vec, file_ids=["f1"], top_k=5)
    assert all(r.get("file_id") == "f1" for r in results_f1)

    print("recall test passed")
