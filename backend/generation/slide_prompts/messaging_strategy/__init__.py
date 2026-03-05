"""Messaging Strategy slide prompts: routes by slide-unique row labels."""

from ..config import REGISTRY, normalize_label
from . import slide3
from .config import SLIDE1_INDEXES


def _messaging_strategy_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Route Messaging Strategy prompt by slide-unique row labels."""
    normalized_indexes = [normalize_label(i) for i in indexes]
    if normalized_indexes == SLIDE1_INDEXES:
        return slide3.build_prompts(content, indexes, segment_names)
    return slide3.build_prompts(content, indexes, segment_names)


def _register() -> None:
    REGISTRY["messaging strategy"] = _messaging_strategy_prompts
