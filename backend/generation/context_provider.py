"""
Context retrieval: full markdown from document store.

Provides get_context_content, get_full_markdown_context, and get_retrieval_context
as the public API. When raw_query is provided, get_retrieval_context runs
the retriever pipeline (query rewrite → facet → chunk → embed → recall → rerank);
otherwise falls back to full markdown.
"""

import time
from typing import Any

from shared.logging_config import setup_logging

from generation.document_store import get_full_markdown_context as _get_full_markdown

logger = setup_logging("generation")


def get_retrieval_context(
    file_ids: list[str],
    raw_query: str,
    session_upload_docs: list[dict[str, Any]] | None = None,
    *,
    correlation_key: str = "",
) -> tuple[str, dict[str, Any]]:
    """
    Run retriever pipeline when raw_query is present.

    Uses query rewrite → facet → chunk → embed → recall → rerank. Falls back
    to full markdown when retrieval returns no chunks or fails.

    Returns:
        Tuple of (content, metadata). metadata has recalled_count, reranked_count,
        fallback_used.
    """
    from generation.stage_metrics import record_stage_metadata, stage_scope
    from retriever.orchestration import run_retrieval_pipeline

    metadata: dict[str, Any] = {
        "recalled_count": 0,
        "reranked_count": 0,
        "fallback_used": False,
    }
    start = time.perf_counter()

    try:
        with stage_scope("context_retrieval"):
            content, pipe_meta = run_retrieval_pipeline(
                raw_query=raw_query,
                file_ids=file_ids,
                session_upload_docs=session_upload_docs,
                correlation_key=correlation_key,
            )
        metadata["recalled_count"] = pipe_meta.get("recalled_count", 0)
        metadata["reranked_count"] = pipe_meta.get("reranked_count", 0)
        record_stage_metadata(
            recalled_count=metadata["recalled_count"],
            reranked_count=metadata["reranked_count"],
        )

        if content and content.strip():
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "Retrieval context done file_ids=%d recalled=%d reranked=%d content_len=%d elapsed_ms=%d",
                len(file_ids),
                metadata["recalled_count"],
                metadata["reranked_count"],
                len(content),
                elapsed_ms,
            )
            return content, metadata

        metadata["fallback_used"] = True
        fallback = _get_full_markdown(file_ids)
        logger.info(
            "Retrieval context fallback: no chunks, using full markdown file_ids=%d content_len=%d",
            len(file_ids),
            len(fallback),
        )
        return fallback, metadata
    except Exception as e:
        logger.exception(
            "Retrieval pipeline failed, falling back to full markdown correlation_key=%s err=%s",
            correlation_key,
            e,
        )
        metadata["fallback_used"] = True
        return _get_full_markdown(file_ids), metadata


def get_context_content(
    file_ids: list[str],
    query: str = "",
    top_k: int = 50,
    module: str = "",
    table_structure: dict[str, Any] | None = None,
) -> str:
    """
    Return full cleaned markdown for all file_ids in original upload order.
    This is the public API for document context.
    """
    start = time.perf_counter()
    combined = _get_full_markdown(file_ids)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "Context content done file_ids=%d content_len=%d elapsed_ms=%d",
        len(file_ids),
        len(combined),
        elapsed_ms,
    )
    return combined


def get_full_markdown_context(file_ids: list[str]) -> str:
    """
    Return full cleaned markdown for all file_ids in original upload order.
    Used for segment name extraction where we need complete documents.
    """
    return _get_full_markdown(file_ids)
