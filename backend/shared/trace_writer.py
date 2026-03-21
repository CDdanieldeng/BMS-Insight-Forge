"""Unified trace file writing for LLM prompt/response debugging and auditing."""

import re
import time
import uuid
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

logger = setup_logging("generation")

_BASE_DIR = Path(__file__).resolve().parents[1]
_KEY_ANSWERS_TRACE_DIR = _BASE_DIR / "logs" / "key_question_llm"
_FILL_TRACE_DIR = _BASE_DIR / "logs" / "slide_fill_llm"
_SEGMENT_HEADER_TRACE_DIR = _BASE_DIR / "logs" / "segment_header_extraction_llm"


def _module_slug(module: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (module or "").strip().lower()).strip("_")
    return slug or "module"


def _write_trace(
    *,
    trace_dir: Path,
    file_suffix: str,
    header_lines: list[str],
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
    log_msg: str,
    log_extra: tuple[Any, ...],
) -> None:
    """Generic trace file writer."""
    try:
        trace_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{file_suffix}_{uuid.uuid4().hex[:8]}.txt"
        file_path = trace_dir / file_name

        header = "\n".join(str(h) for h in header_lines) + "\n"
        text = (
            header
            + "\n=== SYSTEM PROMPT ===\n"
            + (system_prompt or "")
            + "\n\n=== USER PROMPT ===\n"
            + (user_prompt or "")
            + "\n\n=== LLM RAW RESPONSE ===\n"
            + (llm_raw_response or "")
            + "\n"
        )
        file_path.write_text(text, encoding="utf-8")
        logger.info(log_msg, *(*log_extra, file_path))
    except Exception as e:
        logger.warning("Failed to write trace file: %s", e)


def write_key_answers_trace(
    *,
    module: str,
    questions: list[str],
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
) -> None:
    """
    Persist key-question LLM trace to a text file for debugging/auditing.
    Includes questions, full prompts, and raw model output.
    """
    slug = _module_slug(module)
    questions_block = "\n".join(f"- {q}" for q in questions) if questions else "(none)"
    header = [
        f"module: {module}",
        f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"questions_count: {len(questions)}",
        "",
        "=== KEY BUSINESS QUESTIONS ===",
        questions_block,
    ]
    _write_trace(
        trace_dir=_KEY_ANSWERS_TRACE_DIR,
        file_suffix=slug,
        header_lines=header,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        llm_raw_response=llm_raw_response,
        log_msg="Key answers trace file written module=%s path=%s",
        log_extra=(module,),
    )


def write_fill_trace(
    *,
    slide_idx: int,
    module: str,
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
) -> None:
    """Persist fill trace for debugging LLM prompt/response."""
    slug = _module_slug(module)
    header = [
        f"module: {module}",
        f"slide_idx: {slide_idx}",
        f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    file_suffix = f"{slug}_slide{slide_idx}"
    _write_trace(
        trace_dir=_FILL_TRACE_DIR,
        file_suffix=file_suffix,
        header_lines=header,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        llm_raw_response=llm_raw_response,
        log_msg="Fill trace file written module=%s slide_idx=%d path=%s",
        log_extra=(module, slide_idx),
    )


def write_segment_header_trace(
    *,
    module: str,
    n_segments: int,
    system_prompt: str,
    user_prompt: str,
    llm_raw_response: str,
) -> None:
    """Persist segment-header extraction prompt/response for debugging."""
    slug = _module_slug(module)
    header = [
        f"module: {module}",
        f"segments_requested: {n_segments}",
        f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    file_suffix = f"{slug}_segments{n_segments}"
    _write_trace(
        trace_dir=_SEGMENT_HEADER_TRACE_DIR,
        file_suffix=file_suffix,
        header_lines=header,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        llm_raw_response=llm_raw_response,
        log_msg="Segment header trace file written module=%s segments=%d path=%s",
        log_extra=(module, n_segments),
    )
