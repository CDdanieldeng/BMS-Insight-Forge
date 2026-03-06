"""Facet extraction for candidate gating."""

from __future__ import annotations

import json
import re
from typing import Any

from generation.llm_client import complete
from retriever.models import ChunkRecord

_CHANNEL_TERMS = ["wechat", "weixin", "journal", "publication", "conference", "congress", "rep"]
_TOPIC_TERMS = ["preferences", "environment", "channels", "demographics", "volume"]


def _rule_facet(chunk: ChunkRecord) -> dict[str, Any]:
    text = (chunk.text or "").lower()
    numbers = re.findall(
        r"\b\d+(?:\.\d+)?\s*(?:%|patients?|patient|per month|monthly|yearly|times?)\b",
        text,
        flags=re.IGNORECASE,
    )
    return {
        "segments": chunk.segment_hint,
        "topics": [t for t in _TOPIC_TERMS if t in text],
        "channels": [c for c in _CHANNEL_TERMS if c in text],
        "numbers": numbers[:5],
        "noise_flag": chunk.noise_flag,
    }


def _normalize_facet(data: dict[str, Any], chunk: ChunkRecord) -> dict[str, Any]:
    normalized = dict(data or {})
    normalized.setdefault("segments", chunk.segment_hint)
    normalized.setdefault("topics", [])
    normalized.setdefault("channels", [])
    normalized.setdefault("numbers", [])
    normalized.setdefault("noise_flag", chunk.noise_flag)
    return normalized


def extract_facet(chunk: ChunkRecord) -> dict[str, Any]:
    """Generate short facet signals; falls back to rules on failure."""
    system = (
        "Extract retrieval facets from text.\n"
        "Return JSON with keys: segments, topics, channels, numbers, noise_flag.\n"
        "numbers must preserve unit/qualifier when present.\n"
        "Output JSON only."
    )
    user = (
        "Chunk text:\n"
        f"{chunk.text[:2600]}\n\n"
        "Return format example:\n"
        '{"segments":["safe player"],"topics":["preferences"],"channels":["wechat"],'
        '"numbers":["34 moderate-to-severe patients per month"],"noise_flag":false}'
    )
    try:
        raw = complete(system, user, max_tokens=260)
        payload = raw.strip()
        if "```" in payload:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", payload)
            if m:
                payload = m.group(1).strip()
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("facet payload not dict")
        return _normalize_facet(data, chunk)
    except Exception:
        return _rule_facet(chunk)


def extract_facets_batch(chunks: list[ChunkRecord]) -> dict[str, dict[str, Any]]:
    """
    Batch facet extraction for multiple chunks in one LLM call.
    Falls back to rule facets per chunk on parse/API failure.
    """
    if not chunks:
        return {}
    system = (
        "Extract retrieval facets for each chunk.\n"
        "Return ONLY a JSON array. Each item must be:\n"
        '{"chunk_id":"...", "segments":[], "topics":[], "channels":[], "numbers":[], "noise_flag":false}\n'
        "numbers must preserve unit/qualifier when present."
    )
    block_list: list[str] = []
    for chunk in chunks:
        block_list.append(
            f"chunk_id={chunk.chunk_id}\ntext:\n{chunk.text[:1400]}"
        )
    user = "Chunks:\n\n" + "\n\n---\n\n".join(block_list)

    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    try:
        raw = complete(system, user, max_tokens=min(2800, 220 * len(chunks)))
        payload = raw.strip()
        if "```" in payload:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", payload)
            if m:
                payload = m.group(1).strip()
        data = json.loads(payload)
        if not isinstance(data, list):
            raise ValueError("batch facet payload not list")

        result: dict[str, dict[str, Any]] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("chunk_id", "")).strip()
            if not cid or cid not in by_id:
                continue
            result[cid] = _normalize_facet(item, by_id[cid])

        # Fill any missing ids with rule fallback.
        for chunk in chunks:
            if chunk.chunk_id not in result:
                result[chunk.chunk_id] = _rule_facet(chunk)
        return result
    except Exception:
        return {chunk.chunk_id: _rule_facet(chunk) for chunk in chunks}
