"""SWOT Analysis slide prompts."""

from modules._slide_registry import REGISTRY

from . import slide1


def _swot_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """SWOT prompt builder (single slide)."""
    return slide1.build_prompts(content, indexes, segment_names)


def _register() -> None:
    REGISTRY["swot analysis"] = _swot_prompts


_register()
