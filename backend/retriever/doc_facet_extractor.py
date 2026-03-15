"""Document-level facet extraction.

Called once per file at upload time. Generates a doc facet card containing:
  - maturity:       "totally_raw" | "semi_raw" | "mature"
  - topic:          "customer segmentation" | "messaging strategy" | "others"
  - summary:        one short sentence summarizing the document
  - filename:       original file name

Uses the shared LLM client. For very large documents a representative sample
is used to keep token cost low.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from shared.logging_config import setup_logging
from shared.llm_client import complete
from generation.stage_metrics import run_scope, stage_scope

logger = setup_logging("retriever")

# Sample the first + middle portion of the document for classification.
# This is enough to detect structure/maturity signals without reading everything.
_CLASSIFY_MAX_CHARS = 12_000


def _sample_content(text: str, max_chars: int) -> str:
    """Return a representative sample of the document."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n[... middle section omitted ...]\n\n" + text[-half:]


_VALID_TOPICS = frozenset({"customer segmentation", "messaging strategy", "others"})

_CLASSIFY_SYSTEM = """\
You are a document analyst for pharmaceutical commercial strategy.

Classify the uploaded materials:

1) maturity — EXACTLY one of:
- "totally_raw": contains only raw research data — e.g. interview transcripts,
  observational notes, survey verbatims — with no prior human analysis.
- "semi_raw": contains some human analysis or summary commentary but does NOT
  clearly identify named HCP customer segments.
- "mature": contains completed human analysis that explicitly names and describes
  distinct HCP customer segments.

2) topic — EXACTLY one of:
- "customer segmentation": document is about HCP/customer segments, personas, or segment analysis.
- "messaging strategy": document is about messaging, positioning, or communication strategy.
- "others": any other focus (e.g. market data, operations, general insights).

3) summary — one short sentence (under 25 words) summarizing what the document is about.

Return ONLY valid JSON with no markdown:
{"maturity": "totally_raw"|"semi_raw"|"mature", "topic": "customer segmentation"|"messaging strategy"|"others", "summary": "<one short sentence>", "reasoning": "<one sentence>"}"""

_CLASSIFY_USER = """\
Document sample:
{content}

Classify the maturity now:"""


def extract_document_facet(
    file_id: str,
    md_text: str,
    filename: str = "",
) -> dict[str, Any]:
    """
    Generate a document-level facet card for a single uploaded file.

    Performs one LLM call to classify document maturity, topic, and summary.

    Returns a facet dict ready to store in DocumentFacetCache.
    """
    with run_scope(
        operation="doc_facet_extraction",
        metadata={"file_id": file_id, "filename": filename},
    ):
        return _extract_document_facet_inner(file_id=file_id, md_text=md_text, filename=filename)


def _extract_document_facet_inner(
    file_id: str,
    md_text: str,
    filename: str,
) -> dict[str, Any]:
    facet: dict[str, Any] = {
        "file_id": file_id,
        "filename": filename,
        "maturity": "totally_raw",
        "topic": "others",
        "summary": "",
    }

    # ── Step 1: classify maturity ─────────────────────────────────────────
    classify_sample = _sample_content(md_text, _CLASSIFY_MAX_CHARS)
    raw_classify = ""
    with stage_scope("doc_facet_classify"):
        try:
            start = time.perf_counter()
            raw_classify = complete(
                _CLASSIFY_SYSTEM,
                _CLASSIFY_USER.format(content=classify_sample),
                max_tokens=350,
                model_override="qwen-turbo",
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

            topic = str(parsed.get("topic", "others")).strip().lower()
            if topic not in _VALID_TOPICS:
                logger.warning(
                    "Doc facet: unexpected topic '%s' for file_id=%s, defaulting to others",
                    topic,
                    file_id,
                )
                topic = "others"

            summary = parsed.get("summary")
            if summary is not None and not isinstance(summary, str):
                summary = str(summary)
            summary = (summary or "").strip()[:500]

            facet["maturity"] = maturity
            facet["topic"] = topic
            facet["summary"] = summary
            logger.info(
                "Doc facet classify done file_id=%s filename=%s maturity=%s topic=%s summary=%s reasoning=%s elapsed_ms=%d",
                file_id,
                filename,
                maturity,
                topic,
                summary[:80] + ("..." if len(summary) > 80 else ""),
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
            facet.setdefault("topic", "others")
            facet.setdefault("summary", "")

    return facet
