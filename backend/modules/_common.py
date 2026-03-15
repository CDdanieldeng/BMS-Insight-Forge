"""Shared utilities for modules."""

from __future__ import annotations

from typing import Any


class SharedFixTableAgent:
    """Shared fix-table agent. Applies user feedback to refine table content."""

    def apply_feedback(
        self,
        *,
        module: str,
        current_content: list[list[str]],
        table_structure: dict[str, Any],
        user_message: str,
        file_ids: list[str],
        current_column_headers: list[str] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Apply feedback and return updated content + assistant message."""
        # Lazy import to avoid circular dependency: modules -> generation.agent
        from generation.agent import apply_feedback as _apply_feedback_impl

        return _apply_feedback_impl(
            module=module,
            current_content=current_content,
            table_structure=table_structure,
            user_message=user_message,
            file_ids=file_ids,
            current_column_headers=current_column_headers,
            conversation_history=conversation_history,
        )


_SHARED_FIX_TABLE_AGENT: SharedFixTableAgent | None = None


def get_shared_fix_table_agent() -> SharedFixTableAgent:
    """Return singleton shared fix-table agent."""
    global _SHARED_FIX_TABLE_AGENT
    if _SHARED_FIX_TABLE_AGENT is None:
        _SHARED_FIX_TABLE_AGENT = SharedFixTableAgent()
    return _SHARED_FIX_TABLE_AGENT
