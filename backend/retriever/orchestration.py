"""
Retrieval orchestration: query rewrite → facet → chunk → embed → recall → rerank.

Single entrypoint that runs the full retriever pipeline and returns final chunks
with metadata (recalled_count, reranked_count) for observability.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from shared.logging_config import setup_logging

from generation.document_store import get_document_text, get_document_meta
from .chunking import chunk_text
from .embedding import embed
from .facet import DocumentFacet, classify_document_facet
from .query_rewrite import rewrite_for_retrieval
from .recall import CosineSimilarityRecaller, get_default_recaller
from .rerank import rerank

logger = setup_logging("retriever")

# Default top-k for recall and rerank
DEFAULT_RECALL_TOP_K = 20
DEFAULT_RERANK_TOP_K = 10


def _normalize_session_doc(doc: dict[str, Any], idx: int) -> dict[str, Any]:
    """Convert session upload doc to {file_id, text, filename}."""
    text = (doc.get("markdown_content") or doc.get("text") or "").strip()
    filename = str(doc.get("filename") or doc.get("file_id") or f"cowork_upload_{idx}")
    file_id = str(doc.get("file_id") or f"cowork_direct_{idx}")
    return {"file_id": file_id, "text": text, "filename": filename}


def _load_ingested_docs(file_ids: list[str]) -> list[dict[str, Any]]:
    """Load ingested docs from document_store by file_ids."""
    docs: list[dict[str, Any]] = []
    for fid in file_ids:
        text = get_document_text(fid)
        if text and text.strip():
            meta = get_document_meta(fid)
            filename = str(meta.get("filename") or fid)
            docs.append({"file_id": fid, "text": text.strip(), "filename": filename})
    return docs


def _merge_doc_sources(
    file_ids: list[str],
    session_upload_docs: list[dict[str, Any]] | None,
    correlation_key: str = "",
) -> list[dict[str, Any]]:
    """
    Merge session-upload docs and ingested docs into a unified list.
    Falls back to the other source when one is absent or empty.
    """
    ingested = _load_ingested_docs(file_ids) if file_ids else []
    session_docs = []
    if session_upload_docs:
        for i, d in enumerate(session_upload_docs):
            norm = _normalize_session_doc(d, i)
            if norm["text"]:
                session_docs.append(norm)

    merged = session_docs + ingested
    if not merged and ingested:
        merged = ingested
    if not merged and session_docs:
        merged = session_docs

    logger.info(
        "retrieval doc merge correlation_key=%s ingested=%d session_docs=%d merged=%d",
        correlation_key,
        len(ingested),
        len(session_docs),
        len(merged),
    )
    return merged


@dataclass
class IndexedRetrievalCorpus:
    """
    Cached outputs of facet → chunk → per-chunk embedding for a document set.

    Reuse for multiple queries (e.g. Customer Segmentation per-cell retrieval)
    to avoid repeated LLM facet calls and chunk embedding.
    """

    merged_docs: list[dict[str, Any]]
    all_chunks: list[dict[str, Any]]
    chunk_embeddings: list[list[float]]
    facet_results: list[dict[str, Any]]


def _ingest_merged_docs_to_chunks_and_embeddings(
    merged_docs: list[dict[str, Any]],
    correlation_key: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[list[float]]]:
    """
    Facet (LLM) + chunk + embed all chunks for merged docs.

    Returns:
        (all_chunks, facet_results, chunk_embeddings). Embeddings list is empty if no chunks.
    """
    all_chunks: list[dict[str, Any]] = []
    facet_results: list[dict[str, Any]] = []
    for doc in merged_docs:
        file_id = doc["file_id"]
        text = doc["text"]
        filename = doc.get("filename", file_id)
        if not text or len(text.strip()) < 10:
            continue
        facet_result = classify_document_facet(text, filename=filename)
        raw_facet = facet_result.get("file_type", "others") or "others"
        summary = facet_result.get("summary", "")
        topics = facet_result.get("topics") or []
        facet_results.append({
            "filename": filename,
            "file_type": raw_facet,
            "summary": summary,
            "topics": topics,
        })
        logger.info(
            "retrieval facet correlation_key=%s filename=%s file_type=%s summary=%s",
            correlation_key,
            filename,
            raw_facet,
            (summary[:80] + "…") if len(summary) > 80 else summary,
        )
        try:
            facet = DocumentFacet(raw_facet)
        except ValueError:
            facet = DocumentFacet.OTHERS
        chunks = chunk_text(text, facet)
        for c in chunks:
            c["file_id"] = file_id
            c["filename"] = filename
        all_chunks.extend(chunks)

    if not all_chunks:
        return [], facet_results, []

    chunk_texts = [c["text"] for c in all_chunks]
    embeddings = embed(chunk_texts)
    return all_chunks, facet_results, embeddings


def build_indexed_retrieval_corpus(
    file_ids: list[str],
    session_upload_docs: list[dict[str, Any]] | None = None,
    *,
    correlation_key: str = "",
) -> IndexedRetrievalCorpus:
    """
    Run document merge → facet → chunk → chunk embedding once.

    Safe to pass every ``run_retrieval_pipeline(..., indexed_corpus=corpus)`` for
    the same file_ids / session uploads.
    """
    merged_docs = _merge_doc_sources(file_ids, session_upload_docs, correlation_key)
    if not merged_docs:
        return IndexedRetrievalCorpus(
            merged_docs=[],
            all_chunks=[],
            chunk_embeddings=[],
            facet_results=[],
        )
    all_chunks, facet_results, chunk_embeddings = _ingest_merged_docs_to_chunks_and_embeddings(
        merged_docs, correlation_key
    )
    logger.info(
        "indexed corpus built correlation_key=%s doc_count=%d chunk_count=%d embed_count=%d",
        correlation_key,
        len(merged_docs),
        len(all_chunks),
        len(chunk_embeddings),
    )
    return IndexedRetrievalCorpus(
        merged_docs=merged_docs,
        all_chunks=all_chunks,
        chunk_embeddings=chunk_embeddings,
        facet_results=facet_results,
    )


def run_retrieval_pipeline(
    raw_query: str,
    file_ids: list[str],
    session_upload_docs: list[dict[str, Any]] | None = None,
    *,
    recall_top_k: int = DEFAULT_RECALL_TOP_K,
    rerank_top_k: int = DEFAULT_RERANK_TOP_K,
    correlation_key: str = "",
    indexed_corpus: IndexedRetrievalCorpus | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Run full retrieval pipeline: query rewrite → facet → chunk → embed → recall → rerank.

    Args:
        raw_query: Unrewritten retrieval input (e.g. cowork methodology summary) for query rewrite.
        file_ids: Ingested document file IDs.
        session_upload_docs: Optional session-upload docs (from cowork direct uploads).
        recall_top_k: Number of candidates from recall.
        rerank_top_k: Number of final chunks after rerank.
        correlation_key: Optional correlation key for logs.
        indexed_corpus: If set, skip merge/facet/chunk/chunk-embedding and use this
            pre-built index (e.g. shared across many per-cell queries).

    Returns:
        Tuple of (combined_chunk_text, metadata).
        metadata includes: recalled_count, reranked_count, chunk_count, query_len,
        query_preview, fallback_used.
    """
    metadata: dict[str, Any] = {
        "recalled_count": 0,
        "reranked_count": 0,
        "chunk_count": 0,
        "query_len": 0,
        "query_preview": "",
        "fallback_used": False,
        "facet_results": [],
    }

    summary = (raw_query or "").strip()
    if not summary:
        logger.warning(
            "run_retrieval_pipeline: empty raw_query correlation_key=%s",
            correlation_key,
        )
        return "", metadata

    # 1. Query rewrite
    start = time.perf_counter()
    query = rewrite_for_retrieval(summary)
    metadata["query_len"] = len(query)
    metadata["query_preview"] = (query[:120] + "…") if len(query) > 120 else query
    logger.info(
        "retrieval query_rewrite correlation_key=%s summary_len=%d query_len=%d preview=%s",
        correlation_key,
        len(summary),
        len(query),
        metadata["query_preview"],
    )

    # 2–4. Merge + facet + chunk + embed (or use pre-built corpus)
    if indexed_corpus is not None:
        merged_docs = indexed_corpus.merged_docs
        all_chunks = indexed_corpus.all_chunks
        embeddings = indexed_corpus.chunk_embeddings
        metadata["facet_results"] = list(indexed_corpus.facet_results)
        if not merged_docs:
            logger.warning(
                "run_retrieval_pipeline: indexed corpus has no documents correlation_key=%s",
                correlation_key,
            )
            return "", metadata
        logger.info(
            "retrieval using indexed_corpus correlation_key=%s doc_count=%d chunk_count=%d",
            correlation_key,
            len(merged_docs),
            len(all_chunks),
        )
    else:
        merged_docs = _merge_doc_sources(file_ids, session_upload_docs, correlation_key)
        if not merged_docs:
            logger.warning(
                "run_retrieval_pipeline: no documents to chunk correlation_key=%s",
                correlation_key,
            )
            return "", metadata
        all_chunks, facet_results, embeddings = _ingest_merged_docs_to_chunks_and_embeddings(
            merged_docs, correlation_key
        )
        metadata["facet_results"] = facet_results
        if not all_chunks:
            logger.warning(
                "run_retrieval_pipeline: no chunks produced correlation_key=%s",
                correlation_key,
            )
            return "", metadata
        logger.info(
            "retrieval chunking correlation_key=%s doc_count=%d chunk_count=%d",
            correlation_key,
            len(merged_docs),
            len(all_chunks),
        )

    # 5. Index and recall
    recaller = get_default_recaller()
    if hasattr(recaller, "clear"):
        recaller.clear()
    recaller.index(all_chunks, embeddings)
    query_vec = embed([query])[0]
    file_id_list = [d["file_id"] for d in merged_docs] if merged_docs else None
    recalled = recaller.recall(
        query_vec, file_ids=file_id_list, facet=None, top_k=recall_top_k
    )
    recalled_count = len(recalled)
    metadata["recalled_count"] = recalled_count
    metadata["recalled_chunks"] = recalled
    logger.info(
        "retrieval recall correlation_key=%s indexed_total=%d recalled_count=%d top_k=%d",
        correlation_key,
        len(all_chunks),
        recalled_count,
        recall_top_k,
    )

    if not recalled:
        return "", metadata

    # 6. Rerank
    reranked = rerank(query, recalled, top_k=rerank_top_k)
    reranked_count = len(reranked)
    metadata["reranked_count"] = reranked_count
    logger.info(
        "retrieval rerank correlation_key=%s input_candidates=%d reranked_count=%d top_k=%d",
        correlation_key,
        recalled_count,
        reranked_count,
        rerank_top_k,
    )

    # 7. Build final context
    blocks: list[str] = []
    for i, ch in enumerate(reranked, start=1):
        fn = ch.get("filename", ch.get("file_id", ""))
        blocks.append(f"## Document {i}: {fn}\n\n{ch.get('text', '').strip()}")
    combined = "\n\n---\n\n".join(blocks)
    metadata["chunk_count"] = reranked_count

    logger.info(
        "retrieval pipeline complete correlation_key=%s recalled=%d reranked=%d context_chars=%d elapsed_ms=%d",
        correlation_key,
        recalled_count,
        reranked_count,
        len(combined),
        int((time.perf_counter() - start) * 1000),
    )
    return combined, metadata
