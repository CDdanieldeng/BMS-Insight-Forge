"""Document-level facet cache.

Mirrors the chunk-level FacetCache but keyed by file_id instead of chunk_id.
Each entry stores document-level signals generated once at upload time:
  - maturity:       "totally_raw" | "semi_raw" | "mature"
  - topic:          "customer segmentation" | "messaging strategy" | "others"
  - summary:        one short sentence summarizing the document
  - filename:       original file name (for traceability)

Backed by a JSONL file so it survives process restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

logger = setup_logging("retriever")

_CACHE_PATH = Path(__file__).resolve().parents[1] / "logs" / "doc_facet_cache.jsonl"


class DocumentFacetCache:
    """Simple JSONL-backed cache keyed by file_id."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _CACHE_PATH
        self._cache: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                file_id = str(row.get("file_id", "")).strip()
                facet = row.get("facet")
                if file_id and isinstance(facet, dict):
                    self._cache[file_id] = facet
        except Exception as exc:
            logger.warning("Doc facet cache load failed path=%s err=%s", self.path, exc)

    def get(self, file_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return self._cache.get(file_id)

    def set(self, file_id: str, facet: dict[str, Any]) -> None:
        self._ensure_loaded()
        self._cache[file_id] = facet
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {"file_id": file_id, "facet": facet},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception as exc:
            logger.warning("Doc facet cache write failed file_id=%s err=%s", file_id, exc)

    def get_best_maturity(
        self, file_ids: list[str], topic_preference: str | None = None
    ) -> str:
        """
        Given a list of file_ids, return the highest maturity level found.

        If topic_preference is set (e.g. "customer segmentation"), only consider
        files whose facet topic matches; if none match, fall back to all file_ids.

        Priority: mature > semi_raw > totally_raw

        Returns:
            maturity: one of "totally_raw" | "semi_raw" | "mature"
        """
        self._ensure_loaded()
        _PRIORITY = {"mature": 2, "semi_raw": 1, "totally_raw": 0}
        best_maturity = "totally_raw"

        candidates = list(file_ids)
        if topic_preference:
            topic_pref = str(topic_preference).strip().lower()
            by_topic = [fid for fid in file_ids if self._cache.get(fid, {}).get("topic") == topic_pref]
            if by_topic:
                candidates = by_topic

        for fid in candidates:
            facet = self._cache.get(fid)
            if not facet:
                continue
            maturity = str(facet.get("maturity", "totally_raw")).strip().lower()
            if _PRIORITY.get(maturity, 0) > _PRIORITY.get(best_maturity, 0):
                best_maturity = maturity

        return best_maturity


# Module-level singleton used by the ingest endpoint and the CS agent.
_doc_facet_cache = DocumentFacetCache()


def get_doc_facet_cache() -> DocumentFacetCache:
    return _doc_facet_cache
