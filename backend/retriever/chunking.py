"""
Chunking strategies by document facet.

Each file type (transcript, swot, etc.) can use a different chunk size,
overlap, and splitting logic for optimal retrieval.
"""

from __future__ import annotations

from abc import ABC
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


class BaseChunker(ABC):
    """
    Base class for chunking strategies.

    Subclasses set their config and may override chunk() for custom logic.
    """

    config: ChunkConfig

    def chunk(
        self,
        text: str,
        facet: DocumentFacet,
        config_override: ChunkConfig | None = None,
    ) -> list[dict[str, Any]]:
        """
        Split text into chunks according to this strategy.

        Args:
            text: Raw document text.
            facet: Document type (included in chunk metadata).
            config_override: Optional override; uses self.config if not provided.

        Returns:
            List of chunk dicts with keys like "text", "start", "end", "facet".
        """
        cfg = config_override or self.config
        return self._chunk_by_separator(text, facet, cfg)

    def _chunk_by_separator(
        self,
        text: str,
        facet: DocumentFacet,
        config: ChunkConfig,
    ) -> list[dict[str, Any]]:
        """Split text by separator, respecting chunk_size and chunk_overlap."""
        cfg = config
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


# ---------------------------------------------------------------------------
# Per-facet chunkers
# ---------------------------------------------------------------------------


class TranscriptChunker(BaseChunker):
    """Chunker for interview/meeting transcripts."""

    config = ChunkConfig(
        chunk_size=800,
        chunk_overlap=100,
        separator="\n\n",
    )


class SwotChunker(BaseChunker):
    """Chunker for SWOT analysis documents."""

    config = ChunkConfig(
        chunk_size=512,
        chunk_overlap=64,
        separator="\n",
    )


class CustomerSegmentationChunker(BaseChunker):
    """Chunker for customer segmentation documents."""

    config = ChunkConfig(
        chunk_size=600,
        chunk_overlap=80,
        separator="\n\n",
    )


class MessagingStrategyChunker(BaseChunker):
    """Chunker for messaging strategy documents."""

    config = ChunkConfig(
        chunk_size=600,
        chunk_overlap=80,
        separator="\n\n",
    )


class OthersChunker(BaseChunker):
    """Fallback chunker for unspecified document types."""

    config = ChunkConfig(
        chunk_size=512,
        chunk_overlap=64,
        separator="\n\n",
    )


# ---------------------------------------------------------------------------
# Registry and factory
# ---------------------------------------------------------------------------

CHUNKERS: dict[DocumentFacet, type[BaseChunker]] = {
    DocumentFacet.TRANSCRIPT: TranscriptChunker,
    DocumentFacet.SWOT: SwotChunker,
    DocumentFacet.CUSTOMER_SEGMENTATION: CustomerSegmentationChunker,
    DocumentFacet.MESSAGING_STRATEGY: MessagingStrategyChunker,
    DocumentFacet.OTHERS: OthersChunker,
}


def get_chunker(facet: DocumentFacet) -> BaseChunker:
    """Return a chunker instance for the given document facet."""
    cls = CHUNKERS.get(facet, OthersChunker)
    return cls()


# ---------------------------------------------------------------------------
# Public API (backward compatible)
# ---------------------------------------------------------------------------

FACET_CHUNK_CONFIGS: dict[DocumentFacet, ChunkConfig] = {
    f: get_chunker(f).config for f in DocumentFacet
}


def get_chunking_strategy(facet: DocumentFacet) -> ChunkConfig:
    """Return the chunking config for the given document facet."""
    return get_chunker(facet).config


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
    return get_chunker(facet).chunk(text, facet, config)
