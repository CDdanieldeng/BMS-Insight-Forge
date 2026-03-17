"""
LangGraph workflow for evidence retrieval pipeline.

Modular nodes: query_build -> recall -> cheap_filter -> metadata_gate -> read_through
-> compress -> judge -> evidence_output.

Facet card removed: gating uses chunk metadata (segment_hint, table_flag, heading_path, etc.)
and rule-based extraction (numbers regex) instead of LLM facet extraction.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from retriever.compression import compress_chunk
from retriever.evidence_judge import judge_snippet
from retriever.models import ChunkRecord
from retriever.query_builder import build_queries

_CHANNEL_TERMS = ["wechat", "weixin", "journal", "publication", "conference", "congress", "rep"]
_TOPIC_TERMS = ["preferences", "environment", "channels", "demographics", "volume"]


class EvidenceState(TypedDict, total=False):
    """State for the evidence retrieval graph."""

    file_ids: list[str]
    module: str
    table_structure: dict[str, Any]
    seed_query: str
    config: Any
    top_k_fallback: int

    queries: list[str]
    all_chunks: list[ChunkRecord]
    candidates: list[ChunkRecord]
    filtered: list[ChunkRecord]
    facets: dict[str, dict[str, Any]]
    top_for_read: list[ChunkRecord]
    confirmed: list[ChunkRecord]
    snippets: list[dict[str, Any]]
    context_text: str
    degraded: bool

    metrics: dict[str, Any]


def _metadata_facet(chunk: ChunkRecord) -> dict[str, Any]:
    """Build facet-like dict from chunk metadata and rules. No LLM."""
    text = (chunk.text or "").lower()
    numbers = re.findall(
        r"\b\d+(?:\.\d+)?\s*(?:%|patients?|patient|per month|monthly|yearly|times?)\b",
        text,
        flags=re.IGNORECASE,
    )
    heading_text = " ".join(
        str(v) for v in chunk.metadata.get("heading_path", [])
    )
    topics = [t for t in _TOPIC_TERMS if t in text or t in heading_text]
    channels = [c for c in _CHANNEL_TERMS if c in text]
    return {
        "segments": chunk.segment_hint,
        "topics": topics,
        "channels": channels,
        "numbers": numbers[:5],
        "summary": "",
        "noise_flag": chunk.noise_flag,
    }


def _tokenize_query(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b", text or "")
        if len(t) > 2
    }


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
    segment_terms = [
        str(c).lower()
        for c in (table_structure.get("columns") or [])[1:]
        if str(c).strip()
    ]
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


def node_query_build(state: EvidenceState) -> EvidenceState:
    """Build query variants via Query Builder."""
    qs = build_queries(
        state["seed_query"],
        state["module"],
        state["table_structure"],
    )
    queries = [state["seed_query"]] + qs.extended_queries
    return {"queries": queries}


def node_recall(state: EvidenceState) -> EvidenceState:
    """Hybrid recall over file_ids scoped chunks."""
    from retriever.hybrid import hybrid_retrieve
    from retriever.router import _chunk_store, _embedding_store

    all_chunks: list[ChunkRecord] = []
    for fid in state["file_ids"]:
        all_chunks.extend(_chunk_store.get(fid, []))
    candidates = hybrid_retrieve(
        all_chunks,
        state["queries"],
        max_candidates=state["config"].max_candidates,
        index_store=_embedding_store,
    )
    return {"all_chunks": all_chunks, "candidates": candidates}


def node_cheap_filter(state: EvidenceState) -> EvidenceState:
    """Filter low-quality chunks."""
    filtered = _cheap_filter(state["candidates"])
    return {"filtered": filtered}


def node_metadata_facets(state: EvidenceState) -> EvidenceState:
    """Build facets from chunk metadata and rules. No LLM, no cache."""
    filtered = state["filtered"]
    facets = {chunk.chunk_id: _metadata_facet(chunk) for chunk in filtered}
    return {"facets": facets}


def node_facet_gate(state: EvidenceState) -> EvidenceState:
    """Gate by facet relevance, expand once if empty."""
    filtered = state["filtered"]
    config = state["config"]
    top_n = min(max(config.max_chunks_agent_read, 10), 20)
    top_for_read = _facet_gate(
        filtered,
        state["facets"],
        seed_query=state["seed_query"],
        table_structure=state["table_structure"],
        top_n=top_n,
    )
    if not top_for_read and config.max_iterations_expand > 0:
        top_for_read = filtered[: min(len(filtered), config.max_chunks_agent_read)]
    return {"top_for_read": top_for_read}


def node_read_through(state: EvidenceState) -> EvidenceState:
    """Keyword/read-through filter."""
    config = state["config"]
    confirmed = _read_through(
        state["top_for_read"],
        state["seed_query"],
        config.max_chunks_agent_read,
    )
    return {"confirmed": confirmed}


def node_compress_and_judge(state: EvidenceState) -> EvidenceState:
    """Compress chunks to snippets and judge by field type."""
    confirmed = state["confirmed"]
    config = state["config"]
    module = (state["module"] or "").strip().lower()
    table = state["table_structure"]

    is_swot = module == "swot analysis"
    if is_swot:
        row_defs = [str(v) for v in (table.get("columns") or []) if str(v).strip()]
        segment_terms = list(row_defs)
    else:
        row_defs = [str(v) for v in (table.get("indexes") or [])]
        segment_terms = [str(v) for v in (table.get("columns") or [])[1:]]

    row_def_str = "; ".join(row_defs)
    snippets: list[dict[str, Any]] = []

    for chunk in confirmed[: config.max_to_compress]:
        compressed = compress_chunk(
            chunk,
            question=state["seed_query"],
            row_definition=row_def_str,
            max_snippets=3,
        )
        for snippet in compressed:
            accepted, _ = judge_snippet(
                snippet,
                row_definition=row_def_str,
                segment_terms=segment_terms,
            )
            if accepted:
                snippets.append(snippet)

    return {"snippets": snippets}


def node_evidence_output(state: EvidenceState) -> EvidenceState:
    """Format final output. If no snippets, degrade path handled by conditional edge."""
    snippets = state.get("snippets") or []
    if snippets:
        context_text = "\n\n".join(
            f"[evidence:{idx + 1}] {item['text']} (source={item['chunk_id']}, meta={item.get('metadata')})"
            for idx, item in enumerate(snippets)
        )
        return {"context_text": context_text, "degraded": False}
    return {"context_text": "", "snippets": [], "degraded": True}


def should_fallback(state: EvidenceState) -> str:
    """Route: fallback if no snippets."""
    snippets = state.get("snippets") or []
    return "fallback" if not snippets else "output"


def node_fallback(state: EvidenceState) -> EvidenceState:
    """BM25 fallback when pipeline produces no snippets."""
    from retriever.chunker import bm25_retrieve_records
    from retriever.router import _chunk_store

    all_chunks: list[ChunkRecord] = []
    for fid in state["file_ids"]:
        all_chunks.extend(_chunk_store.get(fid, []))
    top = bm25_retrieve_records(all_chunks, state["seed_query"], top_k=state["top_k_fallback"] * 2)
    unique_docs = len({c.doc_id for c in top})
    max_per_doc = max(15, state["top_k_fallback"] // max(1, unique_docs))
    doc_counts: dict[str, int] = {}
    capped: list[ChunkRecord] = []
    for c in top:
        if len(capped) >= state["top_k_fallback"]:
            break
        n = doc_counts.get(c.doc_id, 0)
        if n >= max_per_doc:
            continue
        doc_counts[c.doc_id] = n + 1
        capped.append(c)
    context_text = "\n\n---\n\n".join(chunk.as_text_block() for chunk in capped)
    return {"context_text": context_text, "snippets": [], "degraded": True}


def build_evidence_graph():
    """Build and compile the evidence retrieval LangGraph."""
    graph = StateGraph(EvidenceState)

    graph.add_node("query_build", node_query_build)
    graph.add_node("recall", node_recall)
    graph.add_node("cheap_filter", node_cheap_filter)
    graph.add_node("metadata_facets", node_metadata_facets)
    graph.add_node("facet_gate", node_facet_gate)
    graph.add_node("read_through", node_read_through)
    graph.add_node("compress_and_judge", node_compress_and_judge)
    graph.add_node("evidence_output", node_evidence_output)
    graph.add_node("fallback", node_fallback)

    graph.set_entry_point("query_build")
    graph.add_edge("query_build", "recall")
    graph.add_edge("recall", "cheap_filter")
    graph.add_edge("cheap_filter", "metadata_facets")
    graph.add_edge("metadata_facets", "facet_gate")
    graph.add_edge("facet_gate", "read_through")
    graph.add_edge("read_through", "compress_and_judge")
    graph.add_conditional_edges("compress_and_judge", should_fallback, {"output": "evidence_output", "fallback": "fallback"})
    graph.add_edge("evidence_output", END)
    graph.add_edge("fallback", END)

    return graph.compile()
