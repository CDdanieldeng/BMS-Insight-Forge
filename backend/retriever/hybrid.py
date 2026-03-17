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


def _apply_per_doc_cap(
    ranked: list[tuple[str, float]],
    by_chunk_id: dict[str, ChunkRecord],
    max_candidates: int,
    min_per_doc: int = 3,
) -> list[ChunkRecord]:
    """
    Select chunks ensuring diversity across documents.
    Prevents one file from dominating when multiple files are uploaded.
    """
    if not ranked or not by_chunk_id:
        return []
    doc_counts: dict[str, int] = {}
    unique_docs = len({by_chunk_id[cid].doc_id for cid, _ in ranked if cid in by_chunk_id})
    max_per_doc = max(min_per_doc, max(25, max_candidates // max(1, unique_docs)))

    selected: list[ChunkRecord] = []
    for cid, _ in ranked:
        if len(selected) >= max_candidates:
            break
        chunk = by_chunk_id.get(cid)
        if not chunk:
            continue
        doc_id = chunk.doc_id
        count = doc_counts.get(doc_id, 0)
        if count >= max_per_doc:
            continue
        doc_counts[doc_id] = count + 1
        selected.append(chunk)
    return selected


def hybrid_retrieve(
    chunks: list[ChunkRecord],
    query_list: list[str],
    *,
    max_candidates: int = 150,
    index_store: EmbeddingIndexStore | None = None,
) -> list[ChunkRecord]:
    """Return de-duplicated candidate chunks with high recall and per-doc diversity."""
    if not chunks:
        return []
    queries = [q.strip() for q in query_list if q and q.strip()]
    if not queries:
        # When no queries, still ensure per-doc diversity: interleave by doc_id
        # instead of returning first N (which could all come from one file)
        by_doc: dict[str, list[ChunkRecord]] = {}
        for c in chunks:
            by_doc.setdefault(c.doc_id, []).append(c)
        doc_ids = list(by_doc.keys())
        if len(doc_ids) <= 1:
            return chunks[:max_candidates]
        round_robin: list[ChunkRecord] = []
        idx = 0
        while len(round_robin) < max_candidates:
            added = 0
            for did in doc_ids:
                if idx < len(by_doc[did]):
                    round_robin.append(by_doc[did][idx])
                    added += 1
                if len(round_robin) >= max_candidates:
                    break
            if added == 0:
                break
            idx += 1
        return round_robin[:max_candidates]

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
    return _apply_per_doc_cap(ranked, by_chunk_id, max_candidates)
