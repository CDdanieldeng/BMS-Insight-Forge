"""Markdown parser/chunker for unified retrieval chunks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from retriever.models import ChunkRecord
from retriever.parsers.normalize import (
    dedupe_lines,
    estimate_tokens,
    keep_short_chunk,
    normalize_whitespace,
    p0_clean_lines,
    segment_hints_from_text,
)

_MAX_CHUNK_TOKENS = 500
_MIN_CHUNK_TOKENS = 100


@dataclass(slots=True)
class _Section:
    heading_path: list[str]
    heading_title: str
    start_line: int
    end_line: int
    lines: list[str]
    table_flag: bool = False


def _split_large_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    cur: list[str] = []
    cur_tokens = 0
    for paragraph in paragraphs:
        p_tokens = estimate_tokens(paragraph)
        if cur and cur_tokens + p_tokens > _MAX_CHUNK_TOKENS:
            chunks.append("\n\n".join(cur))
            cur = [paragraph]
            cur_tokens = p_tokens
            continue
        cur.append(paragraph)
        cur_tokens += p_tokens
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks or [text.strip()]


def parse_markdown_text(
    text: str,
    *,
    doc_id: str,
    source_type: str = "pdf_md",
) -> list[ChunkRecord]:
    """Parse markdown into section chunks with location metadata."""
    normalized = dedupe_lines(normalize_whitespace(text))
    raw_lines = normalized.splitlines()

    sections: list[_Section] = []
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_start = 1
    current_heading = ""
    in_table = False
    table_buf: list[str] = []
    table_start = 0

    def flush_current(end_line: int) -> None:
        nonlocal current_lines, current_start, current_heading
        cleaned = p0_clean_lines(current_lines)
        if not cleaned:
            current_lines = []
            return
        sections.append(
            _Section(
                heading_path=list(heading_stack),
                heading_title=current_heading or (heading_stack[-1] if heading_stack else ""),
                start_line=current_start,
                end_line=end_line,
                lines=cleaned,
                table_flag=False,
            )
        )
        current_lines = []

    for idx, line in enumerate(raw_lines, start=1):
        stripped = line.strip()

        if "|" in stripped and stripped.count("|") >= 2:
            if not in_table:
                in_table = True
                table_buf = []
                table_start = idx
            table_buf.append(stripped)
            continue
        if in_table:
            if table_buf:
                sections.append(
                    _Section(
                        heading_path=list(heading_stack),
                        heading_title=current_heading or (heading_stack[-1] if heading_stack else ""),
                        start_line=table_start,
                        end_line=idx - 1,
                        lines=p0_clean_lines(table_buf),
                        table_flag=True,
                    )
                )
            in_table = False
            table_buf = []

        if stripped.startswith("#"):
            flush_current(idx - 1)
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            while len(heading_stack) >= level:
                heading_stack.pop()
            heading_stack.append(title)
            current_heading = title
            current_start = idx + 1
            continue

        if not current_lines:
            current_start = idx
        current_lines.append(line)

    if in_table and table_buf:
        sections.append(
            _Section(
                heading_path=list(heading_stack),
                heading_title=current_heading or (heading_stack[-1] if heading_stack else ""),
                start_line=table_start,
                end_line=len(raw_lines),
                lines=p0_clean_lines(table_buf),
                table_flag=True,
            )
        )
    flush_current(len(raw_lines))

    chunks: list[ChunkRecord] = []
    for section in sections:
        section_text = normalize_whitespace("\n".join(section.lines))
        if not section_text:
            continue
        piece_list = (
            [section_text]
            if estimate_tokens(section_text) <= _MAX_CHUNK_TOKENS
            else _split_large_text(section_text)
        )
        for part_idx, piece in enumerate(piece_list):
            token_length = estimate_tokens(piece)
            if token_length < _MIN_CHUNK_TOKENS and not keep_short_chunk(piece, section.table_flag):
                continue
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{doc_id}:{uuid.uuid4().hex[:8]}",
                    doc_id=doc_id,
                    source_type=source_type,
                    text=piece,
                    token_length=token_length,
                    metadata={
                        "heading_path": section.heading_path,
                        "heading_title": section.heading_title,
                        "section_title": section.heading_title,
                        "line_range": [section.start_line, section.end_line],
                        "part_index": part_idx,
                    },
                    table_flag=section.table_flag,
                    segment_hint=segment_hints_from_text(piece),
                    noise_flag=False,
                )
            )
    return chunks
