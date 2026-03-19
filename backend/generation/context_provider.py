"""
Context retrieval: full markdown from document store.

Provides get_context_content and get_full_markdown_context as the public API.
"""

import time
from typing import Any

from shared.logging_config import setup_logging

from generation.document_store import get_full_markdown_context as _get_full_markdown

logger = setup_logging("generation")


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
