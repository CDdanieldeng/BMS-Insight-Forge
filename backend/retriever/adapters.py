"""
Document <-> ChunkRecord adapter for LangChain integration.

Ensures metadata normalization including page_number for all source types.
"""

from __future__ import annotations

from typing import Any

from langchain_core.documents import Document

from retriever.models import ChunkRecord
from retriever.parsers.normalize import estimate_tokens, segment_hints_from_text


def _ensure_page_number(metadata: dict[str, Any], source_type: str) -> int:
    """Derive page_number from parser-specific metadata. Must be preserved."""
    if "page_number" in metadata:
        return int(metadata["page_number"])
    if "slide_number" in metadata:
        return int(metadata["slide_number"])
    if "line_range" in metadata:
        rng = metadata["line_range"]
        if isinstance(rng, (list, tuple)) and rng:
            return int(rng[0])
    if "paragraph_range" in metadata:
        rng = metadata["paragraph_range"]
        if isinstance(rng, (list, tuple)) and rng:
            return int(rng[0])
    return 1


def chunk_record_to_document(chunk: ChunkRecord) -> Document:
    """Convert ChunkRecord to LangChain Document with normalized metadata."""
    meta = dict(chunk.metadata)
    meta["chunk_id"] = chunk.chunk_id
    meta["doc_id"] = chunk.doc_id
    meta["source_type"] = chunk.source_type
    meta["table_flag"] = chunk.table_flag
    meta["page_number"] = _ensure_page_number(meta, chunk.source_type)
    return Document(
        page_content=chunk.text,
        metadata=meta,
    )


def document_to_chunk_record(
    doc: Document,
    *,
    file_id: str,
    source_type: str = "unknown",
    table_flag: bool = False,
) -> ChunkRecord:
    """Convert LangChain Document to ChunkRecord. file_id used as doc_id."""
    meta = dict(doc.metadata)
    chunk_id = meta.pop("chunk_id", None) or f"{file_id}:{hash(doc.page_content) % 0xFFFFFFFF:08x}"
    doc_id = meta.pop("doc_id", file_id)
    st = meta.pop("source_type", source_type)
    tf = meta.pop("table_flag", table_flag)
    page_num = meta.get("page_number") or meta.get("slide_number")
    if page_num is not None:
        meta["page_number"] = int(page_num)

    token_length = estimate_tokens(doc.page_content)
    segment_hint = segment_hints_from_text(doc.page_content)

    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        source_type=st or source_type,
        text=doc.page_content,
        token_length=token_length,
        metadata=meta,
        table_flag=tf if tf is not None else table_flag,
        segment_hint=segment_hint,
        noise_flag=bool(meta.get("noise_flag", False)),
    )
