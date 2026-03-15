"""
Context retrieval abstraction: BM25 retriever or full markdown based on USE_RETRIEVER.

Provides get_context_content as the public API for document context.
"""

import os
import time
from typing import Any

from shared.logging_config import setup_logging

from retriever.evidence_pipeline import run_evidence_pipeline
from retriever.pipeline_config import load_pipeline_config

logger = setup_logging("generation")


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean-like environment variable with a safe default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def use_retriever() -> bool:
    """Whether to use BM25 retriever before LLM prompting."""
    return _env_flag("USE_RETRIEVER", default=True)


def _retriever_search(
    file_ids: list[str],
    query: str,
    module: str = "",
    table_structure: dict[str, Any] | None = None,
    top_k: int = 50,
) -> str:
    """Run evidence pipeline and return combined context text."""
    from retriever.router import _chunk_store

    start = time.perf_counter()
    all_chunks = []
    found = 0
    for fid in file_ids:
        if fid in _chunk_store:
            all_chunks.extend(_chunk_store[fid])
            found += 1
    config = load_pipeline_config()
    pipeline_result = run_evidence_pipeline(
        file_ids=file_ids,
        module=module,
        table_structure=table_structure or {},
        seed_query=query,
        config=config,
        top_k_fallback=top_k,
    )
    combined = pipeline_result.context_text
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "Retriever search done file_ids=%d found=%d total_chunks=%d query_len=%d content_len=%d degraded=%s metrics=%s elapsed_ms=%d",
        len(file_ids),
        found,
        len(all_chunks),
        len(query or ""),
        len(combined),
        pipeline_result.degraded,
        pipeline_result.metrics,
        elapsed_ms,
    )
    return combined


def _full_markdown_context(file_ids: list[str]) -> str:
    """Return full cleaned markdown for all file_ids in original upload order."""
    from retriever.router import _store

    start = time.perf_counter()
    texts: list[str] = []
    found = 0
    for fid in file_ids:
        text = _store.get(fid)
        if text:
            texts.append(text.strip())
            found += 1

    combined = "\n\n---\n\n".join(t for t in texts if t)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "Full markdown context done file_ids=%d found=%d content_len=%d elapsed_ms=%d",
        len(file_ids),
        found,
        len(combined),
        elapsed_ms,
    )
    return combined


def get_context_content(
    file_ids: list[str],
    query: str,
    top_k: int = 50,
    module: str = "",
    table_structure: dict[str, Any] | None = None,
) -> str:
    """
    Select context source based on USE_RETRIEVER toggle.

    USE_RETRIEVER=true  -> BM25 top-k chunks (current default flow)
    USE_RETRIEVER=false -> full cleaned markdown content

    This is the public API for document context. Use this instead of
    internal orchestrator functions.
    """
    if use_retriever():
        return _retriever_search(
            file_ids,
            query,
            module=module,
            table_structure=table_structure,
            top_k=top_k,
        )
    return _full_markdown_context(file_ids)


def get_full_markdown_context(file_ids: list[str]) -> str:
    """
    Return full cleaned markdown for all file_ids in original upload order.
    Used for segment name extraction where we need complete documents, not retrieved chunks.
    """
    return _full_markdown_context(file_ids)
