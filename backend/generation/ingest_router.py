"""Document ingest API: upload files and store as markdown."""

from fastapi import APIRouter, File, UploadFile

from generation.document_store import ingest_files

router = APIRouter(prefix="/document", tags=["document"])


@router.post("/ingest")
async def ingest(files: list[UploadFile] = File(...)):
    """
    Upload files, convert to markdown, and store in memory.
    Returns {"file_ids": [...], "errors": [...]}.
    """
    return await ingest_files(files)
