"""FastAPI router for the retriever service."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from retriever.converter import convert_to_markdown

router = APIRouter(prefix="/retriever", tags=["retriever"])
logger = __import__("logging").getLogger("retriever")

# In-memory store: file_id -> markdown content (PoC)
_store: dict[str, str] = {}


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
            result["file_ids"].append(file_id)
            logger.info("Ingested %s as %s", file.filename, file_id)
        except Exception as e:
            logger.exception("Failed to ingest %s: %s", file.filename, e)
            result["errors"].append({"file": file.filename, "error": str(e)})

    return result


@router.post("/search")
async def search(req: SearchRequest) -> dict[str, Any]:
    """
    Return concatenated text from stored files.
    For PoC: query is ignored, we return all content from file_ids.
    """
    texts = []
    for fid in req.file_ids:
        if fid in _store:
            texts.append(_store[fid])
        else:
            logger.warning("File id not found: %s", fid)

    combined = "\n\n---\n\n".join(texts)
    return {"content": combined, "char_count": len(combined)}
