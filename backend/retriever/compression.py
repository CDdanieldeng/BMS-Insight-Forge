"""Query-time compression into short evidence snippets."""

from __future__ import annotations

import re
from typing import Any

from retriever.models import ChunkRecord


def _sentence_split(text: str) -> list[str]:
    items = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [i.strip() for i in items if i.strip()]


def _score_sentence(sentence: str, must_terms: set[str]) -> int:
    lowered = sentence.lower()
    score = 0
    for term in must_terms:
        if term and term in lowered:
            score += 2
    if re.search(r"\d", sentence):
        score += 2
    if re.search(r"\b(per month|monthly|%|patients?|volume|moderate-to-severe)\b", lowered):
        score += 2
    return score


def compress_chunk(
    chunk: ChunkRecord,
    *,
    question: str,
    row_definition: str = "",
    max_snippets: int = 3,
) -> list[dict[str, Any]]:
    """
    Query-focused compression from chunk text.
    Returns at most 1-3 snippets with provenance.
    """
    must_terms = {
        t
        for t in re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b", f"{question} {row_definition}".lower())
        if len(t) > 2
    }
    sentences = _sentence_split(chunk.text)
    ranked = sorted(sentences, key=lambda s: _score_sentence(s, must_terms), reverse=True)
    selected: list[dict[str, Any]] = []
    for sent in ranked:
        if len(selected) >= max_snippets:
            break
        if _score_sentence(sent, must_terms) <= 0:
            continue
        selected.append(
            {
                "chunk_id": chunk.chunk_id,
                "text": sent,
                "metadata": chunk.metadata,
            }
        )
    return selected
