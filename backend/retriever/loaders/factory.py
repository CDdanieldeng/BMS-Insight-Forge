"""Factory to select loader by file extension."""

from __future__ import annotations

from pathlib import Path


def load_documents(
    content: bytes | str,
    *,
    file_id: str,
    filename: str,
    session_id: str | None = None,
) -> list:
    """
    Load documents by extension. Returns list of LangChain Documents.
    For md/pdf, content must be str (converted text). For pptx/docx, content is bytes.
    """
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext == "pptx":
        if isinstance(content, str):
            raise ValueError("PPTX loader expects bytes")
        return __import__("retriever.loaders.pptx_loader", fromlist=["load_pptx"]).load_pptx(
            content, file_id=file_id, session_id=session_id
        )
    if ext in ("docx", "doc"):
        if isinstance(content, str):
            raise ValueError("DOCX loader expects bytes")
        return __import__("retriever.loaders.docx_loader", fromlist=["load_docx"]).load_docx(
            content, file_id=file_id, session_id=session_id
        )
    if ext in ("md", "pdf"):
        text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
        st = "pdf_md" if ext == "pdf" else "md"
        return __import__("retriever.loaders.md_loader", fromlist=["load_markdown"]).load_markdown(
            text, file_id=file_id, source_type=st, session_id=session_id
        )
    raise ValueError(f"Unsupported format: {filename}")
