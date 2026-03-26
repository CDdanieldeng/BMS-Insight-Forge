"""FastAPI backend for Insight Forge - mounts all services."""

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env before any imports that depend on env vars (e.g. voice ASR).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.entra_jwt import AUTH_ENABLED
from auth.middleware import EntraAuthMiddleware
from shared.logging_config import setup_logging

from fill_engine.router import router as fill_engine_router
from generation.router import router as generation_router
from generation.ingest_router import router as document_ingest_router
from modules.cowork.router import router as cowork_agent_router
from web_search.router import router as web_search_router
from voice.router import router as voice_router

logger = setup_logging("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Insight Forge backend starting")
    yield
    logger.info("Insight Forge backend shutting down")


app = FastAPI(
    title="Insight Forge API",
    description="GenAI-powered business plan slide deck filler",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Insight-Forge-Slide-Preview"],
)
app.add_middleware(EntraAuthMiddleware)

app.include_router(generation_router)
app.include_router(document_ingest_router)
app.include_router(fill_engine_router)
app.include_router(cowork_agent_router)
app.include_router(web_search_router)
app.include_router(voice_router)


@app.get("/health")
def health():
    return {"status": "ok", "auth_enabled": AUTH_ENABLED}
