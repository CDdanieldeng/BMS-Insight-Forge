"""Segment name extraction helper for generation pipeline."""

import json
import re
import time
from collections.abc import Callable

from shared.logging_config import setup_logging

from shared.llm_client import complete
from shared.stage_metrics import stage_scope

logger = setup_logging("generation")


def extract_segment_names(
    retriever_content: str,
    n_segments: int,
    module: str,
    trace_writer: Callable[..., None] | None = None,
) -> list[str]:
    """
    Use LLM to identify real customer segment names from uploaded documents.
    Returns exactly n_segments names. Falls back to generic names if content
    is insufficient.
    """
    system = f"""You are a pharmaceutical commercial strategy analyst.

Analyze the provided materials and identify HCP customer segments relevant for promoting the product discussed.
Customers must refer only to HCPs (physicians, specialists, prescribers, clinical decision makers).
Do not create segments for payers, regulators, procurement bodies, government stakeholders, or patients.

Your goal is to identify exactly {n_segments} distinct, mutually exclusive HCP segments that reflect different
physician mindsets and treatment decision logics related to therapy adoption.

Segmentation must primarily differ by:
- attitudes and beliefs
- treatment behaviors and decision patterns
- drivers and barriers

Use demographics or practice setting only as secondary context, not primary segmentation criteria.
Do not define segments only by prescribing volume, usage, geography, hospital tier, or patient volume.

Evidence discipline:
- prioritize segment patterns explicitly supported in the source
- avoid unsupported inference and over-generalization
- if evidence is sparse, still provide plausible HCP segment names grounded in available signals

Naming rules:
- concise and descriptive
- less than 5 words each
- respectful and neutral
- easy to remember

Return ONLY valid JSON as a flat array of exactly {n_segments} segment name strings.
No markdown, no explanation, no extra keys."""

    user = f"""Module: {module}
Number of segments needed: {n_segments}

Content from uploaded documents:
{retriever_content}

Task:
1) Identify the most meaningful and distinct HCP segment archetypes in this content.
2) Ensure names capture mindset/behavior differences in treatment decisions.
3) Return exactly {n_segments} names.

Output format:
["Segment Name 1", "Segment Name 2", "..."]"""

    with stage_scope("segment_name_extraction"):
        raw = ""
        try:
            start = time.perf_counter()
            raw = complete(system, user, max_tokens=150).strip()
            if trace_writer:
                trace_writer(
                    module=module,
                    n_segments=n_segments,
                    system_prompt=system,
                    user_prompt=user,
                    llm_raw_response=raw,
                )
            if "```" in raw:
                match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
                if match:
                    raw = match.group(1)
            names = json.loads(raw)
            if not isinstance(names, list):
                raise ValueError("Expected a JSON list")
            # Ensure exactly n_segments entries.
            names = [str(name).strip() for name in names[:n_segments]]
            while len(names) < n_segments:
                names.append(f"Segment {len(names) + 1}")
            logger.info(
                "Segment extraction done module=%s n=%d names=%s elapsed_ms=%d",
                module,
                n_segments,
                names,
                int((time.perf_counter() - start) * 1000),
            )
            return names
        except Exception as exc:
            if trace_writer:
                trace_writer(
                    module=module,
                    n_segments=n_segments,
                    system_prompt=system,
                    user_prompt=user,
                    llm_raw_response=raw,
                )
            logger.warning("Segment extraction failed, using fallbacks: %s", exc)
            return [f"Segment {i}" for i in range(1, n_segments + 1)]
