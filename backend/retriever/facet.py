"""
Document facet classification: roughly determine file type for routing.

Used to select appropriate chunking and retrieval strategies per document.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import TypedDict

from shared.llm_client import complete

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


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

# Approximate chars per page for token-saving truncation
_CHARS_PER_PAGE = 2000
_NUM_PAGES_FOR_FACET = 2


class FacetExtractionResult(TypedDict):
    """Result of LLM facet extraction."""

    file_type: str
    summary: str


def _truncate_to_first_pages(content: str, n_pages: int = _NUM_PAGES_FOR_FACET) -> str:
    """Keep only the first n pages of content to save tokens."""
    max_chars = n_pages * _CHARS_PER_PAGE
    if len(content) <= max_chars:
        return content
    logger.debug(
        "Truncated content for facet extraction orig_len=%d max_chars=%d",
        len(content),
        max_chars,
    )
    return content[:max_chars]


def classify_document_facet(
    content: str,
    filename: str = "",
) -> FacetExtractionResult:
    """
    Classify a document into one of the supported facets and extract a summary.

    Uses Qwen Turbo for extraction. Only the first two pages are sent to save tokens.

    Args:
        content: Raw text or markdown content of the document.
        filename: Optional filename for extension-based hints.

    Returns:
        Dict with "file_type" (e.g. "transcript") and "summary" (brief summary).
    """
    truncated = _truncate_to_first_pages(content)
    logger.info(
        "Classifying document facet filename=%s content_chars=%d truncated_chars=%d",
        filename or "(unnamed)",
        len(content),
        len(truncated),
    )
    facet_list = ", ".join(FACET_VALUES)

    system_prompt = (
        "You are a document classifier. Analyze the given document excerpt and respond with a JSON object only, no other text. "
        f"Set 'file_type' to exactly one of: {facet_list}. "
        "Set 'summary' to a brief 1–2 sentence summary of the document content. "
        "Respond with valid JSON only."
    )
    user_prompt = f"Document excerpt:\n\n{truncated}"

    try:
        raw = complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=512,
            provider_override="qwen",
            model_override="qwen-turbo",
            response_format={"type": "json_object"},
        )
        # Handle markdown code blocks if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        parsed = json.loads(text)
        file_type = str(parsed.get("file_type", "others")).strip().lower()
        summary = str(parsed.get("summary", "")).strip()
        # Normalize to known facet
        if file_type not in FACET_VALUES:
            logger.warning(
                "Unknown file_type from LLM, normalizing to others file_type=%s filename=%s",
                file_type,
                filename or "(unnamed)",
            )
            file_type = "others"
        result = {"file_type": file_type, "summary": summary}
        logger.info(
            "Facet extraction complete file_type=%s summary_len=%d filename=%s",
            file_type,
            len(summary),
            filename or "(unnamed)",
        )
        return result
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(
            "Facet extraction failed, falling back to others filename=%s err=%s",
            filename or "(unnamed)",
            e,
        )
        return {"file_type": "others", "summary": f"(extraction failed: {e})"}



if __name__ == "__main__":
    sample = """
    Interview Transcript - Sales Call
    ---
    Moderator: Can you describe your typical customer?
    Respondent: We focus on mid-sized hospitals in tier-2 cities...
    """
    result = classify_document_facet(sample)
    print(result)  