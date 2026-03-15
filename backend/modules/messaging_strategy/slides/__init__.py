"""Messaging Strategy slide prompts."""

from modules._slide_registry import REGISTRY

from . import slide3


def _messaging_strategy_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Route Messaging Strategy prompt by slide-unique row labels."""
    return slide3.build_prompts(content, indexes, segment_names)


def _register() -> None:
    REGISTRY["messaging strategy"] = _messaging_strategy_prompts


_register()
