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
            "age, gender, and personal identity attributes only."
            "Exclude location, city tier, hospital level, institution type, and patient volume."
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

_CS_SLIDE2_INDEXES = [
    "segment summary",
    "current behavior",
    "desired behavior",
    "segment prioritization",
]

_MESSAGING_STRATEGY_SLIDE1_INDEXES = [
    "target/prioritized segment",
    "drivers/barriers",
    "desired behavior change",
    "differentiated competitive benefit",
    "reason to believe",
    "business objective",
]


def _normalize_label(label: str) -> str:
    return " ".join((label or "").strip().lower().split())


def _customer_segmentation_slide2_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Focused prompt for Customer Segmentation slide 2."""
    n_segments = len(segment_names)
    n_rows = len(indexes)
    segments_list = ", ".join(f'"{s}"' for s in segment_names)

    system = f"""You are a commercial strategy analyst supporting a pharmaceutical brand team.

Your task is to fill the slide-2 segment table using the provided segment names and source materials.
The segment columns are already fixed (inherited from slide 1) and must remain consistent.

ROW DEFINITIONS (SLIDE 2)
- "Segment Summary": A concise portrait of the segment describing defining characteristics explicitly stated in the materials (e.g., mindset, positioning, distinguishing traits). It summarizes who the segment is.
- "Current Behavior": Observable actions the segment currently takes in practice, including prescribing patterns, treatment sequencing, product usage, adoption timing, and switching behavior. Must describe present-state behavior only.
- "Desired Behavior": The target behavior expected from the segment regarding {{SOTYKTU}}. Prefer explicitly stated objectives. If no explicit target behavior exists, infer a conservative and commercially logical improvement strictly grounded in extracted Current Behavior (e.g., earlier adoption, increased usage, switching from competitor).
- "Segment Prioritization":
  A readable text output (NOT a JSON object), in this exact style:
  "High - <1-3 concise sentences explanation>"
  or "Medium - <...>" or "Low - <...>"
  Based on attractiveness assessment across segments.

CORE EXTRACTION PRINCIPLES
1. Use only information explicitly stated in the provided materials for Segment Summary and Current Behavior.
2. If evidence is truly missing for a specific segment-row pair, return exactly:
   "Not found in provided materials."
3. Keep each cell concise but complete for commercial understanding (about 1-3 short bullet-like statements in one paragraph).
4. Do not copy raw long quotes from source text.

DESIRED BEHAVIOR LOGIC

Stage 1 - Explicit Retrieval:
- Extract explicitly stated target behaviors or brand expectations if present.

Stage 2 - Controlled Inference (only if Stage 1 yields no result):
- Infer directional improvement strictly based on extracted Current Behavior.
- Do NOT introduce new assumptions beyond observed behavior patterns.


SEGMENT PRIORITIZATION LOGIC

Stage 1 - Explicit Ranking:
- If materials explicitly rank/prioritize segments, use that directly.

Stage 2 - Comparative Assessment (if no explicit ranking):
- Evaluate segments relative to one another across three criteria:

  1. Market Potential: Measured by current volume, patient size, growth potential

  2. Brand Acceptance: Measured by innovation receptivity, brand preference, competitive defense level

  3. Segment Profile Strength: Measured by demographic, regional, or attitudinal attractiveness and strategic fit

- At least one segment must be "High".
- At least one segment must be "Low".
- Others may be "Medium".
- Explanation must explicitly reference the three criteria, must be grounded only in extracted evidence, and summarized into 1-3 concise sentences.

OUTPUT FORMAT

Return ONLY a valid JSON array of arrays. Structure must follow this exact orientation:

  - The outer array has exactly {n_rows} elements, one per ROW LABEL.
  - Each inner array has exactly {n_segments} elements, one per SEGMENT COLUMN.
  - Do NOT group by segment. Do NOT transpose. Each outer element = one row label.

Concrete layout (using your actual row labels and segment names):

result[0] = row for "{indexes[0]}"  → [{segment_names[0]}_value, {segment_names[1]}_value, ...]
result[1] = row for "{indexes[1]}"  → [{segment_names[0]}_value, {segment_names[1]}_value, ...]
result[2] = row for "{indexes[2]}"  → [{segment_names[0]}_value, {segment_names[1]}_value, ...]
result[3] = row for "{indexes[3]}"  → [{segment_names[0]}_value, {segment_names[1]}_value, ...]

Schematic example (3 rows, 2 segments):
[
  ["row1_seg1_value", "row1_seg2_value"],
  ["row2_seg1_value", "row2_seg2_value"],
  ["row3_seg1_value", "row3_seg2_value"]
]

