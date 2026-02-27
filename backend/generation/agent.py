"""Agent for user feedback: adjust table content based on chat."""

import json
import re
from typing import Any

from shared.logging_config import setup_logging

from generation.llm_client import complete

logger = setup_logging("generation")


def apply_feedback(
    module: str,
    current_content: list[list[str]],
    table_structure: dict[str, Any],
    user_message: str,
) -> list[list[str]]:
    """
    Use LLM to update table content based on user feedback.
    Returns updated 2D table data.
    """
    columns = table_structure.get("columns", [])
    indexes = table_structure.get("indexes", [])

    system = """You are a business analyst assistant. The user has provided feedback on a table.
Update the table data according to their feedback. Output a JSON array of arrays.
Each inner array is one row of data. The structure must match the original (same rows, same columns).
Output ONLY valid JSON, no markdown or explanation."""

    user = f"""Module: {module}
Table columns: {columns}
Row labels: {indexes}

Current table data (JSON):
{json.dumps(current_content, ensure_ascii=False)}

User feedback: {user_message}

Generate the updated table data as JSON array of arrays:"""

    try:
        raw = complete(system, user)
        raw = raw.strip()
        if "```" in raw:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if match:
                raw = match.group(1)

        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Expected list of lists")

        result = []
        for row in data:
            if isinstance(row, list):
                result.append([str(c) for c in row])
            else:
                result.append([str(row)])

        logger.info("Agent applied feedback, %d rows", len(result))
        return result
    except Exception as e:
        logger.exception("Agent feedback failed: %s", e)
        raise
