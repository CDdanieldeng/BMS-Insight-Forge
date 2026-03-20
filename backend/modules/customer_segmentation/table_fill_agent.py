"""Table fill agent for Customer Segmentation.

Wraps CustomerSegmentationAgent: per-cell retrieval and table fill for slide 1.
Segment column names must be supplied by the orchestrator (cowork or cache).
"""

from __future__ import annotations

from typing import Any

from modules.customer_segmentation.agent import CustomerSegmentationAgent


class CustomerSegmentationTableFillAgent:
    """Table fill agent for CS module with placeholder columns."""

    def __init__(self) -> None:
        self._agent = CustomerSegmentationAgent()

    def run(
        self,
        *,
        file_ids: list[str],
        n_segments: int,
        indexes: list[str],
        module: str,
        trace_capture: dict[str, Any] | None = None,
        cowork_guidance: dict[str, Any] | None = None,
        segment_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run per-cell retrieval + table generation (segment names from cowork or cache)."""
        return self._agent.run(
            file_ids=file_ids,
            n_segments=n_segments,
            indexes=indexes,
            module=module,
            trace_capture=trace_capture,
            cowork_guidance=cowork_guidance,
            segment_names=segment_names,
        )
