"""Hybrid retrieval over BM25 + vector similarity + metadata boosts."""

from __future__ import annotations

from collections import defaultdict

from retriever.chunker import bm25_scores
from retriever.index_store import EmbeddingIndexStore
from retriever.models import ChunkRecord

_TOPIC_BOOST_TERMS = {
    "preferences",
    "channels",
    "environment",
    "demographics",
    "wechat",
    "weixin",
    "conference",
    "journal",
    "publication",
    "segment",
}


def _metadata_boost(chunk: ChunkRecord, query: str) -> float:
    lowered = (query or "").lower()
    score = 0.0
    if chunk.table_flag:
        score += 0.08
    if chunk.segment_hint:
        score += 0.08
    heading_text = " ".join(str(v) for v in chunk.metadata.get("heading_path", []))
    if heading_text and any(term in heading_text.lower() for term in _TOPIC_BOOST_TERMS):
        score += 0.06
    if any(term in lowered for term in chunk.segment_hint):
        score += 0.12
    return score


def hybrid_retrieve(
    chunks: list[ChunkRecord],
    query_list: list[str],
    *,
    max_candidates: int = 150,
    index_store: EmbeddingIndexStore | None = None,
) -> list[ChunkRecord]:
    """Return de-duplicated candidate chunks with high recall."""
    if not chunks:
        return []
    queries = [q.strip() for q in query_list if q and q.strip()]
    if not queries:
        return chunks[:max_candidates]

    index = index_store or EmbeddingIndexStore()
    index.upsert_chunks(chunks)

    by_chunk_id = {chunk.chunk_id: chunk for chunk in chunks}
    aggregate_scores: dict[str, float] = defaultdict(float)
    chunk_text = [c.text for c in chunks]
    chunk_ids = [c.chunk_id for c in chunks]

    for query in queries:
        bm25 = bm25_scores(chunk_text, query)
        vec = index.similarity_scores(query)
        for idx, cid in enumerate(chunk_ids):
            base = (bm25[idx] * 0.7) + (vec.get(cid, 0.0) * 0.3)
            base += _metadata_boost(by_chunk_id[cid], query)
            aggregate_scores[cid] = max(aggregate_scores[cid], base)

    ranked = sorted(aggregate_scores.items(), key=lambda kv: kv[1], reverse=True)
    selected_ids = [cid for cid, _ in ranked[:max_candidates]]
    return [by_chunk_id[cid] for cid in selected_ids if cid in by_chunk_id]
