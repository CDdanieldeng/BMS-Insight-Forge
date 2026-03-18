"""Multilingual embedding and similarity search. Lazy-load model."""

from __future__ import annotations

import math

_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_model = None


def _get_model():
    """Lazy load model on first use."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of text strings. Returns list of 384-dim vectors."""
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    return vectors.tolist()


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity (vectors assumed normalized)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, dot))


def similarity_search(
    query: str,
    chunks: list[str],
    top_k: int,
) -> list[tuple[str, float]]:
    """
    Embed query and chunks, compute cosine similarity, return top_k (text, score).
    """
    if not chunks or not query or not query.strip():
        return []
    model = _get_model()
    query_vec = model.encode(query.strip(), normalize_embeddings=True)
    chunk_vecs = model.encode(chunks, normalize_embeddings=True)
    scored: list[tuple[str, float]] = []
    for i, chunk in enumerate(chunks):
        vec = chunk_vecs[i] if hasattr(chunk_vecs[i], "__iter__") else chunk_vecs[i].tolist()
        if hasattr(vec, "tolist"):
            vec = vec.tolist()
        score = _cosine_sim(query_vec.tolist(), vec)
        scored.append((chunk, float(score)))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]
