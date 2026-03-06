"""In-memory vector-ish index store for hybrid retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter

from retriever.models import ChunkRecord

_TOKEN_RE = re.compile(r"\b[a-zA-Z0-9]+\b")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _vectorize(text: str) -> Counter[str]:
    return Counter(_tokenize(text))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    if dot <= 0:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingIndexStore:
    """Small in-memory index keyed by chunk_id."""

    def __init__(self) -> None:
        self._vectors: dict[str, Counter[str]] = {}
        self._chunks: dict[str, ChunkRecord] = {}

    def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = _vectorize(chunk.text)

    def remove_doc(self, doc_id: str) -> None:
        target = [cid for cid, c in self._chunks.items() if c.doc_id == doc_id]
        for cid in target:
            self._chunks.pop(cid, None)
            self._vectors.pop(cid, None)

    def similarity_scores(self, query: str) -> dict[str, float]:
        q_vec = _vectorize(query)
        if not q_vec:
            return {}
        return {cid: _cosine(vec, q_vec) for cid, vec in self._vectors.items()}
