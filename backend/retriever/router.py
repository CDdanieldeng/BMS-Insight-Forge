"""FastAPI router for the retriever service."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from retriever.chunker import bm25_retrieve_records
from retriever.converter import convert_to_markdown
from retriever.models import ChunkRecord
from retriever.vector_store import SentenceTransformerStore
from retriever.parsers.docx_parser import parse_docx_bytes
from retriever.parsers.md_parser import parse_markdown_text
from retriever.parsers.pptx_parser import parse_pptx_bytes

router = APIRouter(prefix="/retriever", tags=["retriever"])
logger = __import__("logging").getLogger("retriever")

# In-memory stores: file_id -> full markdown text / list of chunks
_store: dict[str, str] = {}
_chunk_store: dict[str, list[ChunkRecord]] = {}
_doc_meta_store: dict[str, dict[str, Any]] = {}
try:
    _embedding_store = SentenceTransformerStore()
except Exception:
    from retriever.index_store import EmbeddingIndexStore
    _embedding_store = EmbeddingIndexStore()


class SearchRequest(BaseModel):
    file_ids: list[str]
    query: str = ""


@router.post("/ingest")
async def ingest(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """
    Upload files, parse into chunks, and store in memory.
    Returns file_id for each file.
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

            if ext == "pptx":
                chunks = parse_pptx_bytes(content, doc_id=file_id)
                md_text = convert_to_markdown(content, file.filename)
            elif ext in {"docx", "doc"}:
                chunks = parse_docx_bytes(content, doc_id=file_id)
                md_text = convert_to_markdown(content, file.filename)
            else:
                md_text = convert_to_markdown(content, file.filename)
                source_type = "pdf_md" if ext == "pdf" else "md"
                chunks = parse_markdown_text(md_text, doc_id=file_id, source_type=source_type)

            _store[file_id] = md_text
            _chunk_store[file_id] = chunks
            _doc_meta_store[file_id] = {"filename": file.filename, "ext": ext}
            _embedding_store.upsert_chunks(chunks)
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
    all_chunks: list[ChunkRecord] = []
    for fid in req.file_ids:
        if fid in _chunk_store:
            all_chunks.extend(_chunk_store[fid])
        else:
            logger.warning("File id not found: %s", fid)

    relevant = bm25_retrieve_records(all_chunks, req.query, top_k=12)
    combined = "\n\n---\n\n".join(chunk.as_text_block() for chunk in relevant)
    logger.info(
        "Search query_len=%d total_chunks=%d returned_chunks=%d result_chars=%d",
        len(req.query),
        len(all_chunks),
        len(relevant),
        len(combined),
    )
    return {"content": combined, "char_count": len(combined)}
