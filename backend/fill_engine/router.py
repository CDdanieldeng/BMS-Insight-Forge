"""FastAPI router for the fill engine service."""

import base64
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import Response

from fill_engine.engine import (
    fill_table,
    get_slide_info,
    get_table_structure,
    load_presentation,
)
from fill_engine.slide_renderer import render_slide_to_png

router = APIRouter(prefix="/fill-engine", tags=["fill-engine"])
logger = __import__("logging").getLogger("fill_engine")


@router.post("/slide-info")
async def slide_info(file: UploadFile = File(...)) -> list[dict[str, Any]]:
    """
    Parse pptx and return slide metadata.
    Accepts pptx file upload.
    """
    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Expected .pptx file")

    content = await file.read()
    try:
        result = get_slide_info(pptx_bytes=content)
        return result
    except Exception as e:
        logger.exception("Failed to get slide info: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/slide-info-from-path")
async def slide_info_from_path(path: str = Form(...)) -> list[dict[str, Any]]:
    """
    Parse pptx from file path (for template on disk).
    """
    try:
        result = get_slide_info(pptx_path=path)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Failed to get slide info: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/table-structure")
async def table_structure(
    slide_idx: int = Form(...),
    file: UploadFile | None = File(None),
    path: str | None = Form(None),
) -> dict[str, Any]:
    """
    Get table structure for a slide. Provide either file upload or path.
    """
    if file:
        content = await file.read()
        structure = get_table_structure(pptx_bytes=content, slide_idx=slide_idx)
    elif path:
        structure = get_table_structure(pptx_path=path, slide_idx=slide_idx)
    else:
        raise HTTPException(status_code=400, detail="Provide file or path")

    return structure


@router.post("/fill-table")
async def fill_table_endpoint(
    slide_idx: int = Form(...),
    file: UploadFile = File(...),
    table_data_b64: str = Form(...),
    column_headers_b64: str | None = Form(None),
) -> dict[str, str]:
    """
    Fill table and return updated pptx bytes (base64 encoded in response).

    table_data_b64:     base64-encoded JSON 2-D array of cell values
                        (no header row, no index column).
    column_headers_b64: optional base64-encoded JSON array of segment name strings
                        that replace placeholder column headers (row 0, cols 1+).
    """
    import json

    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Expected .pptx file")

    content = await file.read()

    try:
        table_data_raw = base64.b64decode(table_data_b64).decode("utf-8")
        table_data = json.loads(table_data_raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid table_data: {e}")

    if not isinstance(table_data, list) or not all(isinstance(r, list) for r in table_data):
        raise HTTPException(status_code=400, detail="table_data must be list of lists")

    column_headers: list[str] | None = None
    if column_headers_b64:
        try:
            raw = base64.b64decode(column_headers_b64).decode("utf-8")
            column_headers = json.loads(raw)
            if not isinstance(column_headers, list):
                raise ValueError("Expected a list")
            column_headers = [str(h) for h in column_headers]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid column_headers: {e}")

    try:
        result_bytes = fill_table(content, slide_idx, table_data, column_headers=column_headers)
        return {"pptx_base64": base64.b64encode(result_bytes).decode("utf-8")}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Failed to fill table: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/render-slide-png")
async def render_slide_png(
    slide_idx: int = Form(...),
    file: UploadFile | None = File(None),
    path: str | None = Form(None),
) -> Response:
    """
    Render a slide to PNG using matplotlib with BMS-branded table styling.
    Provide either file upload or path.
    """
    if file:
        if not file.filename or not file.filename.lower().endswith(".pptx"):
            raise HTTPException(status_code=400, detail="Expected .pptx file")
        content = await file.read()
        prs = load_presentation(pptx_bytes=content)
    elif path:
        prs = load_presentation(pptx_path=path)
    else:
        raise HTTPException(status_code=400, detail="Provide file or path")

    if slide_idx < 0 or slide_idx >= len(prs.slides):
        raise HTTPException(status_code=400, detail=f"Invalid slide_idx: {slide_idx}")

    try:
        png_bytes = render_slide_to_png(prs, slide_idx)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        logger.exception("Failed to render slide: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
