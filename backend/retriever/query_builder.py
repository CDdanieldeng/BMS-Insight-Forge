"""
Cell-aware Query Builder for retrieval.

Produces 1-3 query variants (exact, extended, fallback) from table structure.
Extensible for future LLM or rule-based strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class QuerySet:
    """Structured query variants for hybrid retrieval."""

    exact_query: str
    extended_queries: list[str]
    fallback_query: str

    def all_queries(self) -> list[str]:
        """Return [exact] + extended + [fallback] for recall. Deduped."""
        seen: set[str] = set()
        out: list[str] = []
        for q in [self.exact_query] + self.extended_queries + [self.fallback_query]:
            k = (q or "").strip().lower()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(q.strip())
        return out[:10]  # Cap to avoid explosion


def build_queries(
    seed_query: str,
    module: str,
    table_structure: dict[str, Any],
    *,
    column_name: str | None = None,
    index: str | None = None,
    sheet_name: str | None = None,
    headers: list[str] | None = None,
    cell_context: str | None = None,
    session_id: str | None = None,
    file_id: str | None = None,
) -> QuerySet:
    """
    Build query variants from cell/table context. Extensible, not hardcoded.

    Returns at least 1-3 queries: exact, extended, fallback.
    """
    columns = [str(c).strip() for c in (table_structure.get("columns") or []) if str(c).strip()]
    indexes = [str(i).strip() for i in (table_structure.get("indexes") or []) if str(i).strip()]
    cols = columns[1:6]  # Skip empty/ID column
    idxs = indexes[:6]
    seed = (seed_query or "").strip()
    mod = (module or "").strip()
    is_swot = mod.lower() == "swot analysis"

    # Exact: seed as primary query
    exact_query = seed or " "

    # Extended: seed + columns/indexes
    extended: list[str] = []
    for col in cols:
        extended.append(f"{seed}; {col}")
    if not is_swot:
        for idx in idxs:
            extended.append(f"{seed}; {idx}")
        for col in cols[:3]:
            for idx in idxs[:3]:
                extended.append(f"{seed}; {col}; {idx}")
    if mod:
        extended.append(f"{mod}; {seed}")

    seen_ext: set[str] = set()
    deduped_ext: list[str] = []
    for q in extended:
        k = q.lower().strip()
        if k in seen_ext:
            continue
        seen_ext.add(k)
        deduped_ext.append(q)
        if len(deduped_ext) >= 9:
            break

    # Fallback: simpler query when recall fails
    fallback_query = seed or " "
    if mod:
        fallback_query = f"{mod}; {seed}"

    return QuerySet(
        exact_query=exact_query,
        extended_queries=deduped_ext,
        fallback_query=fallback_query,
    )
