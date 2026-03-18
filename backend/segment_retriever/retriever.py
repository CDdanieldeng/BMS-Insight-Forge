"""Orchestrate segment retrieval pipeline: query -> chunk -> embed -> similarity."""

from __future__ import annotations

from segment_retriever.chunker import chunk_text
from segment_retriever.embedding_store import similarity_search
from segment_retriever.query_generator import methodology_to_query


def retrieve(
    methodology: str,
    content: str,
    *,
    max_context_chars: int = 12000,
    top_k: int = 25,
) -> str:
    """
    Retrieve context for segment synthesis, guided by methodology.

    Args:
        methodology: Cowork summary (segmentation methodology guide)
        content: Full markdown text from uploaded documents
        max_context_chars: Maximum characters in returned context
        top_k: Maximum chunks to retrieve

    Returns:
        Formatted context string for synthesize_with_methodology prompt
    """
    if not content or not content.strip():
        return ""

    chunks = chunk_text(content)
    if not chunks:
        return ""

    if len(chunks) == 1:
        text = chunks[0]
        return text[:max_context_chars] + (
            "\n\n[Content truncated to fit context.]" if len(text) > max_context_chars else ""
        )

    query = methodology_to_query(methodology)
    top = similarity_search(query=query, chunks=chunks, top_k=top_k)

    if not top:
        return content[:max_context_chars] + (
            "\n\n[Content truncated to fit context.]" if len(content) > max_context_chars else ""
        )

    parts = [text for text, _ in top]
    combined = "\n\n---\n\n".join(parts)

    if len(combined) <= max_context_chars:
        return combined

    out: list[str] = []
    remaining = max_context_chars
    for part in parts:
        if remaining <= 50:
            break
        if len(part) <= remaining:
            out.append(part)
            remaining -= len(part) + 4  # separator overhead
        else:
            out.append(part[: remaining - 30] + "\n...[truncated]")
            break
    return "\n\n---\n\n".join(out) + "\n\n[Content truncated to fit context.]"
