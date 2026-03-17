"""
Vector store using sentence-transformers for semantic similarity.

Implements EmbeddingIndexStore-like interface (upsert_chunks, similarity_scores)
for drop-in replacement in hybrid retrieval. BM25 weight ~70%, vector ~30%.
"""

from __future__ import annotations

import math
from typing import Any

from retriever.models import ChunkRecord


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0-1 (clamped)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    sim = dot / (norm_a * norm_b)
    # Clamp to [0, 1] for consistency with TF-IDF scores
    return max(0.0, min(1.0, (sim + 1.0) / 2.0))


class SentenceTransformerStore:
    """
    In-memory vector store using HuggingFace sentence-transformers.
    Compatible with EmbeddingIndexStore interface for hybrid_retrieve.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "cpu",
    ) -> None:
        from langchain_community.embeddings import HuggingFaceEmbeddings

        self._embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device},
        )
        self._vectors: dict[str, list[float]] = {}
        self._chunks: dict[str, ChunkRecord] = {}

    def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        """Embed and store chunks. Skips re-embedding for chunk_ids already in store."""
        if not chunks:
            return
        new_chunks = [c for c in chunks if c.chunk_id not in self._vectors]
        if not new_chunks:
            return
        texts = [c.text for c in new_chunks]
        vectors = self._embeddings.embed_documents(texts)
        for chunk, vec in zip(new_chunks, vectors):
            self._vectors[chunk.chunk_id] = vec
            self._chunks[chunk.chunk_id] = chunk

    def remove_doc(self, doc_id: str) -> None:
        """Remove all chunks belonging to doc_id."""
        to_remove = [cid for cid, c in self._chunks.items() if c.doc_id == doc_id]
        for cid in to_remove:
            self._vectors.pop(cid, None)
            self._chunks.pop(cid, None)

    def similarity_scores(self, query: str) -> dict[str, float]:
        """
        Return similarity score per chunk_id. Compatible with hybrid_retrieve.
        """
        if not self._vectors:
            return {}
        q_vec = self._embeddings.embed_query(query or " ")
        return {
            cid: _cosine_sim(vec, q_vec)
            for cid, vec in self._vectors.items()
        }
