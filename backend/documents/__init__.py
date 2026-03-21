"""Document ingest and in-memory storage."""

from documents.document_store import (
    get_document_meta,
    get_document_text,
    get_full_markdown_context,
    ingest_files,
)

__all__ = [
    "get_document_meta",
    "get_document_text",
    "get_full_markdown_context",
    "ingest_files",
]
