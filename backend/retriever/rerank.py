"""
Rerank: score and reorder recall candidates for relevance.

Uses gte-rerank-v2 from Alicloud DashScope as API service.
"""

from __future__ import annotations

import os
from http import HTTPStatus
from typing import Any

import dashscope


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """
    Rerank candidate chunks by relevance to the query using Alicloud gte-rerank-v2.

    Args:
        query: User query or search intent.
        candidates: Chunks from recall step (each has "text" and optional metadata).
        top_k: Number of top results to return after reranking.

    Returns:
        Reordered subset of candidates with added "rerank_score".
        Falls back to candidates[:top_k] if API key is missing or API fails.
    """
    if not candidates:
        return []

    api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
    if not api_key:
        return candidates[:top_k]

    documents = [c.get("text", "") or "" for c in candidates]

    dashscope.api_key = api_key
    resp = dashscope.TextReRank.call(
        model="gte-rerank-v2",
        query=query,
        documents=documents,
        top_n=min(top_k, len(candidates)),
        return_documents=False,
    )

    if resp.status_code != HTTPStatus.OK or not getattr(resp, "output", None):
        return candidates[:top_k]

    results = resp.output.get("results") or []
    ordered: list[dict[str, Any]] = []
    for r in results:
        idx = r.get("index", -1)
        score = r.get("relevance_score", 0.0)
        if 0 <= idx < len(candidates):
            ordered.append({**candidates[idx], "rerank_score": score})

    return ordered


if __name__ == "__main__":
    # cd backend && python -m retriever.rerank
    # Requires DASHSCOPE_API_KEY or QWEN_API_KEY for actual API call.
    candidates = [
        {"text": "文本排序模型广泛用于搜索引擎和推荐系统中", "file_id": "f1"},
        {"text": "量子计算是计算科学的一个前沿领域", "file_id": "f2"},
        {"text": "预训练语言模型的发展给文本排序模型带来了新的进展", "file_id": "f1"},
    ]
    query = "什么是文本排序模型"

    api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
    if not api_key:
        print("Skip: DASHSCOPE_API_KEY or QWEN_API_KEY not set")
        print("Pass-through rerank (no API):", rerank(query, candidates, top_k=2))
    else:
        out = rerank(query, candidates, top_k=2)
        print("Reranked results:", out)
        assert len(out) <= 2
        assert all("rerank_score" in r for r in out)
        assert out[0]["rerank_score"] >= out[-1]["rerank_score"] if len(out) > 1 else True
        print("rerank test passed")
