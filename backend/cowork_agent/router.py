"""API router for cowork conversational agents. Dispatches via module registry."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from modules._registry import get_module

from cowork_agent.models import (
    CoworkTurnRequest,
    CoworkTurnResponse,
    CoworkUploadResponse,
    DirectUploadedDoc,
    WorkflowState,
)
from retriever.converter import convert_to_markdown

router = APIRouter(prefix="/cowork-agent", tags=["cowork-agent"])
logger = __import__("logging").getLogger("cowork_agent")


def _normalize_workflow_state(result: dict) -> dict:
    """Ensure workflow.state is a valid WorkflowState enum for CoworkTurnResponse."""
    wf = result.get("workflow")
    if wf and isinstance(wf.get("state"), str):
        try:
            wf = dict(wf)
            wf["state"] = WorkflowState(wf["state"])
            result = dict(result)
            result["workflow"] = wf
        except ValueError:
            wf = dict(wf)
            wf["state"] = WorkflowState.REVIEWING_WITH_USER
            result = dict(result)
            result["workflow"] = wf
    return result


@router.post("/cs/chat", response_model=CoworkTurnResponse)
async def cs_cowork_chat(req: CoworkTurnRequest) -> CoworkTurnResponse:
    provider = get_module(req.module)
    if not provider or not provider.get_cowork_agent():
        raise HTTPException(
            status_code=400,
            detail="Cowork mode is not available for this module.",
        )
    try:
        result = provider.get_cowork_agent().handle_turn(req)
        if isinstance(result, dict):
            result = _normalize_workflow_state(result)
            return CoworkTurnResponse(**result)
        return result
    except Exception as e:
        logger.exception("Cowork chat failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cs/upload-files", response_model=CoworkUploadResponse)
async def cs_cowork_upload_files(
    session_id: str = Form(...),
    module: str = Form(...),
    files: list[UploadFile] = File(...),
) -> CoworkUploadResponse:
    provider = get_module(module)
    if not provider or not provider.get_cowork_agent():
        raise HTTPException(
            status_code=400,
            detail="Cowork upload is not available for this module.",
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
    session = provider.get_cowork_agent().store_direct_upload_docs(
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


# ─── SWOT Cowork ───────────────────────────────────────────────────────────


@router.post("/swot/chat", response_model=CoworkTurnResponse)
async def swot_cowork_chat(req: CoworkTurnRequest) -> CoworkTurnResponse:
    provider = get_module(req.module)
    if not provider or not provider.get_cowork_agent():
        raise HTTPException(
            status_code=400,
            detail="SWOT chat is not available for this module.",
        )
    try:
        result = provider.get_cowork_agent().handle_turn(req)
        result = _normalize_workflow_state(result)
        return CoworkTurnResponse(**result)
    except Exception as e:
        logger.exception("SWOT cowork chat failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/swot/upload-files", response_model=CoworkUploadResponse)
async def swot_cowork_upload_files(
    session_id: str = Form(...),
    module: str = Form(...),
    files: list[UploadFile] = File(...),
) -> CoworkUploadResponse:
    provider = get_module(module)
    if not provider or not provider.get_cowork_agent():
        raise HTTPException(
            status_code=400,
            detail="SWOT upload is not available for this module.",
        )
    converted_docs: list[DirectUploadedDoc] = []
    for f in files:
        if not f.filename:
            continue
        content = await f.read()
        try:
            md_text = convert_to_markdown(content, f.filename)
        except Exception as e:
            logger.warning("SWOT cowork upload conversion failed file=%s err=%s", f.filename, e)
            continue
        converted_docs.append(
            DirectUploadedDoc(filename=f.filename, markdown_content=md_text)
        )
    if not converted_docs:
        raise HTTPException(
            status_code=400,
            detail="No valid files were converted. Supported: .pptx/.docx/.doc/.pdf/.md",
        )
    session = provider.get_cowork_agent().store_direct_upload_docs(
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
