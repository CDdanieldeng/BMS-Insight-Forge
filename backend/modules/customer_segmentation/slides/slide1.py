"""Customer Segmentation slide 1 prompt builder."""

from __future__ import annotations

NOT_FOUND_CELL_TEXT = "Not found in provided materials."

# Normalized keys via alnum-only lowercasing (e.g. "Attitudes/Beliefs" -> "attitudesbeliefs")
_ROW_DEFINITION_FRAGMENTS: dict[str, str] = {
    "demographics": (
        "- Demographics: ONLY age or gender\n"
        '  If not explicitly stated → "Not found in provided materials."'
    ),
    "preferences": "- Preferences:\n  Explicit engagement preferences",
    "attitudesbeliefs": (
        "- Attitudes/Beliefs:\n  Explicit mindset or perception"
    ),
    "capabilities": (
        "- Capabilities:\n  Clinical experience or operational capability"
    ),
    "environment": (
        "- Environment:\n  Practice setting (city tier, hospital level, etc.)"
    ),
    "behaviors": "- Behaviors:\n  Observable actions (prescribing, adoption)",
    "drivers": "- Drivers:\n  Explicit motivators",
    "barriers": "- Barriers:\n  Explicit concerns or resistance",
}

_UNKNOWN_ROW_DEFINITION = (
    "- Use only information explicitly stated in the excerpts that applies to this row.\n"
    '- If nothing qualifies → output EXACTLY: "Not found in provided materials."'
)


def _normalize_row_key(row_label: str) -> str:
    return "".join(ch for ch in (row_label or "").lower() if ch.isalnum())


def row_definition_for_label(row_label: str) -> str:
    """Return the strict row-definition snippet for a template row label."""
    key = _normalize_row_key(row_label)
    return _ROW_DEFINITION_FRAGMENTS.get(key, _UNKNOWN_ROW_DEFINITION)


def row_definition_for_index(indexes: list[str], row_idx: int) -> str:
    """Row definition for the row at *row_idx* in *indexes* order."""
    if row_idx < 0 or row_idx >= len(indexes):
        return _UNKNOWN_ROW_DEFINITION
    return row_definition_for_label(indexes[row_idx])


def build_methodology_block(raw_query: str | None) -> str:
    """Verbatim methodology block used in matrix and single-cell prompts."""
    if not raw_query or not str(raw_query).strip():
        return ""
    return f"""
------------------------------------------------------------

SEGMENTATION METHODOLOGY GUIDANCE

The following methodology was agreed with the business team and should be treated
as the decision framework for segment identification.

You will typically receive this methodology in 3 parts:
- Business Objective
- Segmentation Lens
- Segmentation Guideline

How to apply it:
- Treat Segmentation Lens as the primary segmentation axis.
- Treat Segmentation Guideline as strict classification rules and inclusion constraints.
- Use Business Objective only as strategic context; do not use it as direct evidence.
- Validate each segment against uploaded evidence before filling any cell.
- The methodology guides where to look and how to classify, but it is NOT evidence itself.
- Every cell value MUST come from or be verified against uploaded materials.

Agreed segmentation methodology (verbatim):
{str(raw_query).strip()}

------------------------------------------------------------

"""


def build_single_cell_prompts(
    *,
    segment_name: str,
    row_label: str,
    row_definition: str,
    evidence_text: str,
    methodology_block: str,
) -> tuple[str, str]:
    """
    Prompts for filling ONE matrix cell (one segment × one row).

    The model must return JSON: {{"cell": "..."}} only.
    """
    methodology = methodology_block or ""
    evidence_section = (
        evidence_text.strip()
        if evidence_text.strip()
        else "No excerpts were retrieved for this segment and row. "
        'You must output EXACTLY: "Not found in provided materials."'
    )

    system = f"""You are a professional consultant supporting a pharmaceutical company.
{methodology}
------------------------------------------------------------

SINGLE-CELL TASK

You are filling exactly ONE cell:
- Column (segment): "{segment_name}"
- Row: "{row_label}"

Use ONLY the retrieved excerpts below as evidence. The methodology (if any) is not evidence.

------------------------------------------------------------

LANGUAGE ENFORCEMENT (STRICT)

- ALL output MUST be written in English.
- DO NOT use Chinese or mixed Chinese-English.

------------------------------------------------------------

FALLBACK (STRICT)

When no valid evidence exists for this segment and row in the excerpts, output EXACTLY:
"{NOT_FOUND_CELL_TEXT}"

Do not translate or paraphrase that phrase.

------------------------------------------------------------

ROW DEFINITION FOR THIS CELL (STRICT)

{row_definition}

------------------------------------------------------------

RULES

- Only use explicitly stated information from excerpts attributable to segment "{segment_name}".
- If evidence is ambiguous, shared across segments, or not specific to this segment → use the fallback phrase.
- Do NOT include the segment name inside the cell text.
- 1–3 sentences; one idea per sentence; no speculation; no copy-paste duplication.

------------------------------------------------------------

OUTPUT FORMAT

Return ONLY a JSON object, no markdown fences:
{{"cell": "<value>"}}
"""

    user = f"""Segment: "{segment_name}"
Row: "{row_label}"

Retrieved excerpts (may be empty):
{evidence_section}

Return ONLY: {{"cell": "..."}}"""

    return system, user


