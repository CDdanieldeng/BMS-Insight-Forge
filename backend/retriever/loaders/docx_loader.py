"""LangChain-style loader for DOCX files. Wraps existing parser."""

from __future__ import annotations

from retriever.adapters import chunk_record_to_document
from retriever.parsers.docx_parser import parse_docx_bytes


def load_docx(content: bytes, *, file_id: str, session_id: str | None = None) -> list:
    """
    Load DOCX bytes into LangChain Documents.
    Uses existing parse_docx_bytes, then converts to Document via adapter.
    """
    from langchain_core.documents import Document

    chunks = parse_docx_bytes(content, doc_id=file_id)
    docs: list[Document] = []
    for chunk in chunks:
        doc = chunk_record_to_document(chunk)
        if session_id:
            doc.metadata["session_id"] = session_id
        doc.metadata["file_id"] = file_id
        docs.append(doc)
    return docs
