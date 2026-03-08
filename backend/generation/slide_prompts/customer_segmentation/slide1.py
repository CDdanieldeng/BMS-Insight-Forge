"""Customer Segmentation slide 1 prompt builder."""


def build_prompts(
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
- Demographics: STRICTLY age and gender only.

  VALID demographic evidence:
  - explicit age, age range, or life stage explicitly referring to physician age
  - explicit gender / sex

  INVALID for Demographics (must NOT be included):
  - city tier
  - hospital class / hospital type / institution type
  - practice setting
  - outpatient type / specialized outpatient attendance
  - sub-specialty / PsO focus
  - professional title (e.g., CD, VCD, DIC)
  - years in practice / seniority / "more senior"
  - patient volume
  - treatment experience / knowledge level
  - attitudes / beliefs / behaviors
  - any percentage or profile statistic not explicitly about age or gender

  HARD RULE:
  If explicit age or gender is NOT stated for that segment, return exactly:
  "Not found in provided materials."

  Never use proxy profile information as demographics.
  Never summarize general "Demographic Profiles" sections unless they explicitly contain age or gender.
- Preferences: The way the HCPs like to be engaged with.
  Explicit preferences regarding:
  - Channel preference such as Wechat, Conference, Visit, Face2Face Meeting, etc.
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
- Values per row: {n_segments} (EXACTLY {n_segments} strings per inner array, no more, no less)
- No explanations, no markdown, no extra keys, no trailing commas.

CRITICAL CELL RULES:
- Each cell string describes ONLY the single segment at that column position.
- Do NOT prefix the cell value with the segment name (e.g., "Pioneer: ..." inside a cell is WRONG).
- Do NOT merge two or more segments into one cell string.
- The column order determines which segment a cell belongs to — you do not need to name the segment inside the cell.

WRONG — all segments merged into one cell:
[["Pioneer: x. Considerate Performer: y. Safe Player: z. Traditionalist: w.", ...], ...]

CORRECT — one segment's content per cell, no segment-name prefix:
[["x", "y", "z", "w"], ...]

Example structure (2 rows, 2 segments):
[["value_for_seg1_row1", "value_for_seg2_row1"], ["value_for_seg1_row2", "value_for_seg2_row2"]]"""

    user = f"""Segments to populate (columns): {segments_list}

Row labels to fill (in order): {indexes}

Content from uploaded materials:
{content}

Return the JSON array of arrays now:"""

    return system, user
