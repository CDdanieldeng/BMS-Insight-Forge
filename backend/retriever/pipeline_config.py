"""Configuration for agentic evidence pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


@dataclass(slots=True)
class PipelineConfig:
    max_candidates: int = 150
    max_facet_new_per_request: int = 120
    facet_batch_size: int = 12
    facet_async_workers: int = 3
    max_chunks_agent_read: int = 20
    max_to_compress: int = 20
    max_iterations_expand: int = 1
    max_agent_steps: int = 3


def load_pipeline_config() -> PipelineConfig:
    return PipelineConfig(
        max_candidates=max(10, _env_int("MAX_CANDIDATES", 150)),
        max_facet_new_per_request=max(1, _env_int("MAX_FACET_NEW_PER_REQUEST", 120)),
        facet_batch_size=max(1, _env_int("FACET_BATCH_SIZE", 12)),
        facet_async_workers=max(1, _env_int("FACET_ASYNC_WORKERS", 3)),
        max_chunks_agent_read=max(1, _env_int("MAX_CHUNKS_AGENT_READ", 20)),
        max_to_compress=max(1, _env_int("MAX_TO_COMPRESS", 20)),
        max_iterations_expand=max(0, _env_int("MAX_ITERATIONS_EXPAND", 1)),
        max_agent_steps=max(1, _env_int("MAX_AGENT_STEPS", 3)),
    )
