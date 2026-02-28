"""
Markdown chunker and BM25 retriever.

Splits converted markdown into paragraphs/sections then uses BM25 to
return only the most query-relevant chunks, keeping LLM context tight.
"""

import math
import re
from collections import Counter

# Chunk size bounds (characters)
_CHUNK_MAX = 500
_CHUNK_MIN = 80

# BM25 hyper-parameters (standard defaults)
_K1 = 1.5
_B = 0.75


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def split_chunks(text: str, max_chars: int = _CHUNK_MAX) -> list[str]:
    """
    Split markdown text into chunks of at most max_chars characters.

    Splits on markitdown slide separators (---) and paragraph breaks first,
    then merges tiny fragments with their neighbour, and further splits
    any oversized paragraph by sentence.
    """
    # Primary split: slide separators and blank lines
    raw = re.split(r"\n---+\n|\n{2,}", text)

    chunks: list[str] = []
    current = ""

    for piece in raw:
        piece = piece.strip()
        if not piece:
            continue

        if len(current) + len(piece) + 2 <= max_chars:
            current = (current + "\n\n" + piece).strip() if current else piece
        else:
            if current:
                chunks.append(current)

            if len(piece) > max_chars:
                # Split oversized paragraph by sentence boundary
                sentences = re.split(r"(?<=[.!?])\s+", piece)
                buf = ""
                for s in sentences:
                    if len(buf) + len(s) + 1 <= max_chars:
                        buf = (buf + " " + s).strip() if buf else s
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = s
                if buf:
                    chunks.append(buf)
                current = ""
            else:
                current = piece

    if current:
        chunks.append(current)

    # Merge very small trailing fragments into the previous chunk
    merged: list[str] = []
    for chunk in chunks:
        if merged and len(merged[-1]) < _CHUNK_MIN:
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)

    return [c for c in merged if c.strip()]


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric word tokens."""
    return re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())


def bm25_retrieve(chunks: list[str], query: str, top_k: int = 12) -> list[str]:
    """
    Return the top_k most query-relevant chunks using BM25.

    If the query is empty or none of the chunks contain any query term,
    falls back to returning the first top_k chunks so we never send nothing.
    Returned chunks preserve original document order for coherence.
    """
    if not chunks:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return chunks[:top_k]

    tokenized = [_tokenize(c) for c in chunks]
    n = len(tokenized)
    avgdl = sum(len(t) for t in tokenized) / n

    # Corpus-level IDF for each query term
    idf: dict[str, float] = {}
    for term in set(query_tokens):
        df = sum(1 for t in tokenized if term in set(t))
        idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    scores: list[float] = []
    for doc_tokens in tokenized:
        dl = len(doc_tokens)
        freq = Counter(doc_tokens)
        score = 0.0
        for term in query_tokens:
            tf = freq.get(term, 0)
            score += idf.get(term, 0.0) * (tf * (_K1 + 1)) / (
                tf + _K1 * (1 - _B + _B * dl / max(avgdl, 1))
            )
        scores.append(score)

    ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)
    top = ranked[:top_k]

    # Fallback: no keyword overlap at all
    if all(scores[i] == 0.0 for i in top):
        return chunks[:top_k]

    # Preserve original order among selected chunks
    top_ordered = sorted(top)
    return [chunks[i] for i in top_ordered]
