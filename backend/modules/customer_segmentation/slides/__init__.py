"""Customer Segmentation slide prompts: routes by slide-unique row labels."""

from generation.slide_prompts.config import REGISTRY, normalize_label

from . import slide1, slide2
from .config import SLIDE2_INDEXES


def _customer_segmentation_prompts(
    content: str,
    indexes: list[str],
    segment_names: list[str],
) -> tuple[str, str]:
    """Route Customer Segmentation prompt by slide-unique row labels."""
    normalized_indexes = [normalize_label(i) for i in indexes]
    if normalized_indexes == SLIDE2_INDEXES:
        return slide2.build_prompts(content, indexes, segment_names)
    return slide1.build_prompts(content, indexes, segment_names)


def _register() -> None:
    REGISTRY["customer segmentation"] = _customer_segmentation_prompts


_register()
