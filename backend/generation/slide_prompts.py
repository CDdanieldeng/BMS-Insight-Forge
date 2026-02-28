"""Per-slide LLM prompt builders.

Each builder receives:
    content        – retrieved document text (already chunked/ranked)
    indexes        – ordered list of row labels for this slide's table
    segment_names  – ordered list of column/segment names

Returns a (system_prompt, user_prompt) tuple consumed by generate_table_content.

To add a new slide, implement a builder function and register it in _REGISTRY
under the normalized module name (lowercase, stripped).
"""

from typing import Callable

# (content, indexes, segment_names) → (system_str, user_str)
PromptBuilder = Callable[[str, list[str], list[str]], tuple[str, str]]

# ──────────────────────────────────────────────────────────────────────────────
# Row schema definitions for Customer Segmentation
# ──────────────────────────────────────────────────────────────────────────────

_CUSTOMER_SEGMENTATION_ROW_SCHEMA: list[dict[str, str]] = [
    {
        "row_label": "Demographics",
        "definition": (
            "Scope components: age, gender. "
            "Only personal identity attributes are allowed. "
            "Exclude location, city tier, hospital level, specialty, "
            "institution type, and patient volume."
        ),
    },
    {
        "row_label": "Preferences",
        "definition": (
            "Scope components: channel preference, detailing style, call frequency. "
            "Refers only to engagement preferences toward pharmaceutical sales representatives. "
            "Excludes patient communication and treatment preference."
        ),
    },
    {
        "row_label": "Attitudes/Beliefs",
        "definition": (
            "Scope components: overall mindset, treatment approach, product perceptions. "
            "Refers to explicitly stated beliefs or evaluations. "
            "Excludes observable prescribing behavior."
        ),
    },
    {
        "row_label": "Capabilities",
        "definition": (
            "Scope components: support staff availability, caregiver support, "
            "knowledge level, clinical experience. "
            "Refers to ability or available resources. "
            "Excludes attitudes and environment."
        ),
    },
    {
        "row_label": "Environment",
        "definition": (
            "Scope components: practice size, socio-economic environment, location. "
            "Includes city tier, hospital level, patient volume, and institutional setting. "
            "Excludes personal identity attributes."
        ),
    },
    {
        "row_label": "Behaviors",
        "definition": (
            "Scope components: product usage, early adopter status, practice affinity, "
            "prescribing patterns, treatment sequencing, adoption timing. "
            "Refers only to observable actions."
        ),
    },
    {
        "row_label": "Drivers",
        "definition": (
            "Scope component: explicitly stated motivating factors for prescribing the product. "
            "Must directly describe reasons to prescribe the product."
        ),
    },
    {
        "row_label": "Barriers",
        "definition": (
            "Scope component: explicitly stated discouraging factors for prescribing the product. "
            "Must directly describe reasons not to prescribe the product."
        ),
    },
]

# Build a lookup so we can emit only the schemas that match actual table rows
_CS_SCHEMA_BY_LABEL: dict[str, str] = {
    row["row_label"].lower(): row["definition"]
    for row in _CUSTOMER_SEGMENTATION_ROW_SCHEMA
}


def _customer_segmentation_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Strict extraction prompt for the Customer Segmentation slide."""

    n_segments = len(segment_names)
    n_rows = len(indexes)

    # Build the row schema block: use predefined definition when available,
    # otherwise fall back to a generic definition.
    schema_lines: list[str] = []
    for label in indexes:
        definition = _CS_SCHEMA_BY_LABEL.get(label.lower().strip())
        if definition:
            schema_lines.append(f'  - "{label}": {definition}')
        else:
            schema_lines.append(
                f'  - "{label}": Explicitly stated information related to {label} for this segment.'
            )
    schema_block = "\n".join(schema_lines)

    segments_list = ", ".join(f'"{s}"' for s in segment_names)

    system = f"""You are a strict information extraction agent supporting a pharmaceutical company.

Your task is to extract structured information describing HCP customer segments \
from the uploaded materials and populate a predefined table.

------------------------------------------------------------

STRICT CLASSIFICATION & EXTRACTION PRINCIPLE

- Only use information explicitly stated in the materials.
- Do NOT infer implied attributes.
- Evaluate each data point independently against the relevant row definition.
- Do NOT force a data point into a row if it does not strictly match the definition.
- If not fully confident that a data point matches the row definition, use exactly:
  "Not found in provided materials."

------------------------------------------------------------

ROW SCHEMA (FIXED)

Each row label has a definition that must be followed strictly:

{schema_block}

------------------------------------------------------------

EXHAUSTIVE SEARCH REQUIREMENT (APPLIES TO EACH ROW AND EACH SEGMENT)

For each segment and for each row label:

1. Scan the entire material and identify ALL explicitly stated data points \
that strictly match the row definition.
2. Re-scan the entire material to ensure no valid matches are omitted. \
Do NOT stop after identifying one example.
3. Extract all valid matching statements before summarisation.
4. If no explicit match exists for a given row and segment, use:
   "Not found in provided materials."

------------------------------------------------------------

SUMMARISATION REQUIREMENT (APPLIES AFTER COMPLETE EXTRACTION PER ROW PER SEGMENT)

After completing exhaustive extraction for a given row label and segment:

1. If no valid matches exist, return exactly:
   "Not found in provided materials."

2. If valid matches exist:
   - Summarise them into 1–4 key conclusions (maximum 4).
   - Retain numerical values only when they directly describe the segment \
itself under the row definition (e.g., volume, age, size).
   - Convert numerical values into qualitative conclusions when they represent \
proportions, percentages, comparisons across segments, or survey statistics. \
Do NOT report raw numbers.

3. Each conclusion must:
   - Represent one distinct idea.
   - Be concise and non-redundant.
   - Use neutral, objective, descriptive language.
   - Strictly reflect the extracted content only.
   - Be 18 words or fewer.

------------------------------------------------------------

COMPLETENESS VERIFICATION (MANDATORY INTERNAL STEP)

Before generating output:

1. Ensure exhaustive scanning has been completed for every segment × row label.
2. Ensure all valid matches have been considered.
3. Ensure summarisation reflects extracted content only.
4. Then generate the final JSON.

Do NOT output this verification step.

------------------------------------------------------------

OUTPUT FORMAT

Return ONLY a valid JSON array of arrays.
- Outer array: one inner array per row label, in this exact order: {indexes}
- Inner array: one string value per segment column, in this exact order: {segment_names}
- Total rows: {n_rows}
- Values per row: {n_segments}
- No explanations, no markdown, no extra keys, no trailing commas.

Example structure (2 rows, 2 segments):
[["value_row1_seg1", "value_row1_seg2"], ["value_row2_seg1", "value_row2_seg2"]]"""

    user = f"""Segments to populate (columns): {segments_list}

Row labels to fill (in order): {indexes}

Content from uploaded materials:
{content}

Return the JSON array of arrays now:"""

    return system, user


# ──────────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, PromptBuilder] = {
    "customer segmentation": _customer_segmentation_prompts,
}


def get_prompt_builder(module: str) -> PromptBuilder | None:
    """Return the slide-specific prompt builder for *module*, or None."""
    return _REGISTRY.get(module.lower().strip())
