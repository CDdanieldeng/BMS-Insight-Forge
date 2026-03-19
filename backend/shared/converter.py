"""Convert supported files to markdown using markitdown."""

import re
import tempfile
import time
from pathlib import Path

from shared.logging_config import setup_logging

logger = setup_logging("shared")

# Lazy import to avoid import error if markitdown not installed
_markitdown = None

# Each pattern has tailored flags. Avoid global DOTALL, which can accidentally
# consume content across many slides.
_NOISE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Allow bounded cross-line removal for long legal footer variants.
    (
        re.compile(
            r"No part of it may be circulated[\s\S]{0,800}?approval of ZS\.",
            flags=re.IGNORECASE,
        ),
        "",
    ),
    (re.compile(r"^\s*!\[\]\(Picture.*?\)\s*$", flags=re.IGNORECASE | re.MULTILINE), ""),
    (re.compile(r"^\s*Source:\s*ZS analysis.*$", flags=re.IGNORECASE | re.MULTILINE), ""),
    (re.compile(r"^\s*###\s*Notes:\s*$", flags=re.IGNORECASE | re.MULTILINE), ""),
    (re.compile(r"^\s*#\s*Contents\s*$", flags=re.IGNORECASE | re.MULTILINE), ""),
    (re.compile(r"\bAppendix\b", flags=re.IGNORECASE), ""),
]


def _get_markitdown():
    global _markitdown
    if _markitdown is None:
        try:
            from markitdown import MarkItDown
            _markitdown = MarkItDown()
        except ImportError as e:
            logger.error("markitdown not installed: %s", e)
            raise
    return _markitdown


def _cleanup_temp_file(path: Path) -> None:
    """
    Best-effort cleanup for temp files.
    On Windows, downstream converters can briefly keep the file handle open.
    """
    for i in range(5):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if i == 4:
                logger.warning("Temp file cleanup skipped (file in use): %s", path)
                return
            time.sleep(0.2 * (i + 1))


def clean_text(text: str) -> str:
    """Remove known low-value boilerplate from extracted markdown/text."""
    cleaned = text
    for pattern, replacement in _NOISE_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)

    # Normalize excess blank lines after pattern-based deletions.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def convert_to_markdown(content: bytes, filename: str) -> str:
    """
    Convert uploaded file to markdown text.

    Args:
        content: Raw file bytes
        filename: Original filename (used for extension detection)

    Returns:
        Markdown text content
    """
    ext = Path(filename).suffix.lower()
    if ext == ".md":
        return clean_text(content.decode("utf-8", errors="ignore"))
    if ext not in (".pptx", ".docx", ".doc", ".pdf"):
        raise ValueError(f"Unsupported format: {filename}. Use .pptx/.docx/.doc/.pdf/.md")

    md = _get_markitdown()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        temp_path = Path(f.name)
        try:
            f.write(content)
            f.flush()
            result = md.convert(f.name)
            text = result.text_content if hasattr(result, "text_content") else str(result)
            cleaned_text = clean_text(text)
            logger.info(
                "Converted %s to markdown, raw=%d chars cleaned=%d chars",
                filename,
                len(text),
                len(cleaned_text),
            )
            return cleaned_text
        finally:
            _cleanup_temp_file(temp_path)
