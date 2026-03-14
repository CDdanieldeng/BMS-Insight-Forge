"""FastAPI router for web search via Tavily — self-contained, no shared state."""

import logging
import traceback

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .tavily_client import search as tavily_search

logger = logging.getLogger("web_search")

router = APIRouter(prefix="/web-search", tags=["web-search"])


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query string")
    max_results: int = Field(5, ge=1, le=10, description="Number of results to return")


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str


@router.post("/search", response_model=SearchResponse)
def web_search(req: SearchRequest):
    """Search the web using Tavily and return up to max_results results."""
    try:
        raw = tavily_search(req.query, req.max_results)
        return SearchResponse(
            query=req.query,
            results=[SearchResult(**r) for r in raw],
        )
    except ValueError as e:
        logger.error("Web search config error: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Web search error:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")
