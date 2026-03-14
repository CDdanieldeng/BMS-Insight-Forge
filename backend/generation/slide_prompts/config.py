"""Shared types and registry for slide prompt builders.

Each builder receives:
    content        – retrieved document text (already chunked/ranked)
    indexes        – ordered list of row labels for this slide's table
    segment_names  – ordered list of column/segment names

Returns a (system_prompt, user_prompt) tuple consumed by generate_table_content.
"""

from typing import Callable

# (content, indexes, segment_names) → (system_str, user_str)
PromptBuilder = Callable[[str, list[str], list[str]], tuple[str, str]]

# Registry: module name (normalized) → PromptBuilder
REGISTRY: dict[str, PromptBuilder] = {}


def normalize_label(label: str) -> str:
    """Normalize row label for comparison (lowercase, collapsed whitespace)."""
    return " ".join((label or "").strip().lower().split())


def get_prompt_builder(module: str) -> PromptBuilder | None:
    """Return the slide-specific prompt builder for *module*, or None."""
    return REGISTRY.get(module.lower().strip())