Additional constraints:
- Return pure strings in cells only.
- For "Segment Prioritization" cells: "High - <explanation>" OR "Medium - <explanation>" OR "Low - <explanation>" OR "Not found in provided materials."
- No markdown, no prose, no extra keys outside the JSON array."""

    user = f"""Segments (columns, in order): {segments_list}
Row labels (outer array order): {indexes}

REMINDER — outer array = rows, inner array = segments:
result[0] = all segments for "{indexes[0]}"
result[1] = all segments for "{indexes[1]}"
result[2] = all segments for "{indexes[2]}"
result[3] = all segments for "{indexes[3]}"

Source materials:
{content}

Return the JSON array of arrays now (outer = rows, inner = segments):"""

    return system, user


def _customer_segmentation_slide1_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Focused prompt for Customer Segmentation slide 1."""
    n_segments = len(segment_names)
    n_rows = len(indexes)

    segments_list = ", ".join(f'"{s}"' for s in segment_names)

    system = f"""You are a strict information extraction agent supporting a pharmaceutical company.

Your task is to extract structured information describing HCP customer segments \
from the uploaded materials and populate a predefined table.

------------------------------------------------------------

STRICT CLASSIFICATION & EXTRACTION PRINCIPLE

- Only use information explicitly stated in the materials.
- Do NOT infer implied attributes.
- Evaluate each data point independently against the row definitions below.
- Do NOT force a data point into a row if it does not strictly match the row definition.
- If not fully confident that a data point matches, use exactly:
  "Not found in provided materials."

------------------------------------------------------------

ROW DEFINITIONS (STRICT)

- Demographics: age, gender only.
- Preferences:
  Explicit preferences regarding:
  1) Interaction style with pharmaceutical representatives (e.g., persuasion openness, detailing depth),
  2) Preferred information channels (including offline interaction with pharma staff, MSL, sales reps, online interaction via WeChat/email, conferences, medical journals, third-party platforms),
  3) Preferred evidence types to trigger prescription (e.g., clinical data, peer case sharing, real-world evidence),
  4) Communication approach during professional interaction (if it reflects information engagement preference rather than patient behavior).

  Include BOTH online and offline pharma-related engagement channels.
  Include explicitly stated preferred information source or engagement method.
  
  Exclude:
  - Patient communication style unless it directly reflects professional interaction preference.
  - Treatment choice logic.
  - Prescribing behavior itself.
- Attitudes/Beliefs: explicit mindset, product perceptions, treatment philosophy. Exclude observed prescribing behavior.
- Capabilities: knowledge level, clinical experience, support staff, operational capability, clinical confidence. Exclude beliefs and environmental context.
- Environment:
  Practice setting and structural context including:
  1) City tier,
  2) Hospital level or institution type,
  3) Practice size,
  4) Monthly patient volume (including explicit average number of moderate-to-severe PsO patients treated per month),
  5) Sub-specialty status,
  6) Attendance in specialized outpatient clinics.

  Patient volume MUST be included if explicitly provided.

  Exclude:
  - Age and gender (belongs to Demographics),
  - Personal beliefs,
  - Clinical decision preferences.
- Behaviors: observable actions (prescribing patterns, product usage, sequencing, early adoption status, switching behavior, adoption timing).
- Drivers: explicit motivators to prescribe/use the brand.
- Barriers: explicit reasons against prescribing/using the brand.

------------------------------------------------------------

EXTRACTION METHOD (MANDATORY)

For each segment and each row:
1. Scan the entire material for all direct evidence that strictly matches the row definition.
2. Re-scan to ensure no valid matches are omitted.
3. Treat each scope component listed in the row definition as an independent search dimension. All components must be verified before concluding completeness.
4. Apply boundary check for Demographics, Preferences, and Environment:
   - If the statement describes where they practice (e.g., city tier, hospital level, practice size, patient volume), classify as Environment, not Demographics.
   - Only classify as Preferences if it explicitly refers to interaction with pharmaceutical representatives, otherwise "Not found in provided materials.".
   - Do not leave practice size or institutional scale unclassified; these must belong to Environment.
5. Summarize all valid points into 1-3 concise conclusions.
6. If no valid evidence exists, use:
   "Not found in provided materials."

------------------------------------------------------------

SUMMARISATION RULES

- Each conclusion must represent one distinct idea.
- Keep wording concise, neutral, objective, and non-redundant.
- Strictly reflect extracted evidence only.
- Retain numerical values only when they directly describe the segment itself under the row definition (e.g., age, volume, size).
- Convert numerical values into qualitative conclusions when they represent proportions, percentages, comparisons across segments, or survey statistics. Do NOT report raw numbers.

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


def _customer_segmentation_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Route Customer Segmentation prompt by slide-unique row labels."""
    normalized_indexes = [_normalize_label(i) for i in indexes]
    if normalized_indexes == _CS_SLIDE2_INDEXES:
        return _customer_segmentation_slide2_prompts(content, indexes, segment_names)
    return _customer_segmentation_slide1_prompts(content, indexes, segment_names)


