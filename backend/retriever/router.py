"""FastAPI router for the retriever service."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from retriever.chunker import bm25_retrieve, split_chunks
from retriever.converter import convert_to_markdown

router = APIRouter(prefix="/retriever", tags=["retriever"])
logger = __import__("logging").getLogger("retriever")

# In-memory stores: file_id -> full markdown text / list of chunks
_store: dict[str, str] = {}
_chunk_store: dict[str, list[str]] = {}


class SearchRequest(BaseModel):
    file_ids: list[str]
    query: str = ""


@router.post("/ingest")
async def ingest(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """
    Upload files (pptx, docx), convert to markdown, store in memory.
    Returns file_id for each file.
    """
    result = {"file_ids": [], "errors": []}

    for file in files:
        if not file.filename:
            result["errors"].append({"file": "unnamed", "error": "No filename"})
            continue

        ext = file.filename.lower().split(".")[-1] if "." in file.filename else ""
        if ext not in ("pptx", "docx", "doc"):
            result["errors"].append({"file": file.filename, "error": "Unsupported format"})
            continue

        try:
            content = await file.read()
            md_text = convert_to_markdown(content, file.filename)
            file_id = str(uuid.uuid4())
            _store[file_id] = md_text
            chunks = split_chunks(md_text)
            _chunk_store[file_id] = chunks
            result["file_ids"].append(file_id)
            logger.info("Ingested %s as %s (%d chunks)", file.filename, file_id, len(chunks))
        except Exception as e:
            logger.exception("Failed to ingest %s: %s", file.filename, e)
            result["errors"].append({"file": file.filename, "error": str(e)})

    return result


@router.post("/search")
async def search(req: SearchRequest) -> dict[str, Any]:
    """
    Return the most query-relevant chunks from stored files using BM25.
    Falls back to first N chunks when query is empty.
    """
    all_chunks: list[str] = []
    for fid in req.file_ids:
        if fid in _chunk_store:
            all_chunks.extend(_chunk_store[fid])
        else:
            logger.warning("File id not found: %s", fid)

    relevant = bm25_retrieve(all_chunks, req.query, top_k=12)
    combined = "\n\n---\n\n".join(relevant)
    logger.info(
        "Search query_len=%d total_chunks=%d returned_chunks=%d result_chars=%d",
        len(req.query),
        len(all_chunks),
        len(relevant),
        len(combined),
    )
    return {"content": combined, "char_count": len(combined)}
