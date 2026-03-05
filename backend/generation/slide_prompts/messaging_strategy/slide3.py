"""Messaging Strategy slide 3 prompt builder."""


def build_prompts(
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
- No markdown, no explanations, no extra keys.

STRICT SHAPE RULES (MANDATORY)
1. The top-level value MUST be a JSON array with exactly {n_rows} items.
2. Every top-level item MUST be a JSON array (never a plain string/object/null).
3. Every inner array MUST contain exactly {n_segments} string values.
4. Even when a row uses one shared statement across segments
   (e.g., "Desired Behavior Change", "Differentiated Competitive Benefit"),
   you MUST still output an array with {n_segments} strings by repeating the same
   core statement in each segment position.
5. Invalid example (DO NOT do this):
   ["row1_seg1", "row1_seg2"],
   "shared statement for all segments"
6. Valid example:
   ["row1_seg1", "row1_seg2"],
   ["shared statement", "shared statement"]"""

    user = f"""Segments to populate (columns): {segments_list}

Row labels to fill (in order): {indexes}

Mandatory shape reminder:
- Exactly {n_rows} rows in the outer array.
- Every row must be an array with exactly {n_segments} strings.
- Never return a row as a plain string.

Source materials:
{content}

Return the JSON array of arrays now:"""

    return system, user
