"""Simple prompt builder for SWOT cowork agent."""

from __future__ import annotations

import json

from cowork_agent.models import ChatMessage


_SYSTEM_TEMPLATE = """\
You are a strategic consultant embedded in Insight Forge, helping with SWOT Analysis for \
BP (business plan) insight generation in pharmaceutical commercial planning.

Your role is to align with the user on what to emphasise in the SWOT analysis before it is performed. \
Keep the conversation natural, friendly, and focused. You are not performing the analysis yet — \
you are co-working to agree on priorities and emphasis.

SWOT TABLE GUIDANCE
The SWOT table has 4 columns (Strengths, Weaknesses, Opportunities, Threats) and 1 data row.
When interpreting Customer Segmentation summary, filled CS table, and uploaded market definition /
competitor analysis documents, extract evidence that fits each of the four quadrants.

CONTEXT AVAILABLE
{context_block}

RESPOND IN PLAIN TEXT
Reply in natural prose. No JSON. Be concise and conversational. \
If the user shares emphasis areas or priorities, acknowledge and confirm them. \
If they have questions, answer briefly. Keep responses to 2–4 sentences unless more detail is needed.
"""


def build_swot_prompts(
    *,
    history: list[ChatMessage],
    user_message: str,
    cs_summary: str | None = None,
    cs_table_text: str | None = None,
    uploaded_docs_text: str | None = None,
) -> tuple[str, str]:
    """Build system and user prompts for SWOT cowork turn."""
    context_parts: list[str] = []

    if cs_summary and cs_summary.strip():
        context_parts.append(
            "CUSTOMER SEGMENTATION SUMMARY (from prior module)\n"
            + cs_summary.strip()[:4000]
            + "\n"
        )

    if cs_table_text and cs_table_text.strip():
        context_parts.append(
            "CUSTOMER SEGMENTATION TABLE (filled)\n"
            + cs_table_text.strip()[:3000]
            + "\n"
        )

    if uploaded_docs_text and uploaded_docs_text.strip():
        context_parts.append(
            "UPLOADED DOCUMENTS (Market Definition, Competitor Analysis)\n"
            + uploaded_docs_text.strip()[:6000]
            + "\n"
        )

    context_block = "\n---\n\n".join(context_parts) if context_parts else "(No prior context available yet.)"

    system = _SYSTEM_TEMPLATE.format(context_block=context_block)

    history_json = json.dumps(
        [{"role": m.role, "content": m.content} for m in history[-40:]],
        ensure_ascii=False,
    )
    user = f"""CONVERSATION HISTORY
{history_json}

USER MESSAGE
{user_message}

Respond naturally. Align on what to emphasise in the SWOT analysis."""

    return system, user


def build_swot_summary_prompt(
    *,
    history: list[ChatMessage],
) -> tuple[str, str]:
    """Build prompts for end-of-conversation summary."""
    system = """\
You are a strategic consultant for Insight Forge. The user has ended a cowork conversation \
about SWOT Analysis for their business plan.

Produce a concise summary (3–6 sentences) of:
- What emphasis areas or priorities were agreed for the SWOT analysis
- Any key constraints or focus points the user wanted highlighted

Write in clear prose. Output plain text only — no JSON, no markdown headers.
"""

    history_json = json.dumps(
        [{"role": m.role, "content": m.content} for m in history[-60:]],
        ensure_ascii=False,
    )
    user = f"""CONVERSATION HISTORY
{history_json}

Based on the conversation above, produce a brief summary of the agreed SWOT analysis emphasis \
and priorities for the downstream generation agent."""

    return system, user
