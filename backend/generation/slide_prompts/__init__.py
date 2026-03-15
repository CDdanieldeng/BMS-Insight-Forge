"""Per-slide LLM prompt builders.

Each builder receives:
    content        – retrieved document text (already chunked/ranked)
    indexes        – ordered list of row labels for this slide's table
    segment_names  – ordered list of column/segment names

Returns a (system_prompt, user_prompt) tuple consumed by generate_table_content.

To add a new slide, create a new subfolder with slideN.py + config.py, implement
a builder and register it in that subfolder's __init__.py.
"""

from .config import (
    PromptBuilder,
    get_prompt_builder,
)

__all__ = ["PromptBuilder", "get_prompt_builder"]
