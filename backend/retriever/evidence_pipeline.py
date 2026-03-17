"""Agentic evidence retrieval pipeline with lazy facet and compression."""

from __future__ import annotations

import contextvars
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from shared.logging_config import setup_logging

from retriever.compression import compress_chunk
from retriever.evidence_judge import judge_snippet
from retriever.facet_cache import FacetCache
from retriever.facet_extractor import extract_facets_batch
from retriever.pipeline_config import PipelineConfig
from generation.stage_metrics import stage_scope
from retriever.chunker import bm25_retrieve_records
from retriever.hybrid import hybrid_retrieve
from retriever.models import ChunkRecord
from retriever.router import _chunk_store, _embedding_store

logger = setup_logging("retriever")
_cache = FacetCache()


@dataclass(slots=True)
class EvidencePipelineResult:
    context_text: str
    snippets: list[dict[str, Any]]
    metrics: dict[str, Any]
    degraded: bool = False


def _tokenize_query(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b", text or "")
        if len(t) > 2
    }


def _build_sub_queries(seed_query: str, module: str, table_structure: dict[str, Any]) -> list[str]:
    """Build diverse sub-queries from seed + table columns/indexes for hybrid retrieval."""
    columns = [str(c).strip() for c in (table_structure.get("columns") or []) if str(c).strip()]
    indexes = [str(i).strip() for i in (table_structure.get("indexes") or []) if str(i).strip()]
    # Use columns[1:] to skip empty or ID column; cap to avoid explosion.
    cols = columns[1:6]
    idxs = indexes[:6]
    subs: list[str] = []

    # SWOT: use only the four column names (Strengths, Weaknesses, Opportunities, Threats) as guide.
    is_swot = (module or "").strip().lower() == "swot analysis"

    # 1) Seed + single column — retrieval by dimension (e.g. channel, preference, SWOT quadrant).
    for col in cols:
        subs.append(f"{seed_query}; {col}")

    if not is_swot:
        # 2) Seed + single index — retrieval by segment/row (e.g. Safe Player, segment name).
        for idx in idxs:
            subs.append(f"{seed_query}; {idx}")
        # 3) Seed + column + index — targeted combination (fewer to keep diversity).
        for col in cols[:3]:
            for idx in idxs[:3]:
                subs.append(f"{seed_query}; {col}; {idx}")

    # 4) Module context when present.
    if module:
        subs.append(f"{module}; {seed_query}")

    # Deduplicate and cap at 10 so hybrid_retrieve stays bounded.
    seen: set[str] = set()
    deduped: list[str] = []
    for q in subs:
        key = q.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(q)
        if len(deduped) >= 10:
            break
    return deduped[:10]


def _cheap_filter(chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    out: list[ChunkRecord] = []
    for chunk in chunks:
        if chunk.noise_flag:
            continue
        if chunk.token_length < 40 and not chunk.table_flag and not chunk.segment_hint:
            continue
        out.append(chunk)
    return out


def _facet_gate(
    chunks: list[ChunkRecord],
    facets: dict[str, dict[str, Any]],
    *,
    seed_query: str,
    table_structure: dict[str, Any],
    top_n: int,
) -> list[ChunkRecord]:
    must_terms = _tokenize_query(seed_query)
    segment_terms = [str(c).lower() for c in (table_structure.get("columns") or [])[1:] if str(c).strip()]
    scored: list[tuple[float, ChunkRecord]] = []
    for chunk in chunks:
        facet = facets.get(chunk.chunk_id, {})
        score = 0.0
        summary = facet.get("summary") or ""
        text_blob = " ".join(
            [
                " ".join(str(v) for v in facet.get("segments", [])),
                " ".join(str(v) for v in facet.get("topics", [])),
                " ".join(str(v) for v in facet.get("channels", [])),
                " ".join(str(v) for v in facet.get("numbers", [])),
                summary if isinstance(summary, str) else str(summary),
                chunk.text[:350],
            ]
        ).lower()
        if segment_terms and any(s in text_blob for s in segment_terms):
            score += 1.6
        matched = sum(1 for t in must_terms if t in text_blob)
        score += min(matched, 8) * 0.2
        if facet.get("numbers"):
            score += 0.3
        if chunk.table_flag:
            score += 0.15
        if facet.get("noise_flag"):
            score -= 1.0
        scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for score, chunk in scored[:top_n] if score > 0]


