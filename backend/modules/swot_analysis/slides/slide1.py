"""SWOT Analysis slide 1 (4-column SWOT table) prompt builder."""

def build_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Focused prompt for SWOT Analysis 4-column table."""
    module = "SWOT Analysis"
    questions: list[str] = []
    col_guide = ", ".join(c for c in segment_names if c)
    system = (
        "You are a business analyst. Fill the SWOT table based on the provided context.\n"
        "The SWOT table has 4 columns (Strengths, Weaknesses, Opportunities, Threats) and exactly 1 data row. "
        "Unlike segment tables, there are no row indexes — the four column names are the ONLY guide.\n"
        "Synthesize content for each of the 4 cells from: (1) Customer Segmentation tables/summary if present, "
        "(2) uploaded market definition and competitor analysis documents.\n"
        "Output a JSON array with exactly ONE inner array of 4 values: [strengths_text, weaknesses_text, opportunities_text, threats_text].\n"
        "Use concise, professional language. If context is insufficient, provide reasonable placeholder text.\n"
        "Output ONLY valid JSON, no markdown or explanation."
    )
    user = (
        f"Context (Customer Segmentation + uploaded market/competitor documents):\n{content}\n\n"
        + (f"Key business questions for {module}:\n" + "\n".join(f"- {q}" for q in questions) + "\n\n" if questions else "")
        + f"Table columns (extract evidence for each): {col_guide}\n\n"
        'Generate exactly 1 row with 4 values. Format: [["strengths","weaknesses","opportunities","threats"]]'
    )
    return system, user
