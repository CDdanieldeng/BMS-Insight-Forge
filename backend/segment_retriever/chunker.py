"""Split raw markdown into chunks for embedding. Structure-aware."""

from __future__ import annotations

import re


def chunk_text(text: str, max_chars: int = 500) -> list[str]:
    """
    Split markdown into chunks for embedding.

    Splits on document separators (---) and headings (##, ###) first, then
    by paragraphs up to max_chars. Merges small fragments.
    """
    if not text or not text.strip():
        return []

    raw = (text or "").strip()
    # First split: document separators
    doc_parts = re.split(r"\n\n---+\n\n", raw)
    chunks: list[str] = []
    min_chunk_chars = 80

    for doc_part in doc_parts:
        doc_part = doc_part.strip()
        if not doc_part:
            continue
        # Second split: heading boundaries (## or ### at line start)
        section_parts = re.split(r"(?=\n#{2,3}\s+)", doc_part)
        section_parts = [p.strip() for p in section_parts if p.strip()]

        for section in section_parts:
            if len(section) <= max_chars:
                if len(section) >= min_chunk_chars or not chunks:
                    chunks.append(section)
                else:
                    merged = chunks[-1] + "\n\n" + section
                    if len(merged) <= max_chars * 1.5:
                        chunks[-1] = merged
                    else:
                        chunks.append(section)
            else:
                # Split by paragraph boundaries
                paras = re.split(r"\n\n+", section)
                cur: list[str] = []
                cur_len = 0
                for p in paras:
                    p = p.strip()
                    if not p:
                        continue
                    if cur_len + len(p) + 2 <= max_chars:
                        cur.append(p)
                        cur_len += len(p) + 2
                    else:
                        if cur:
                            joined = "\n\n".join(cur)
                            if len(joined) >= min_chunk_chars:
                                chunks.append(joined)
                        if len(p) > max_chars:
                            # Break long paragraph by sentences
                            sents = re.split(r"(?<=[.!?。！？])\s+", p)
                            cur = []
                            cur_len = 0
                            for s in sents:
                                if cur_len + len(s) + 1 <= max_chars:
                                    cur.append(s)
                                    cur_len += len(s) + 1
                                else:
                                    if cur:
                                        chunks.append(" ".join(cur))
                                    cur = [s] if len(s) < max_chars else [s[:max_chars]]
                                    cur_len = len(cur[-1])
                        else:
                            cur = [p]
                            cur_len = len(p)
                if cur:
                    joined = "\n\n".join(cur)
                    if len(joined) >= min_chunk_chars or not chunks:
                        chunks.append(joined)

    return [c.strip() for c in chunks if c.strip()]