def _read_through(chunks: list[ChunkRecord], seed_query: str, max_read: int) -> list[ChunkRecord]:
    must_terms = _tokenize_query(seed_query)
    confirmed: list[ChunkRecord] = []
    for chunk in chunks[:max_read]:
        body = chunk.text.lower()
        matched = sum(1 for t in must_terms if t in body)
        if matched == 0 and not chunk.table_flag:
            continue
        if re.search(r"\b(template|disclaimer|confidential)\b", body):
            continue
        confirmed.append(chunk)
    return confirmed


def _fallback_context(file_ids: list[str], query: str, top_k: int) -> str:
    """BM25 fallback with per-doc cap so multiple files contribute to context."""
    all_chunks: list[ChunkRecord] = []
    for fid in file_ids:
        all_chunks.extend(_chunk_store.get(fid, []))
    top = bm25_retrieve_records(all_chunks, query, top_k=top_k * 2)  # over-fetch for diversity
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
    Execute seed->multi-query->hybrid->lazy facet->gating->read-through->compression->judge.
    Degrades to BM25-only context on failures.
    """
    start = time.perf_counter()
    metrics: dict[str, Any] = {"seed_query_len": len(seed_query or "")}
    try:
        with stage_scope("evidence_sub_query_build"):
            step_start = time.perf_counter()
            logger.info("Evidence pipeline: building sub queries for seed query=%s module=%s table_structure=%s", seed_query, module, table_structure)
            sub_queries = _build_sub_queries(seed_query, module, table_structure)
            metrics["sub_queries"] = len(sub_queries)
            metrics["sub_query_ms"] = int((time.perf_counter() - step_start) * 1000)

        with stage_scope("evidence_retrieval_hybrid"):
            all_chunks: list[ChunkRecord] = []
            for fid in file_ids:
                all_chunks.extend(_chunk_store.get(fid, []))
            metrics["initial_candidates"] = len(all_chunks)
            candidates = hybrid_retrieve(
                all_chunks,
                [seed_query] + sub_queries,
                max_candidates=config.max_candidates,
                index_store=_embedding_store,
            )
            filtered = _cheap_filter(candidates)
            metrics["filtered_candidates"] = len(filtered)

        with stage_scope("evidence_facet_extraction"):
            facets: dict[str, dict[str, Any]] = {}
            hit = 0
            miss = 0
            generated = 0
            batch_calls = 0
            uncached: list[ChunkRecord] = []
            for chunk in filtered:
                cached = _cache.get(chunk.chunk_id)
                if cached is not None:
                    facets[chunk.chunk_id] = cached
                    hit += 1
                    continue
                miss += 1
                if generated < config.max_facet_new_per_request:
                    uncached.append(chunk)
                    generated += 1

            def _fallback_facet(chunk: ChunkRecord) -> dict[str, Any]:
                return {
                    "segments": chunk.segment_hint,
                    "topics": [],
                    "channels": [],
                    "numbers": [],
                    "summary": "",
                    "noise_flag": chunk.noise_flag,
                }

            batch_size = max(1, config.facet_batch_size)
            batches = [
                uncached[i : i + batch_size]
                for i in range(0, len(uncached), batch_size)
                if uncached[i : i + batch_size]
            ]
            batch_calls = len(batches)
            worker_count = min(max(1, config.facet_async_workers), batch_calls or 1)
            metrics["facet_async_workers"] = worker_count

            if batch_calls > 0 and worker_count > 1:
                # Run LLM facet extraction concurrently, then update cache serially
                # to avoid race conditions in JSONL append writes.
                # Copy the current context per batch so ContextVar values (run_scope, stage_scope)
                # are visible inside each worker; each Context can only be entered in one thread.
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    future_to_batch = {
                        executor.submit(contextvars.copy_context().run, extract_facets_batch, batch): batch
                        for batch in batches
                    }
                    for future in as_completed(future_to_batch):
                        batch = future_to_batch[future]
                        batch_facets = future.result()
                        for chunk in batch:
                            facet = batch_facets.get(chunk.chunk_id) or _fallback_facet(chunk)
                            _cache.set(chunk.chunk_id, facet)
                            facets[chunk.chunk_id] = facet
            else:
                for batch in batches:
                    batch_facets = extract_facets_batch(batch)
                    for chunk in batch:
                        facet = batch_facets.get(chunk.chunk_id) or _fallback_facet(chunk)
                        _cache.set(chunk.chunk_id, facet)
                        facets[chunk.chunk_id] = facet
            metrics["facet_cache_hit"] = hit
            metrics["facet_cache_miss"] = miss
            metrics["facet_new_generated"] = len(uncached)
            metrics["facet_batch_calls"] = batch_calls
            metrics["facet_budget_capped"] = miss > config.max_facet_new_per_request

        with stage_scope("evidence_facet_gating"):
            top_for_read = _facet_gate(
                filtered,
                facets,
                seed_query=seed_query,
                table_structure=table_structure,
                top_n=min(max(config.max_chunks_agent_read, 10), 20),
            )
            metrics["gating_kept"] = len(top_for_read)

        with stage_scope("evidence_agent_read"):
            if not top_for_read and config.max_iterations_expand > 0:
                # One controlled expansion.
                top_for_read = filtered[: min(len(filtered), config.max_chunks_agent_read)]
                metrics["gating_expanded_once"] = True
            else:
                metrics["gating_expanded_once"] = False

            confirmed = _read_through(top_for_read, seed_query, config.max_chunks_agent_read)
            metrics["agent_read_count"] = min(len(top_for_read), config.max_chunks_agent_read)
            metrics["confirmed_chunks"] = len(confirmed)

        with stage_scope("evidence_compress_and_judge"):
            snippets: list[dict[str, Any]] = []
            # SWOT: use column names as guide, not row indexes
            is_swot = (module or "").strip().lower() == "swot analysis"
            if is_swot:
                row_defs = [str(v) for v in (table_structure.get("columns") or []) if str(v).strip()]
                segment_terms = [str(v) for v in row_defs]
            else:
                row_defs = [str(v) for v in (table_structure.get("indexes") or [])]
                segment_terms = [str(v) for v in (table_structure.get("columns") or [])[1:]]
            reject_details: list[str] = []
            for chunk in confirmed[: config.max_to_compress]:
                compressed = compress_chunk(
                    chunk,
                    question=seed_query,
                    row_definition="; ".join(row_defs),
                    max_snippets=3,
                )
                for snippet in compressed:
                    accepted, reason = judge_snippet(
                        snippet,
                        row_definition="; ".join(row_defs),
                        segment_terms=segment_terms,
                    )
                    if accepted:
                        snippets.append(snippet)
                    elif len(reject_details) < 20:
                        reject_details.append(f"{snippet.get('chunk_id')}:{reason}")

            metrics["compression_snippets"] = len(snippets)
            metrics["judge_accept"] = len(snippets)
            metrics["judge_reject"] = len(reject_details)
            if reject_details:
                logger.debug("Evidence reject reasons top20=%s", reject_details)

        if not snippets:
            # Controlled degrade path keeps service availability.
            with stage_scope("evidence_fallback_context"):
                fallback = _fallback_context(file_ids, seed_query, top_k=top_k_fallback)
            metrics["degraded"] = True
            metrics["total_ms"] = int((time.perf_counter() - start) * 1000)
            logger.info("Evidence pipeline degraded metrics=%s", metrics)
            return EvidencePipelineResult(
                context_text=fallback,
                snippets=[],
                metrics=metrics,
                degraded=True,
            )

        context_text = "\n\n".join(
            f"[evidence:{idx + 1}] {item['text']} (source={item['chunk_id']}, meta={item.get('metadata')})"
            for idx, item in enumerate(snippets)
        )
        # Track doc diversity: chunk_id format is doc_id:hex
        unique_docs_in_result = len({s["chunk_id"].split(":")[0] for s in snippets})
        metrics["unique_docs_in_result"] = unique_docs_in_result
        metrics["degraded"] = False
        metrics["total_ms"] = int((time.perf_counter() - start) * 1000)
        logger.info(
            "Evidence pipeline done metrics=%s unique_docs_in_result=%d",
            metrics,
            unique_docs_in_result,
        )
        return EvidencePipelineResult(
            context_text=context_text,
            snippets=snippets,
            metrics=metrics,
            degraded=False,
        )
    except Exception as exc:
        metrics["degraded"] = True
        metrics["error"] = str(exc)
        metrics["total_ms"] = int((time.perf_counter() - start) * 1000)
        logger.warning("Evidence pipeline failed, fallback to BM25 err=%s metrics=%s", exc, metrics)
        with stage_scope("evidence_fallback_context"):
            fallback = _fallback_context(file_ids, seed_query, top_k=top_k_fallback)
        return EvidencePipelineResult(
            context_text=fallback,
            snippets=[],
            metrics=metrics,
            degraded=True,
        )
