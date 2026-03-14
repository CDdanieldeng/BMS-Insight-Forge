"""Local facet cache for lazy facet generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

logger = setup_logging("generation")
_CACHE_PATH = Path(__file__).resolve().parents[1] / "logs" / "facet_cache.jsonl"


class FacetCache:
    """Simple JSONL-backed cache keyed by chunk_id."""

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
                if not line.strip():
                    continue
                row = json.loads(line)
                chunk_id = str(row.get("chunk_id", "")).strip()
                facet = row.get("facet")
                if chunk_id and isinstance(facet, dict):
                    self._cache[chunk_id] = facet
        except Exception as exc:
            logger.warning("Facet cache load failed path=%s err=%s", self.path, exc)

    def get(self, chunk_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return self._cache.get(chunk_id)

    def set(self, chunk_id: str, facet: dict[str, Any]) -> None:
        self._ensure_loaded()
        self._cache[chunk_id] = facet
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {"chunk_id": chunk_id, "facet": facet},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception as exc:
            logger.warning("Facet cache write failed chunk_id=%s err=%s", chunk_id, exc)
