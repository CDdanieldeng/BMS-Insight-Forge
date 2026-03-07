"""Document-level facet extraction.

Called once per file at upload time. Generates a doc facet card containing:
  - maturity:       "totally_raw" | "semi_raw" | "mature"
  - segment_names:  extracted HCP segment names (mature files only)
  - filename:       original file name

Uses the same LLM client as the rest of the generation pipeline.
For very large documents a representative sample is used to keep token cost low.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from shared.logging_config import setup_logging
from generation.llm_client import complete

logger = setup_logging("generation")

# Sample the first + middle portion of the document for classification.
# This is enough to detect structure/maturity signals without reading everything.
_CLASSIFY_MAX_CHARS = 12_000
# Segment extraction reads a bit more since segment names can appear deeper in
# mature documents.
_EXTRACT_MAX_CHARS = 20_000


def _sample_content(text: str, max_chars: int) -> str:
    """Return a representative sample of the document."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n[... middle section omitted ...]\n\n" + text[-half:]


_CLASSIFY_SYSTEM = """\
You are a document analyst for pharmaceutical commercial strategy.

Classify the uploaded materials into EXACTLY one of three categories:

- "totally_raw": contains only raw research data — e.g. interview transcripts,
  observational notes, survey verbatims — with no prior human analysis.
- "semi_raw": contains some human analysis or summary commentary but does NOT
  clearly identify named HCP customer segments.
- "mature": contains completed human analysis that explicitly names and describes
  distinct HCP customer segments.

Return ONLY valid JSON with no markdown:
{"maturity": "totally_raw"|"semi_raw"|"mature", "reasoning": "<one sentence>"}"""

_CLASSIFY_USER = """\
Document sample:
{content}

Classify the maturity now:"""


_EXTRACT_SYSTEM = """\
You are a pharmaceutical commercial strategy analyst.

The uploaded document contains completed HCP customer segment analysis.
Extract the segment names EXACTLY as they appear in the document — do not rename,
merge, or invent new ones.

Rules:
- HCPs only: physicians, specialists, prescribers, clinical decision makers.
- No payers, regulators, procurement, government, or patients.
- Names must be concise (< 6 words each).
- Return between 2 and 6 names.

Return ONLY a valid JSON flat array of segment name strings.
No markdown, no explanation."""

_EXTRACT_USER = """\
Document sample:
{content}

Extract the HCP segment names now:"""


def extract_document_facet(
    file_id: str,
    md_text: str,
    filename: str = "",
) -> dict[str, Any]:
    """
    Generate a document-level facet card for a single uploaded file.

    Performs at most 2 LLM calls:
    1. Classify maturity (always)
    2. Extract segment names (only if mature)

    Returns a facet dict ready to store in DocumentFacetCache.
    """
    facet: dict[str, Any] = {
        "file_id": file_id,
        "filename": filename,
        "maturity": "totally_raw",
        "segment_names": [],
    }

    # ── Step 1: classify maturity ─────────────────────────────────────────
    classify_sample = _sample_content(md_text, _CLASSIFY_MAX_CHARS)
    raw_classify = ""
    try:
        start = time.perf_counter()
        raw_classify = complete(
            _CLASSIFY_SYSTEM,
            _CLASSIFY_USER.format(content=classify_sample),
            max_tokens=200,
        ).strip()

        cleaned = raw_classify
        if "```" in cleaned:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
            if m:
                cleaned = m.group(1)

        parsed = json.loads(cleaned)
        maturity = str(parsed.get("maturity", "")).strip().lower()
        if maturity not in {"totally_raw", "semi_raw", "mature"}:
            logger.warning(
                "Doc facet: unexpected maturity '%s' for file_id=%s, defaulting to semi_raw",
                maturity,
                file_id,
            )
            maturity = "semi_raw"

        facet["maturity"] = maturity
        logger.info(
            "Doc facet classify done file_id=%s filename=%s maturity=%s reasoning=%s elapsed_ms=%d",
            file_id,
            filename,
            maturity,
            str(parsed.get("reasoning", ""))[:200],
            int((time.perf_counter() - start) * 1000),
        )
    except Exception as exc:
        logger.warning(
            "Doc facet classify failed file_id=%s filename=%s err=%s raw=%s",
            file_id,
            filename,
            exc,
            raw_classify[:300],
        )
        # Default to semi_raw so the CS agent synthesizes rather than blindly
        # tries to extract from a potentially raw file.
        facet["maturity"] = "semi_raw"

    # ── Step 2: extract segment names (mature only) ───────────────────────
    if facet["maturity"] == "mature":
        extract_sample = _sample_content(md_text, _EXTRACT_MAX_CHARS)
        raw_extract = ""
        try:
            start = time.perf_counter()
            raw_extract = complete(
                _EXTRACT_SYSTEM,
                _EXTRACT_USER.format(content=extract_sample),
                max_tokens=300,
            ).strip()

            cleaned = raw_extract
            if "```" in cleaned:
                m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
                if m:
                    cleaned = m.group(1)

            names = json.loads(cleaned)
            if not isinstance(names, list):
                raise ValueError("Expected a JSON list")

            names = [str(n).strip() for n in names if str(n).strip()]
            facet["segment_names"] = names
            logger.info(
                "Doc facet extract done file_id=%s filename=%s segments=%s elapsed_ms=%d",
                file_id,
                filename,
                names,
                int((time.perf_counter() - start) * 1000),
            )
        except Exception as exc:
            logger.warning(
                "Doc facet segment extraction failed file_id=%s filename=%s err=%s raw=%s",
                file_id,
                filename,
                exc,
                raw_extract[:300],
            )
            # If extraction fails for a mature file, downgrade to semi_raw so the
            # agent synthesizes rather than returning an empty segment list.
            facet["maturity"] = "semi_raw"
            facet["segment_names"] = []

    return facet
