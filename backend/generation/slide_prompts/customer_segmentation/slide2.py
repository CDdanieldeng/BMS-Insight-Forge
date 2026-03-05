"""Customer Segmentation slide 2 prompt builder."""


def build_prompts(
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
