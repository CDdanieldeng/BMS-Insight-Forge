"""
Structured on-disk logs for Customer Segmentation table fill.

Layout under backend/logs/customer_segmentation/:

  YYYYMMDD_HHMMSS_<run_id>/
    run_meta.json           # run parameters and segment list
    segments_intake.md      # segment names + methodology
    segments_llm.md         # segment-side LLM audit (N/A when names are not model-generated)
    cells/
      r{row}_c{col}_{segment_slug}.txt   # full cell LLM prompts + response + retrieval summary
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

logger = setup_logging("cs_fill_session_log")

_LOG_ROOT = Path(__file__).resolve().parents[2] / "logs" / "customer_segmentation"


def _log_root() -> Path:
    custom = (os.getenv("CS_FILL_LOG_DIR") or "").strip()
    return Path(custom) if custom else _LOG_ROOT


def _slug(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (text or "").strip().lower()).strip("_")
    if not s:
        s = "segment"
    return s[:max_len]


def create_fill_session_dir(*, module: str) -> Path:
    """Create ``customer_segmentation/<timestamp>_<8char>/`` and ``cells/`` subfolder."""
    root = _log_root()
    module_part = _slug(module, 32) or "customer_segmentation"
    run_id = uuid.uuid4().hex[:8]
    dir_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{run_id}_{module_part}"
    session_dir = root / dir_name
    (session_dir / "cells").mkdir(parents=True, exist_ok=False)
    logger.info("CS fill session log dir=%s", session_dir)
    return session_dir


def write_run_meta(
    session_dir: Path,
    *,
    module: str,
    file_ids: list[str],
    indexes: list[str],
    segment_names: list[str],
    n_cells: int,
    methodology_present: bool,
    recall_top_k: int,
    rerank_top_k: int,
    max_cell_workers: int,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schema": "cs_fill_run_meta_v1",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "module": module,
        "file_ids": list(file_ids),
        "row_indexes": list(indexes),
        "segment_names": list(segment_names),
        "n_rows": len(indexes),
        "n_segments": len(segment_names),
        "n_cells": n_cells,
        "methodology_present": methodology_present,
        "retrieval_recall_top_k": recall_top_k,
        "retrieval_rerank_top_k": rerank_top_k,
        "max_cell_workers": max_cell_workers,
    }
    if extra:
        payload["extra"] = extra
    path = session_dir / "run_meta.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_segments_intake(
    session_dir: Path,
    *,
    segment_names: list[str],
    methodology: str | None,
    segment_source: str,
    raw_cowork_keys: list[str] | None = None,
) -> None:
    """
    Persist segment-side inputs. There is no segment-generation LLM today; this file
    is the auditable record of which columns were used and any methodology text.
    """
    lines = [
        "# Customer Segmentation — segment intake",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Segment name source",
        segment_source,
        "",
        "## Resolved segment names (columns)",
        "",
    ]
    for i, name in enumerate(segment_names, start=1):
        lines.append(f"{i}. {name}")
    lines.extend(["", "## Methodology / cowork summary (verbatim)", ""])
    if methodology and methodology.strip():
        lines.append(methodology.strip())
    else:
        lines.append("(none — not provided in cowork_guidance)")
    if raw_cowork_keys:
        lines.extend(["", "## cowork_guidance keys present", ", ".join(raw_cowork_keys)])
    path = session_dir / "segments_intake.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_segments_llm_audit(
    session_dir: Path,
    *,
    segment_source: str,
) -> None:
    """
    Audit file for "segment LLM" requests/responses.

    Current product flow does not call an LLM to generate segment names; this file
    records that explicitly so logs stay complete for reviewers who expect a pair.
    """
    text = f"""# Segment column — LLM prompt / response audit

## Status

**No segment-generation LLM call** in this pipeline run.

Segment names (table columns) are supplied by: **{segment_source}**

## Model prompt (full)

_Not applicable — no request was sent to an LLM solely for segment naming._

Inputs that define the segment axis are recorded in `segments_intake.md` (methodology
verbatim + resolved column names).

## Model response (full)

_Not applicable._
"""
    (session_dir / "segments_llm.md").write_text(text, encoding="utf-8")


def write_cell_llm_log(
    session_dir: Path,
    *,
    row_idx: int,
    col_idx: int,
    segment_name: str,
    row_label: str,
    retrieval_raw_query: str,
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
    parsed_cell_value: str,
    pipe_meta: dict[str, Any] | None = None,
) -> None:
    """One file per cell under ``cells/``."""
    fname = f"r{row_idx:02d}_c{col_idx:02d}_{_slug(segment_name)}.txt"
    path = session_dir / "cells" / fname

    retrieval_lines = ["=== RETRIEVAL (per-cell query → pipeline) ===", f"raw_query: {retrieval_raw_query}"]
    if pipe_meta:
        retrieval_lines.append(f"recalled_count: {pipe_meta.get('recalled_count')}")
        retrieval_lines.append(f"reranked_count: {pipe_meta.get('reranked_count')}")
        retrieval_lines.append(f"query_preview: {pipe_meta.get('query_preview', '')}")
    else:
        retrieval_lines.append("(metadata unavailable)")

    body = (
        f"row_idx: {row_idx}\n"
        f"col_idx: {col_idx}\n"
        f"segment_name: {segment_name}\n"
        f"row_label: {row_label}\n"
        f"parsed_cell_value: {parsed_cell_value}\n"
        "\n"
        + "\n".join(retrieval_lines)
        + "\n\n=== SYSTEM PROMPT ===\n"
        + (system_prompt or "")
        + "\n\n=== USER PROMPT ===\n"
        + (user_prompt or "")
        + "\n\n=== LLM RAW RESPONSE ===\n"
        + (llm_raw_response or "")
        + "\n"
    )
    path.write_text(body, encoding="utf-8")


def logging_enabled() -> bool:
    return (os.getenv("CS_FILL_LOG_DISABLE", "").strip().lower() not in {"1", "true", "yes", "on"})