def build_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
    raw_query: str | None = None,
) -> tuple[str, str]:
    """Focused prompt for Customer Segmentation slide 1."""
    n_segments = len(segment_names)
    n_rows = len(indexes)
    segments_list = ", ".join(f'"{s}"' for s in segment_names)

    cowork_block = ""
    if raw_query and raw_query.strip():
        cowork_block = f"""
------------------------------------------------------------

SEGMENTATION METHODOLOGY GUIDANCE

The following methodology was agreed with the business team and should be treated
as the decision framework for segment identification.

You will typically receive this methodology in 3 parts:
- Business Objective
- Segmentation Lens
- Segmentation Guideline

How to apply it:
- Treat Segmentation Lens as the primary segmentation axis.
- Treat Segmentation Guideline as strict classification rules and inclusion constraints.
- Use Business Objective only as strategic context; do not use it as direct evidence.
- Validate each segment against uploaded evidence before filling any cell.
- The methodology guides where to look and how to classify, but it is NOT evidence itself.
- Every cell value MUST come from or be verified against uploaded materials.

Agreed segmentation methodology (verbatim):
{raw_query.strip()}

------------------------------------------------------------

"""

    system = f"""You are a professional consultant supporting a pharmaceutical company.
{cowork_block}

------------------------------------------------------------

LANGUAGE ENFORCEMENT (STRICT)

- ALL output MUST be written in English.
- This rule applies to EVERY cell and EVERY sentence.

- DO NOT use:
  - Chinese
  - mixed Chinese-English sentences

- Even if the input materials are in Chinese:
  - translate the meaning
  - summarize in professional English

------------------------------------------------------------

FALLBACK LANGUAGE RULE

When no valid evidence exists, output EXACTLY:
"Not found in provided materials."

- Do NOT translate
- Do NOT paraphrase
- Do NOT modify wording

------------------------------------------------------------

## CORE OBJECTIVE

Generate a Customer Segmentation matrix based ONLY on the provided materials.

------------------------------------------------------------

MANDATORY WORKFLOW (STRICT)

You MUST follow this internal workflow before writing output:

Step 1. SEGMENT-LEVEL EVIDENCE CLASSIFICATION
- For each segment, identify ONLY evidence that explicitly belongs to that segment
- Evidence must be clearly attributable to ONE segment
- If evidence is ambiguous, shared, or not segment-specific → DISCARD it

Step 2. EVIDENCE VALIDATION
- Only use explicitly stated information
- Do NOT infer or assume

Step 3. CELL CONSTRUCTION
- For each row × segment:
  - Use ONLY that segment’s evidence
  - If no valid evidence → "Not found in provided materials."

Step 4. ANTI-COLLAPSE CHECK
- Compare across segments BEFORE finalizing
- If two cells are identical:
  - Re-check if segment-specific evidence truly supports it
  - If not → replace with "Not found in provided materials."

------------------------------------------------------------

STRICT CLASSIFICATION PRINCIPLE

- Do NOT mix evidence across segments
- General statements without segment attribution MUST NOT be used

------------------------------------------------------------

ROW DEFINITIONS (STRICT)

- Demographics: ONLY age or gender  
  If not explicitly stated → "Not found in provided materials."

- Preferences:
  Explicit engagement preferences

- Attitudes/Beliefs:
  Explicit mindset or perception

- Capabilities:
  Clinical experience or operational capability

- Environment:
  Practice setting (city tier, hospital level, etc.)

- Behaviors:
  Observable actions (prescribing, adoption)

- Drivers:
  Explicit motivators

- Barriers:
  Explicit concerns or resistance

------------------------------------------------------------

SUMMARISATION RULES

- 1–3 sentences per cell
- Each sentence = one idea
- No redundancy
- No speculation
- No copy-paste

------------------------------------------------------------

FINAL CHECK (MANDATORY)

Before output:
- All cells are in English
- No Chinese characters exist
- All cells are evidence-based
- No identical sentences across segments unless strictly justified

------------------------------------------------------------

OUTPUT FORMAT

Return ONLY a valid JSON array of arrays.

- Outer array (rows in order):
  {indexes}

- Inner array (segments in order):
  {segment_names}

- Total rows: {n_rows}
- Values per row: {n_segments}

NO:
- explanations
- markdown
- extra text

------------------------------------------------------------

CRITICAL CELL RULE

Each cell:
- Represents ONE segment ONLY
- Do NOT merge segments
- Do NOT include segment names inside cell

WRONG:
[["A: xxx B: xxx"]]

CORRECT:
[["xxx", "xxx"]]
"""

    user = f"""Segments to populate (columns): {segments_list}

Row labels to fill (in order): {indexes}

Content from uploaded materials:
{content}

Return the JSON array of arrays now:"""

    return system, user
