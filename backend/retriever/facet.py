"""
Document facet classification: roughly determine file type for routing.

Used to select appropriate chunking and retrieval strategies per document.
"""

from __future__ import annotations

from enum import Enum


class DocumentFacet(str, Enum):
    """
    Rough file-type facets for retrieval pipeline routing.

    Determines chunking strategy and optional retrieval tweaks per document.
    """

    TRANSCRIPT = "transcript"
    SWOT = "swot"
    CUSTOMER_SEGMENTATION = "customer segmentation"
    MESSAGING_STRATEGY = "messaging strategy"
    OTHERS = "others"


FACET_VALUES: list[str] = [f.value for f in DocumentFacet]


def classify_document_facet(
    content: str,
    filename: str = "",
) -> DocumentFacet:
    """
    Classify a document into one of the supported facets.

    Uses heuristics (keywords, structure) or LLM for ambiguous cases.
    Override this with your implementation.

    Args:
        content: Raw text or markdown content of the document.
        filename: Optional filename for extension-based hints.

    Returns:
        DocumentFacet indicating the document type.
    """
    # TODO: Implement classification (heuristics + optional LLM fallback)
    return DocumentFacet.OTHERS