def _messaging_strategy_slide3_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Focused prompt for Messaging Strategy slide 3 (Messaging Strategy)."""
    n_segments = len(segment_names)
    n_rows = len(indexes)
    segments_list = ", ".join(f'"{s}"' for s in segment_names)

    system = f"""You are a commercial strategy analyst supporting a pharmaceutical brand team.

Your task is to fill Messaging Strategy slide-3 table based on the provided segment names and source inputs.
Keep content practical, actionable, and strictly evidence-led.

SOURCE PRIORITY (MANDATORY)
The user prompt includes two sections:
1) PRIMARY INPUT: PREVIOUS CUSTOMER SEGMENTATION TABLES
2) SECONDARY INPUT: UPLOADED MATERIALS

You MUST fill each cell using PRIMARY INPUT first.
Only when the needed content cannot be found in PRIMARY INPUT for that row/segment, you may use SECONDARY INPUT.
If neither source has evidence, return exactly:
"Not found in provided materials."

ROW DEFINITIONS (MESSAGING STRATEGY - SLIDE 3)
- "Target/Prioritized Segment": use prioritized segment name(s) from Customer Segmentation "Segment Prioritization" entries marked as "High". If multiple are "High", list those names in column order.
- "Drivers/Barriers": summarize the core motivation and resistance factors for that segment, primarily grounded in previous slide tables.
- "Desired Behavior Change": specify the concrete behavior shift expected from the same-column "Target/Prioritized Segment". It must explicitly describe what that prioritized segment should do differently. IMPORTANT: this row must be consistent across all segment columns (same core statement).
- "Differentiated Competitive Benefit": state the brand benefit that is distinctive versus alternatives. IMPORTANT: this row must be consistent across all segment columns (same core statement).
- "Reason to Believe": provide supporting proof points (e.g., evidence theme, clinical rationale, practical experience) that make the benefit credible.
- "Business Objective": define the commercial objective this messaging strategy supports based on the same-column "Target/Prioritized Segment". It must be explicitly linked to winning behavior change in that prioritized segment (e.g., adoption, share, initiation, switching, persistence).

RULES
1. Prioritize explicit evidence; keep synthesis conservative and traceable to evidence.
2. Keep each cell concise (about 1-3 short bullet-like statements in one paragraph).
3. Ensure internal consistency across rows per segment.
4. Column headers are fixed template placeholders (e.g., "Segment 1", "Segment 2"); do not reinterpret them as extracted segment names.
5. For "Desired Behavior Change" and "Differentiated Competitive Benefit":
   - Use one shared statement for all segment columns.
   - Minor wording changes are allowed only for fluency, not for changing meaning.
6. "Desired Behavior Change" must be consistent with the same-column "Target/Prioritized Segment" and cannot be a generic statement detached from target segment context.
7. "Business Objective" must be consistent with the same-column "Target/Prioritized Segment" and cannot be a generic brand-level statement detached from target segment context.
8. If evidence is truly missing for a specific segment-row pair, return exactly:
   "Not found in provided materials."
9. Do not output long raw quotes from source text.

OUTPUT FORMAT
- Return ONLY a valid JSON array of arrays.
- Outer array order must exactly match: {indexes}
- Inner array order must exactly match: {segment_names}
- Total rows: {n_rows}
- Values per row: {n_segments}
- No markdown, no explanations, no extra keys."""

    user = f"""Segments to populate (columns): {segments_list}

Row labels to fill (in order): {indexes}

Source materials:
{content}

Return the JSON array of arrays now:"""

    return system, user


def _messaging_strategy_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Route Messaging Strategy prompt by slide-unique row labels."""
    normalized_indexes = [_normalize_label(i) for i in indexes]
    if normalized_indexes == _MESSAGING_STRATEGY_SLIDE1_INDEXES:
        return _messaging_strategy_slide3_prompts(content, indexes, segment_names)
    return _messaging_strategy_slide3_prompts(content, indexes, segment_names)


# ──────────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, PromptBuilder] = {
    "customer segmentation": _customer_segmentation_prompts,
    "messaging strategy": _messaging_strategy_prompts,
}


def get_prompt_builder(module: str) -> PromptBuilder | None:
    """Return the slide-specific prompt builder for *module*, or None."""
    return _REGISTRY.get(module.lower().strip())
