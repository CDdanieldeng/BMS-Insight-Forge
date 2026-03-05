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

# Import submodules so they register their builders
from . import customer_segmentation  # noqa: F401
from . import messaging_strategy  # noqa: F401

# Call _register on each so REGISTRY is populated
customer_segmentation._register()  # noqa: F401
messaging_strategy._register()  # noqa: F401

__all__ = ["PromptBuilder", "get_prompt_builder"]
