"""
Chunking strategies by document facet.

Each file type (transcript, swot, etc.) can use a different chunk size,
overlap, and splitting logic for optimal retrieval.
"""

from __future__ import annotations

import re
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
    """
    Chunker for interview/meeting transcripts.

    Splits by Q&A pairs. Supports Chinese and English formats:

    Chinese:
        问题Q1. ...
        答案：
    English:
        Question 1. ...  /  Q1. ...
        Answer:
        ...

    Each chunk is one complete Q&A pair (question + answer).
    Falls back to separator-based chunking when no Q&A structure is detected.
    """

    # Regex: 问题Qn (Chinese) | Question n (English) | Qn (English)
    _QA_PATTERN = re.compile(
        r"问题Q\s*\d+|Question\s*\d+|\bQ\s*\d+",
        re.IGNORECASE,
    )

    config = ChunkConfig(
        chunk_size=800,
        chunk_overlap=100,
        separator="\n\n",
    )

    def chunk(
        self,
        text: str,
        facet: DocumentFacet,
        config_override: ChunkConfig | None = None,
    ) -> list[dict[str, Any]]:
        """Split transcript by Q&A pairs; fall back to base chunking if no Q&A structure."""
        return self._chunk_by_qa_pairs(text, facet, config_override)

    def _chunk_by_qa_pairs(
        self,
        text: str,
        facet: DocumentFacet,
        config_override: ChunkConfig | None = None,
    ) -> list[dict[str, Any]]:
        """
        Split transcript into chunks by Q&A pairs.
        Each chunk = one Q&A block (问题Qn/Question n/Qn ... 答案：/Answer: ...).
        Falls back to _chunk_by_separator when no Q&A pattern is found.
        """
        matches = list(self._QA_PATTERN.finditer(text))
        if not matches:
            cfg = config_override or self.config
            return self._chunk_by_separator(text, facet, cfg)

        chunks: list[dict[str, Any]] = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk_text_val = text[start:end].strip()
            if chunk_text_val:
                chunks.append({
                    "text": chunk_text_val,
                    "start": start,
                    "end": end,
                    "facet": facet.value,
                })

        # Preamble before first Q&A marker (if non-empty)
        if matches and matches[0].start() > 0:
            preamble = text[: matches[0].start()].strip()
            if preamble:
                chunks.insert(0, {
                    "text": preamble,
                    "start": 0,
                    "end": matches[0].start(),
                    "facet": facet.value,
                })

        return chunks


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


if __name__ == "__main__":
    # Run: cd backend && python -m retriever.chunking
    text = """问题Q1. 你的典型客户是谁？
答案：我们主要服务二线城市的中型医院。

问题Q2. 最大的挑战是什么？
答案：价格敏感度和竞品对比。"""
    chunks = chunk_text(text, DocumentFacet.TRANSCRIPT)
    print(f"Chunks: {len(chunks)}")
    for i, c in enumerate(chunks):
        print(f"  {i+1}: {c['text'][:60]}...")
        print("*"*60)

