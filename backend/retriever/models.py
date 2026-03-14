"""Typed models for retrieval chunks and document metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ChunkRecord:
    """Unified chunk object used by parser/index/retrieval stages."""

    chunk_id: str
    doc_id: str
    source_type: str
    text: str
    token_length: int
    metadata: dict[str, Any] = field(default_factory=dict)
    table_flag: bool = False
    segment_hint: list[str] = field(default_factory=list)
    noise_flag: bool = False

    def as_text_block(self) -> str:
        """Render compact chunk text with location hint for prompt context."""
        location = []
        if "slide_number" in self.metadata:
            location.append(f"slide={self.metadata.get('slide_number')}")
        if self.metadata.get("slide_title"):
            location.append(f"title={self.metadata.get('slide_title')}")
        if self.metadata.get("heading_title"):
            location.append(f"heading={self.metadata.get('heading_title')}")
        if self.metadata.get("line_range"):
            location.append(f"lines={self.metadata.get('line_range')}")
        prefix = f"[{self.chunk_id}]"
        if location:
            prefix += f" ({', '.join(str(v) for v in location if v)})"
        return f"{prefix}\n{self.text.strip()}"
