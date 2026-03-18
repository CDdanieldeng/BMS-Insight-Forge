"""Parse methodology text into retrieval query strings."""

import re


def _extract_segmentation_lens(methodology: str) -> str:
    """Extract segmentation lens from methodology text. Returns lowercased lens key."""
    if not methodology or not methodology.strip():
        return ""
    text = methodology.strip().lower()
    m = re.search(
        r"segmentation\s+lens\s*(?:\d\.)?\s*([^\n]+?)(?=segmentation\s+guideline|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return ""
    lens_line = m.group(1).strip().split("\n")[0].strip()
    lens_line = re.sub(r"^\d+\.\s*", "", lens_line).strip()
    return lens_line


_LENS_QUERY_MAP: dict[str, list[str]] = {
    "city tier": [
        "城市",
        "地区",
        "执业",
        "医院",
        "一线",
        "二线",
        "三线",
        "上海",
        "北京",
        "广州",
        "深圳",
        "成都",
        "杭州",
        "南京",
        "武汉",
        "西安",
        "长沙",
        "city",
        "region",
        "practice location",
        "urbanization",
        "market potential",
    ],
    "hospital tier": [
        "三甲",
        "二甲",
        "医院等级",
        "tier",
        "hospital level",
    ],
    "treatment behavior": [
        "治疗",
        "处方",
        "biologics",
        "attitudes",
        "barriers",
        "prescribing",
    ],
}


def methodology_to_query(methodology: str) -> str:
    """
    Convert cowork summary (methodology) to a retrieval query string.

    Args:
        methodology: Segmentation methodology text from cowork summary.

    Returns:
        Primary query string for embedding similarity search.
    """
    if not methodology or not methodology.strip():
        return "HCP segment physician prescriber"

    lens = _extract_segmentation_lens(methodology)
    terms: list[str] = []

    # Check extracted lens first, then whole methodology for robustness
    search_text = f"{lens} {methodology}".lower()
    for key, words in _LENS_QUERY_MAP.items():
        if key in lens or key in search_text:
            terms = words
            break

    if not terms:
        guideline_m = re.search(
            r"segmentation\s+guideline\s*\n([\s\S]+?)(?=\n\n|$)",
            methodology,
            re.IGNORECASE,
        )
        if guideline_m:
            g = guideline_m.group(1)[:300]
            cjk = re.findall(r"[\u4e00-\u9fff]{2,4}", g)
            terms = list(dict.fromkeys(cjk))[:10]
        if not terms:
            return "HCP segment physician prescriber"

    return " ".join(terms[:15])
