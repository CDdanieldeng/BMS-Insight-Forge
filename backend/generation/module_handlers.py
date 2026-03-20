"""
Module-specific context merge and table postprocessing.

Isolates logic for Messaging Strategy slide 3 and SWOT from the orchestrator.
"""

from typing import Any

from generation.session_cache import (
    build_prior_table_primary_context,
    extract_prioritized_segments_from_customer_segmentation,
)
from generation.utils import normalize_label

# Row indexes that identify Messaging Strategy slide 3.
MESSAGING_STRATEGY_SLIDE3_INDEXES = [
    "target/prioritized segment",
    "drivers/barriers",
    "desired behavior change",
    "differentiated competitive benefit",
    "reason to believe",
    "business objective",
]


def is_messaging_strategy_slide3(module: str, indexes: list[str]) -> bool:
    """Return True if this is Messaging Strategy slide 3 (specific row layout)."""
    if normalize_label(module) != "messaging strategy":
        return False
    return [normalize_label(i) for i in indexes] == [
        normalize_label(i) for i in MESSAGING_STRATEGY_SLIDE3_INDEXES
    ]


def merge_context_messaging_strategy_slide3(
    slide_idx: int,
    uploaded_content: str,
) -> str:
    """Merge prior CS tables with uploaded materials for MS slide 3."""
    prior_table_context = build_prior_table_primary_context(slide_idx)
    if prior_table_context:
        return (
            "PRIMARY INPUT: PREVIOUS CUSTOMER SEGMENTATION TABLES\n"
            f"{prior_table_context}\n\n"
            "SECONDARY INPUT: UPLOADED MATERIALS\n"
            f"{uploaded_content}"
        )
    return (
        "PRIMARY INPUT: PREVIOUS CUSTOMER SEGMENTATION TABLES\n"
        "(none)\n\n"
        "SECONDARY INPUT: UPLOADED MATERIALS\n"
        f"{uploaded_content}"
    )


def merge_context_swot(slide_idx: int, uploaded_content: str) -> str:
    """Merge prior CS tables with uploaded market/competitor docs for SWOT."""
    prior_table_context = build_prior_table_primary_context(slide_idx)
    if prior_table_context:
        return (
            "PRIMARY INPUT: CUSTOMER SEGMENTATION (prior slides)\n"
            f"{prior_table_context}\n\n"
            "SECONDARY INPUT: UPLOADED MARKET DEFINITION & COMPETITOR ANALYSIS\n"
            f"{uploaded_content}"
        )
    return (
        "PRIMARY INPUT: CUSTOMER SEGMENTATION\n"
        "(none — fill CS slides first for best results)\n\n"
        "SECONDARY INPUT: UPLOADED MARKET DEFINITION & COMPETITOR ANALYSIS\n"
        f"{uploaded_content}"
    )


def merge_context_for_slide(
    module: str,
    slide_idx: int,
    indexes: list[str],
    uploaded_content: str,
) -> str:
    """
    Merge prior table context with uploaded content for slides that need it.
    Handles Messaging Strategy slide 3 and SWOT. Returns uploaded_content
    unchanged for other modules.
    """
    if is_messaging_strategy_slide3(module, indexes):
        return merge_context_messaging_strategy_slide3(slide_idx, uploaded_content)
    if normalize_label(module) == "swot analysis":
        return merge_context_swot(slide_idx, uploaded_content)
    return uploaded_content


def postprocess_table_for_slide(
    module: str,
    slide_idx: int,
    table_data: list[list[str]],
    indexes: list[str],
) -> list[list[str]]:
    """
    Apply module-specific postprocessing to table_data.
    Currently only Messaging Strategy slide 3 has special handling.
    """
    if is_messaging_strategy_slide3(module, indexes):
        return postprocess_messaging_strategy_slide3(slide_idx, table_data, indexes)
    return table_data


def postprocess_messaging_strategy_slide3(
    slide_idx: int,
    table_data: list[list[str]],
    indexes: list[str],
) -> list[list[str]]:
    """
    Force row 'target/prioritized segment' to use prioritized segments from CS.
    Returns modified table_data (mutates in place but returns for clarity).
    """
    prioritized_segments = extract_prioritized_segments_from_customer_segmentation(
        slide_idx
    )
    normalized_indexes = [normalize_label(i) for i in indexes]
    if "target/prioritized segment" not in normalized_indexes or not table_data:
        return table_data
    target_row_idx = normalized_indexes.index("target/prioritized segment")
    if target_row_idx >= len(table_data):
        return table_data
    col_count = len(table_data[target_row_idx])
    if col_count <= 0:
        return table_data
    if prioritized_segments:
        table_data[target_row_idx] = [
            prioritized_segments[i % len(prioritized_segments)]
            for i in range(col_count)
        ]
    return table_data
