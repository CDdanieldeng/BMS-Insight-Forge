"""
Rasterize a whole PPTX slide to PNG (true visual snapshot), not a redrawn table.

Uses LibreOffice headless (pptx → PDF) and PyMuPDF to render the PDF page at
the given DPI. If LibreOffice or PyMuPDF is unavailable, returns None so the
caller can fall back to matplotlib-based preview.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_soffice() -> str | None:
    for key in ("SOFFICE_PATH", "LIBREOFFICE_PATH"):
        env = os.environ.get(key)
        if env and os.path.isfile(env):
            return env
    w = shutil.which("soffice")
    if w:
        return w
    mac = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if os.path.isfile(mac):
        return mac
    if sys.platform == "win32":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ):
            win_path = os.path.join(base, "LibreOffice", "program", "soffice.exe")
            if os.path.isfile(win_path):
                return win_path
    return None


def rasterize_pptx_slide_to_png(
    pptx_bytes: bytes,
    slide_idx: int,
    dpi: int = 144,
    timeout_s: int = 120,
) -> bytes | None:
    """
    Return PNG bytes for slide ``slide_idx`` (0-based), or None on failure / missing tools.
    """
    if slide_idx < 0 or not pptx_bytes:
        return None

    soffice = _resolve_soffice()
    if not soffice:
        logger.info("soffice not found; use matplotlib slide preview or set SOFFICE_PATH")
        return None

    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.info("PyMuPDF (fitz) not installed; cannot rasterize slide")
        return None

    with tempfile.TemporaryDirectory(prefix="if_raster_") as tmp:
        tmp_path = Path(tmp)
        pptx_path = tmp_path / f"{uuid.uuid4().hex}.pptx"
        pptx_path.write_bytes(pptx_bytes)
        out_dir = tmp_path / "pdf_out"
        out_dir.mkdir()

        cmd = [
            soffice,
            "--headless",
            "--invisible",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(pptx_path),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=timeout_s,
            )
        except FileNotFoundError:
            logger.warning("soffice binary missing at %s", soffice)
            return None
        except subprocess.CalledProcessError as e:
            logger.warning(
                "LibreOffice pptx->pdf failed (exit %s): %s",
                e.returncode,
                (e.stderr or e.stdout or b"")[:500],
            )
            return None
        except subprocess.TimeoutExpired:
            logger.warning("LibreOffice pptx->pdf timed out after %ss", timeout_s)
            return None

        pdfs = sorted(out_dir.glob("*.pdf"))
        if not pdfs:
            logger.warning("LibreOffice produced no PDF in %s", out_dir)
            return None

        pdf_path = pdfs[0]
        doc = None
        try:
            doc = fitz.open(pdf_path)
            if slide_idx >= doc.page_count:
                logger.warning(
                    "slide_idx %s >= PDF page count %s",
                    slide_idx,
                    doc.page_count,
                )
                return None
            page = doc.load_page(slide_idx)
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            return pix.tobytes("png")
        except Exception as e:
            logger.warning("PyMuPDF rasterize failed: %s", e)
            return None
        finally:
            if doc is not None:
                doc.close()
