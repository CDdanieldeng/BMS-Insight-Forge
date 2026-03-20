"""Minimal document store: ingest files to markdown and serve full content."""

import uuid
from typing import Any

from fastapi import UploadFile

from shared.logging_config import setup_logging
from shared.converter import convert_to_markdown

logger = setup_logging("generation")

# In-memory stores: file_id -> full markdown text / metadata
_store: dict[str, str] = {}
_doc_meta_store: dict[str, dict[str, Any]] = {}


def get_document_text(file_id: str) -> str | None:
    """Return stored markdown text for a file_id."""
    return _store.get(file_id)


def get_document_meta(file_id: str) -> dict[str, Any]:
    """Return stored metadata for a file_id."""
    return _doc_meta_store.get(file_id, {})


def get_full_markdown_context(file_ids: list[str]) -> str:
    """
    Return full cleaned markdown for all file_ids in original order.
    Used for context retrieval when retrieval is disabled.
    """
    texts: list[str] = []
    for idx, fid in enumerate(file_ids, start=1):
        text = _store.get(fid)
        if text:
            meta = _doc_meta_store.get(fid, {})
            filename = str(meta.get("filename") or fid)
            texts.append(f"## Document {idx}: {filename}\n\n{text.strip()}")
    return "\n\n---\n\n".join(texts)


async def ingest_files(files: list[UploadFile]) -> dict[str, Any]:
    """
    Upload files, convert to markdown, and store in memory.
    Returns {"file_ids": [...], "errors": [...]}.
    """
    result = {"file_ids": [], "errors": []}
    logger.info("Ingest received %d files", len(files))

    for file in files:
        if not file.filename:
            result["errors"].append({"file": "unnamed", "error": "No filename"})
            continue

        ext = file.filename.lower().split(".")[-1] if "." in file.filename else ""
        if ext not in ("pptx", "docx", "doc", "md", "pdf"):
            result["errors"].append({"file": file.filename, "error": "Unsupported format"})
            continue

        try:
            content = await file.read()
            file_id = str(uuid.uuid4())
            md_text = convert_to_markdown(content, file.filename)
            _store[file_id] = md_text
            _doc_meta_store[file_id] = {"filename": file.filename, "ext": ext}
            result["file_ids"].append(file_id)
            logger.info("Ingested %s as %s", file.filename, file_id)
        except Exception as e:
            logger.exception("Failed to ingest %s: %s", file.filename, e)
            result["errors"].append({"file": file.filename, "error": str(e)})

    return result
