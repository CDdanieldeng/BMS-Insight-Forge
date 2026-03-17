"""Agentic evidence retrieval pipeline with lazy facet and compression."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

from retriever.chunker import bm25_retrieve_records
from retriever.graph import build_evidence_graph
from retriever.models import ChunkRecord
from retriever.pipeline_config import PipelineConfig
from retriever.retrieval_logger import log_retrieval_step
from retriever.router import _chunk_store

logger = setup_logging("retriever")

_RETRIEVAL_CHUNKS_DIR = Path(__file__).resolve().parents[1] / "logs" / "retrieval_chunks"


@dataclass(slots=True)
class EvidencePipelineResult:
    context_text: str
    snippets: list[dict[str, Any]]
    metrics: dict[str, Any]
    degraded: bool = False


def _write_recall_rerank_chunks(
    *,
    candidates: list[ChunkRecord],
    confirmed: list[ChunkRecord],
    seed_query: str,
    module: str,
    file_ids: list[str],
) -> None:
    """Persist recall and rerank chunks to logs for debugging."""
    try:
        _RETRIEVAL_CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
        module_slug = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "_",
            (module or "").strip().lower(),
        ).strip("_")
        if not module_slug:
            module_slug = "module"
        file_name = (
            f"{time.strftime('%Y%m%d_%H%M%S')}_{module_slug}_{uuid.uuid4().hex[:8]}.txt"
        )
        file_path = _RETRIEVAL_CHUNKS_DIR / file_name

        recall_blocks = [chunk.as_text_block() for chunk in candidates]
        rerank_blocks = [chunk.as_text_block() for chunk in confirmed]

        text = (
            f"module: {module}\n"
            f"file_ids: {file_ids}\n"
            f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"metrics: recall_count={len(candidates)} rerank_count={len(confirmed)}\n"
            "\n=== SEED QUERY ===\n"
            + (seed_query or "")
            + "\n\n=== RECALL CHUNKS ===\n"
            + ("\n\n---\n\n".join(recall_blocks) if recall_blocks else "(none)")
            + "\n\n=== RERANK CHUNKS ===\n"
            + ("\n\n---\n\n".join(rerank_blocks) if rerank_blocks else "(none)")
            + "\n"
        )
        file_path.write_text(text, encoding="utf-8")
        logger.info(
            "Retrieval chunks written module=%s path=%s recall=%d rerank=%d",
            module,
            file_path,
            len(candidates),
            len(confirmed),
        )
    except Exception as e:
        logger.warning(
            "Failed to write retrieval chunks module=%s err=%s", module, e
        )


def _fallback_context(file_ids: list[str], query: str, top_k: int) -> str:
    """BM25 fallback with per-doc cap so multiple files contribute to context."""
    all_chunks: list[ChunkRecord] = []
    for fid in file_ids:
        all_chunks.extend(_chunk_store.get(fid, []))
    top = bm25_retrieve_records(all_chunks, query, top_k=top_k * 2)
    unique_docs = len({c.doc_id for c in top})
    max_per_doc = max(15, top_k // max(1, unique_docs))
    doc_counts: dict[str, int] = {}
    capped: list[ChunkRecord] = []
    for c in top:
        if len(capped) >= top_k:
            break
        n = doc_counts.get(c.doc_id, 0)
        if n >= max_per_doc:
            continue
        doc_counts[c.doc_id] = n + 1
        capped.append(c)
    return "\n\n---\n\n".join(chunk.as_text_block() for chunk in capped)


def run_evidence_pipeline(
    *,
    file_ids: list[str],
    module: str,
    table_structure: dict[str, Any],
    seed_query: str,
    config: PipelineConfig,
    top_k_fallback: int = 50,
) -> EvidencePipelineResult:
    """
    Execute LangGraph evidence pipeline.
    Degrades to BM25-only context on failures.
    """
    start = time.perf_counter()
    metrics: dict[str, Any] = {"seed_query_len": len(seed_query or "")}
    try:
        graph = build_evidence_graph()
        initial_state: dict[str, Any] = {
            "file_ids": file_ids,
            "module": module or "",
            "table_structure": table_structure or {},
            "seed_query": seed_query or "",
            "config": config,
            "top_k_fallback": top_k_fallback,
        }
        final_state = graph.invoke(initial_state)

        context_text = final_state.get("context_text") or ""
        snippets = final_state.get("snippets") or []
        degraded = final_state.get("degraded", False)

        metrics["total_ms"] = int((time.perf_counter() - start) * 1000)
        metrics["degraded"] = degraded
        recall_count = len(final_state.get("candidates", []))
        rerank_count = len(final_state.get("confirmed", []))
        metrics["recall_count"] = recall_count
        metrics["rerank_count"] = rerank_count
        if snippets:
            metrics["unique_docs_in_result"] = len(
                {s["chunk_id"].split(":")[0] for s in snippets}
            )
        if final_state.get("all_chunks"):
            metrics["initial_candidates"] = len(final_state["all_chunks"])
        if final_state.get("filtered"):
            metrics["filtered_candidates"] = len(final_state["filtered"])
        if final_state.get("confirmed"):
            metrics["confirmed_chunks"] = len(final_state["confirmed"])
        metrics["compression_snippets"] = len(snippets)

        # Key counts for debugging generation issues
        logger.info(
            "retrieval recall_count=%d rerank_count=%d snippets=%d file_ids=%s degraded=%s",
            recall_count,
            rerank_count,
            len(snippets),
            file_ids,
            degraded,
        )

        log_retrieval_step(
            stage="evidence_output",
            step="complete",
            queries=[seed_query],
            after=[{"chunk_id": s.get("chunk_id"), "score": s.get("score")} for s in snippets[:10]],
            latency_ms=metrics.get("total_ms"),
            file_ids=file_ids,
            extra={"metrics": metrics, "degraded": degraded},
        )
        log_retrieval_step(
            "evidence_output",
            "done",
            queries=[seed_query],
            after=[{"chunk_id": s.get("chunk_id"), "len": len(s.get("text", ""))} for s in snippets],
            latency_ms=metrics.get("total_ms"),
            file_ids=file_ids,
            extra={"metrics": metrics, "degraded": degraded},
        )

        _write_recall_rerank_chunks(
            candidates=final_state.get("candidates", []),
            confirmed=final_state.get("confirmed", []),
            seed_query=seed_query or "",
            module=module or "",
            file_ids=file_ids,
        )

        logger.info(
            "Evidence pipeline done metrics=%s degraded=%s",
            metrics,
            degraded,
        )
        return EvidencePipelineResult(
            context_text=context_text,
            snippets=snippets,
            metrics=metrics,
            degraded=degraded,
        )
    except Exception as exc:
        metrics["degraded"] = True
        metrics["error"] = str(exc)
        metrics["total_ms"] = int((time.perf_counter() - start) * 1000)
        metrics["recall_count"] = 0
        metrics["rerank_count"] = 0
        logger.warning(
            "Evidence pipeline failed, fallback to BM25 err=%s metrics=%s recall_count=0 rerank_count=0",
            exc,
            metrics,
        )
        fallback = _fallback_context(file_ids, seed_query, top_k=top_k_fallback)
        return EvidencePipelineResult(
            context_text=fallback,
            snippets=[],
            metrics=metrics,
            degraded=True,
        )
