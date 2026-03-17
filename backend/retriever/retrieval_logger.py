"""
Structured retrieval logging for debugging generation issues.

Records: input, query gen, recall, rerank, output, timing.
Debug mode (RETRIEVAL_DEBUG=true): includes chunk text (truncated).
"""

from __future__ import annotations

import os
import time
from typing import Any

from shared.logging_config import setup_logging

logger = setup_logging("retriever")


def _is_debug() -> bool:
    raw = os.getenv("RETRIEVAL_DEBUG", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def log_retrieval_step(
    stage: str,
    step: str,
    *,
    queries: list[str] | None = None,
    before: list[Any] | None = None,
    after: list[Any] | None = None,
    latency_ms: int | None = None,
    file_ids: list[str] | None = None,
    column_name: str | None = None,
    index: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Log a structured retrieval step.
    In debug mode, before/after may include truncated chunk text.
    """
    payload: dict[str, Any] = {
        "stage": "retrieval",
        "step": step,
        "sub_stage": stage,
    }
    if queries is not None:
        payload["queries"] = queries
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    if file_ids is not None:
        payload["file_ids"] = file_ids
    if column_name is not None:
        payload["column_name"] = column_name
    if index is not None:
        payload["index"] = index
    if extra:
        payload.update(extra)

    if before is not None:
        if _is_debug():
            payload["before"] = [
                str(x)[:200] + "..." if len(str(x)) > 200 else x
                for x in before[:20]
            ]
        else:
            payload["before_count"] = len(before)

    if after is not None:
        if _is_debug():
            payload["after"] = [
                str(x)[:200] + "..." if len(str(x)) > 200 else x
                for x in after[:20]
            ]
        else:
            payload["after_count"] = len(after)

    logger.info("retrieval_step %s", payload)
