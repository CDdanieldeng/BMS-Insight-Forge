"""
Query rewrite: convert guidance text into retrieval-optimized queries.

Provides a generic rewrite_for_retrieval() and domain-specific wrappers
(e.g. rewrite_segment_guidance for cowork segment methodology).
Designed for easy extension to new guidance types.
"""

from __future__ import annotations

from typing import Callable

from shared.logging_config import setup_logging
from shared.llm_client import complete

logger = setup_logging("retriever")

QWEN_TURBO = "qwen-turbo"

_SYSTEM_PROMPT = """You are a query optimization assistant for a semantic search system.

Your ONLY task: produce an EVIDENCE RETRIEVAL query — a query to find document passages that
CONTAIN the relevant facts (names, locations, values, attributes), NOT passages that define or
explain concepts.

Target format: "Find evidence about [X] / [Y] / [Z]" — where X, Y, Z are concrete evidence types
that would appear in source documents (e.g., city, hospital location, practicing city, region).

CRITICAL — avoid definition/explanation direction:
- GOOD: "physician city, hospital location, practicing city, region, Tier 1 Tier 2 Tier 3"
- BAD: "what is city tier", "city tier definition", "explain city tier classification"

Rules:
- Output terms that would appear IN the evidence-bearing passages (place names, attributes).
- Do NOT ask "what is X" or request definitions/explanations.
- Do NOT output JSON or markdown. Return plain text only.
"""


def rewrite_for_retrieval(
    guidance_text: str,
    *,
    user_prompt_suffix: str = "Produce an evidence retrieval query (find passages containing this info, NOT definitions):",
    provider_override: str = "qwen",
    model_override: str = QWEN_TURBO,
    max_tokens: int = 256,
    fallback_fn: Callable[[str], str] | None = None,
) -> str:
    """
    Rewrite guidance text into a retrieval-optimized query.

    Generic entry point for any guidance type. Use domain-specific wrappers
    (e.g. rewrite_segment_guidance) or pass custom user_prompt_suffix to extend.

    Args:
        guidance_text: Raw guidance or methodology text.
        user_prompt_suffix: Instruction shown after the text (default: "Produce a retrieval query:").
        provider_override: LLM provider.
        model_override: Model name.
        max_tokens: Max output length.
        fallback_fn: If provided, called on input when LLM fails instead of returning original.
            Signature: (input_text: str) -> str.

    Returns:
        A concise query string for semantic search.
    """
    text = (guidance_text or "").strip()
    if not text:
        logger.warning("rewrite_for_retrieval: empty input, returning empty string")
        return ""

    user_prompt = f"{text}\n\n{user_prompt_suffix}"

    try:
        raw = complete(
            _SYSTEM_PROMPT,
            user_prompt,
            max_tokens=max_tokens,
            provider_override=provider_override,
            model_override=model_override,
        )
        query = (raw or "").strip()
        logger.info(
            "rewrite_for_retrieval done input_len=%d output_len=%d",
            len(text),
            len(query),
        )
        return query
    except Exception as e:
        logger.exception(
            "rewrite_for_retrieval failed: %s",
            e.__class__.__name__,
        )
        if fallback_fn is not None:
            return fallback_fn(text)
        return text


def rewrite_segment_guidance(
    segment_guidance: str,
    *,
    provider_override: str = "qwen",
    model_override: str = QWEN_TURBO,
    max_tokens: int = 256,
) -> str:
    """
    Rewrite cowork segment guidance into a retrieval-optimized query.

    Thin wrapper over rewrite_for_retrieval for segment methodology from the
    cowork agent. Pass segment guidance text; uses generic rewrite logic.
    """
    return rewrite_for_retrieval(
        segment_guidance,
        user_prompt_suffix=(
            "Produce an evidence retrieval query to find passages containing the evidence "
            "described above (e.g. for city tier: physician city, hospital location, practicing "
            "city, region — NOT definitions or explanations):"
        ),
        provider_override=provider_override,
        model_override=model_override,
        max_tokens=max_tokens,
    )


if __name__ == "__main__":
    # cd backend && python -m retriever.query_rewrite
    sample = """
Business Objective
Support targeted resource allocation for Sotyku by identifying HCPs based on city tier.

Segmentation Lens
1. City tier

Segmentation Guideline
1. Look for HCP practice location, city names, Tier 1 Tier 2 Tier 3.
2. Identify urbanization levels, metropolitan area, regional classification.
"""
    result = rewrite_segment_guidance(sample)
    assert result, "rewrite should return non-empty query"
    print("Rewritten query:", result)
    print("query_rewrite test passed")


