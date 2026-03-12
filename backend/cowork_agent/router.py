"""API router for CS cowork conversational agent."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from cowork_agent.models import (
    CoworkTurnRequest,
    CoworkTurnResponse,
    CoworkUploadResponse,
    DirectUploadedDoc,
)
from cowork_agent.orchestrator import CSCoworkOrchestrator
from retriever.converter import convert_to_markdown

router = APIRouter(prefix="/cowork-agent", tags=["cowork-agent"])
logger = __import__("logging").getLogger("cowork_agent")

_orchestrator = CSCoworkOrchestrator()


@router.post("/cs/chat", response_model=CoworkTurnResponse)
async def cs_cowork_chat(req: CoworkTurnRequest) -> CoworkTurnResponse:
    if req.module.strip().lower() != "customer segmentation":
        raise HTTPException(
            status_code=400,
            detail="Cowork mode is currently available for Customer Segmentation only.",
        )
    try:
        return _orchestrator.handle_turn(req)
    except Exception as e:
        logger.exception("Cowork chat failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cs/upload-files", response_model=CoworkUploadResponse)
async def cs_cowork_upload_files(
    session_id: str = Form(...),
    module: str = Form(...),
    files: list[UploadFile] = File(...),
) -> CoworkUploadResponse:
    if module.strip().lower() != "customer segmentation":
        raise HTTPException(
            status_code=400,
            detail="Cowork mode is currently available for Customer Segmentation only.",
        )
    converted_docs: list[DirectUploadedDoc] = []
    for f in files:
        if not f.filename:
            continue
        content = await f.read()
        try:
            md_text = convert_to_markdown(content, f.filename)
        except Exception as e:
            logger.warning("Cowork direct upload conversion failed file=%s err=%s", f.filename, e)
            continue
        converted_docs.append(
            DirectUploadedDoc(filename=f.filename, markdown_content=md_text)
        )
    if not converted_docs:
        raise HTTPException(
            status_code=400,
            detail="No valid files were converted. Supported: .pptx/.docx/.doc/.pdf/.md",
        )
    session = _orchestrator.store_direct_upload_docs(
        session_id=session_id,
        module=module,
        docs=converted_docs,
    )
    return CoworkUploadResponse(
        session_id=session.session_id,
        uploaded_count=len(converted_docs),
        total_docs_in_memory=len(session.direct_uploaded_docs),
        filenames=[d.filename for d in converted_docs],
    )

