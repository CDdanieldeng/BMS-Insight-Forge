"""Convert pptx/docx to markdown using markitdown."""

import io
import tempfile
import time
from pathlib import Path

from shared.logging_config import setup_logging

logger = setup_logging("retriever")

# Lazy import to avoid import error if markitdown not installed
_markitdown = None


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


def convert_to_markdown(content: bytes, filename: str) -> str:
    """
    Convert uploaded file (pptx or docx) to markdown text.

    Args:
        content: Raw file bytes
        filename: Original filename (used for extension detection)

    Returns:
        Markdown text content
    """
    ext = Path(filename).suffix.lower()
    if ext not in (".pptx", ".docx", ".doc"):
        raise ValueError(f"Unsupported format: {filename}. Use .pptx or .docx")

    md = _get_markitdown()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        temp_path = Path(f.name)
        try:
            f.write(content)
            f.flush()
            result = md.convert(f.name)
            text = result.text_content if hasattr(result, "text_content") else str(result)
            logger.info("Converted %s to markdown, %d chars", filename, len(text))
            return text
        finally:
            _cleanup_temp_file(temp_path)
