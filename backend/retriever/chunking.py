"""
Chunking strategies by document facet.

Each file type (transcript, swot, etc.) can use a different chunk size,
overlap, and splitting logic for optimal retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .facet import DocumentFacet


@dataclass
class ChunkConfig:
    """Configuration for a chunking strategy."""

    chunk_size: int
    chunk_overlap: int
    separator: str = "\n\n"
    extra: dict[str, Any] | None = None


# Default configs per facet (override for fine-tuning)
FACET_CHUNK_CONFIGS: dict[DocumentFacet, ChunkConfig] = {
    DocumentFacet.TRANSCRIPT: ChunkConfig(
        chunk_size=800,
        chunk_overlap=100,
        separator="\n\n",
    ),
    DocumentFacet.SWOT: ChunkConfig(
        chunk_size=512,
        chunk_overlap=64,
        separator="\n",
    ),
    DocumentFacet.CUSTOMER_SEGMENTATION: ChunkConfig(
        chunk_size=600,
        chunk_overlap=80,
        separator="\n\n",
    ),
    DocumentFacet.MESSAGING_STRATEGY: ChunkConfig(
        chunk_size=600,
        chunk_overlap=80,
        separator="\n\n",
    ),
    DocumentFacet.OTHERS: ChunkConfig(
        chunk_size=512,
        chunk_overlap=64,
        separator="\n\n",
    ),
}


def get_chunking_strategy(facet: DocumentFacet) -> ChunkConfig:
    """Return the chunking config for the given document facet."""
    return FACET_CHUNK_CONFIGS.get(facet, FACET_CHUNK_CONFIGS[DocumentFacet.OTHERS])


def chunk_text(
    text: str,
    facet: DocumentFacet,
    config: ChunkConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Split text into chunks according to the facet's strategy.

    Args:
        text: Raw document text.
        facet: Document type (determines default config if config is None).
        config: Optional override; uses facet default if not provided.

    Returns:
        List of chunk dicts with keys like "text", "start", "end", "facet".
    """
    cfg = config or get_chunking_strategy(facet)
    chunks: list[dict[str, Any]] = []
    parts = text.split(cfg.separator) if cfg.separator else [text]
    pos = 0
    current: list[str] = []
    current_len = 0

    for part in parts:
        part_len = len(part) + (len(cfg.separator) if current else 0)
        if current_len + part_len > cfg.chunk_size and current:
            chunk_text_val = cfg.separator.join(current)
            start = pos - len(chunk_text_val)
            chunks.append({
                "text": chunk_text_val,
                "start": start,
                "end": pos,
                "facet": facet.value,
            })
            # Overlap: keep last N chars
            overlap_text = cfg.separator.join(current)
            kept = overlap_text[-cfg.chunk_overlap:] if cfg.chunk_overlap else ""
            current = [kept] if kept else []
            current_len = len(kept)
        current.append(part)
        current_len += part_len
        pos += part_len + (len(cfg.separator) if len(parts) > 1 else 0)

    if current:
        chunk_text_val = cfg.separator.join(current)
        start = pos - len(chunk_text_val)
        chunks.append({
            "text": chunk_text_val,
            "start": start,
            "end": pos,
            "facet": facet.value,
        })

    return chunks
