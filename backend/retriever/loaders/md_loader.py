"""LangChain-style loader for Markdown/PDF-converted text. Wraps existing parser."""

from __future__ import annotations

from retriever.adapters import chunk_record_to_document
from retriever.parsers.md_parser import parse_markdown_text


def load_markdown(
    text: str,
    *,
    file_id: str,
    source_type: str = "md",
    session_id: str | None = None,
) -> list:
    """
    Load markdown text into LangChain Documents.
    Uses existing parse_markdown_text, then converts to Document via adapter.
    """
    from langchain_core.documents import Document

    chunks = parse_markdown_text(text, doc_id=file_id, source_type=source_type)
    docs: list[Document] = []
    for chunk in chunks:
        doc = chunk_record_to_document(chunk)
        if session_id:
            doc.metadata["session_id"] = session_id
        doc.metadata["file_id"] = file_id
        docs.append(doc)
    return docs
