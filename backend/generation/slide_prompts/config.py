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
_modules_loaded = False


def _ensure_modules_loaded() -> None:
    """Lazy load modules to register prompt builders. Breaks circular import with modules."""
    global _modules_loaded
    if not _modules_loaded:
        from modules import customer_segmentation  # noqa: F401
        from modules import messaging_strategy  # noqa: F401
        from modules import swot_analysis  # noqa: F401
        _modules_loaded = True


def normalize_label(label: str) -> str:
    """Normalize row label for comparison (lowercase, collapsed whitespace)."""
    return " ".join((label or "").strip().lower().split())


def get_prompt_builder(module: str) -> PromptBuilder | None:
    """Return the slide-specific prompt builder for *module*, or None."""
    _ensure_modules_loaded()
    return REGISTRY.get(module.lower().strip())


def register_prompt_builder(module: str, builder: PromptBuilder) -> None:
    """Register a prompt builder for a module. Used by modules when they load."""
    REGISTRY[(module or "").lower().strip()] = builder
