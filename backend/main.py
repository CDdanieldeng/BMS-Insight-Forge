"""FastAPI backend for Insight Forge - mounts all services."""

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.logging_config import setup_logging

from fill_engine.router import router as fill_engine_router
from generation.router import router as generation_router
from retriever.router import router as retriever_router
from cowork_agent.router import router as cowork_agent_router

# Load .env from project root so backend works even when started manually.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

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
)

app.include_router(generation_router)
app.include_router(retriever_router)
app.include_router(fill_engine_router)
app.include_router(cowork_agent_router)


@app.get("/health")
def health():
    return {"status": "ok"}
