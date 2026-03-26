"""Python-pptx fill engine: extract table structure and fill tables."""

import io
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Pt

from shared.logging_config import setup_logging

from fill_engine.swot_placeholder_fill import slide_has_swot_placeholders

logger = setup_logging("fill_engine")

# Project root: parent of backend/ (fill_engine is backend/fill_engine/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_pptx_path(path: str | Path) -> Path:
    """Resolve pptx path: if relative and not found from cwd, try project root."""
    p = Path(path)
    if p.is_absolute() and p.exists():
        return p
    if p.exists():
        return p.resolve()
    # Backend often runs from backend/, so relative paths like example_files/... fail
    root_path = _PROJECT_ROOT / p
    if root_path.exists():
        logger.debug("Resolved path %s -> %s", p, root_path)
        return root_path.resolve()
    return p.resolve()  # Let caller get FileNotFoundError

# Placeholder patterns that indicate a cell is blank/fillable
BLANK_PATTERNS = ("", "—", "-", "TBD", "tbd", "N/A", "n/a", " ")

# Canonical module names in separator slides and accepted aliases.
MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "Customer Segmentation": ("Customer Segmentation",),
    "SWOT Analysis": ("SWOT Analysis", "SWOT"),
    "Messaging Strategy": ("Messaging Strategy",),
}


def _is_blank(text: str) -> bool:
    """Check if cell text is considered blank/fillable."""
    t = (text or "").strip()
    return not t or t in BLANK_PATTERNS


def _normalize_text(text: str) -> str:
    """
    Collapse all whitespace variants (space, \n, \r, \t, \x0b, \x0c) into a
    single space so that module names like 'Messaging\x0bStrategy' still match
    'Messaging Strategy' as stored in MODULE_NAMES.
    """
    import re
    return re.sub(r"\s+", " ", text).strip()


def _get_slide_text(slide) -> str:
    """Extract all text from a slide for module detection."""
    parts = []
    for shape in slide.shapes:
        if hasattr(shape, "text") and shape.text:
            parts.append(_normalize_text(shape.text))
    return " ".join(parts)


def _detect_module(slide) -> str | None:
    """Detect module name from slide text (for separators)."""
    text = _normalize_text(_get_slide_text(slide)).lower()
    for canonical_name, aliases in MODULE_ALIASES.items():
        for alias in aliases:
            if _normalize_text(alias).lower() in text:
                return canonical_name
    return None


def load_presentation(pptx_bytes: bytes | None = None, pptx_path: str | Path | None = None) -> Presentation:
    """Load a presentation from bytes or file path."""
    if pptx_bytes is not None:
        return Presentation(io.BytesIO(pptx_bytes))
    if pptx_path is not None:
        path = _resolve_pptx_path(pptx_path)
        if not path.exists():
            raise FileNotFoundError(f"Presentation not found: {path}")
        return Presentation(str(path))
    raise ValueError("Provide pptx_bytes or pptx_path")


def read_presentation_bytes(pptx_path: str | Path) -> bytes:
    """Read a .pptx from disk (same path resolution as load_presentation)."""
    path = _resolve_pptx_path(pptx_path)
    if not path.is_file():
        raise FileNotFoundError(f"Presentation not found: {path}")
    return path.read_bytes()


def get_slide_info(pptx_bytes: bytes | None = None, pptx_path: str | Path | None = None) -> list[dict[str, Any]]:
    """
    Parse pptx and return slide metadata: idx, is_fillable, module, table_structure.

    Separator slides: have module name text, no table.
    Fillable slides: have exactly one table.
    """
    prs = load_presentation(pptx_bytes=pptx_bytes, pptx_path=pptx_path)
    result = []
    current_module: str | None = None

    for idx, slide in enumerate(prs.slides):
        module = _detect_module(slide)
        if module:
            current_module = module

        tables = [s for s in slide.shapes if s.has_table]
        is_fillable = len(tables) == 1

        # Temporary: detect SWOT placeholder template (placeholders instead of table)
        is_swot_placeholder = (
            current_module == "SWOT Analysis"
            and slide_has_swot_placeholders(slide)
            and len(tables) == 0
        )
        if is_swot_placeholder:
            is_fillable = True

        entry = {
            "idx": idx,
            "is_fillable": is_fillable,
            "module": current_module or "Unknown",
        }
        if is_swot_placeholder:
            entry["is_swot_placeholder_template"] = True
            entry["table_structure"] = {
                "columns": ["Strengths", "Weaknesses", "Opportunities", "Threats"],
                "indexes": [],
            }
        elif is_fillable and tables:
            structure = _extract_table_structure(tables[0].table)
            if current_module == "SWOT Analysis":
                structure = dict(structure)
                structure["indexes"] = []
            entry["table_structure"] = structure

        result.append(entry)
        logger.info(
            "Slide %d: is_fillable=%s, module=%s",
            idx,
            is_fillable,
            entry["module"],
            extra={"slide_idx": idx},
        )

    return result


def _extract_table_structure(table) -> dict[str, Any]:
    """Extract columns (header row), indexes (first column), and title from table."""
    rows = list(table.rows)
    cols = list(table.columns)
    if not rows or not cols:
        return {"columns": [], "indexes": [], "title": ""}

    # Row 0 = column headers (first cell may be empty/corner)
    columns = [table.cell(0, c).text.strip() for c in range(len(cols))]
    # Row 1+ first column = row indexes
    indexes = [table.cell(r, 0).text.strip().replace("\n", " ") for r in range(1, len(rows))]

    # Use first non-empty column as title hint, or first row first cell
    title = columns[0] if columns[0] else (indexes[0] if indexes else "")

    return {
        "columns": columns,
        "indexes": indexes,
        "title": title,
        "num_rows": len(rows),
        "num_cols": len(cols),
    }


def get_table_structure(
    pptx_bytes: bytes | None = None,
    pptx_path: str | Path | None = None,
    slide_idx: int = 0,
) -> dict[str, Any]:
    """
    Get table structure for a specific slide: columns, indexes, title.
    """
    prs = load_presentation(pptx_bytes=pptx_bytes, pptx_path=pptx_path)
    if slide_idx < 0 or slide_idx >= len(prs.slides):
        raise ValueError(f"Invalid slide_idx: {slide_idx}")

    slide = prs.slides[slide_idx]
    for shape in slide.shapes:
        if shape.has_table:
            structure = _extract_table_structure(shape.table)
            logger.info(
                "Table structure for slide %d: %d cols, %d rows",
                slide_idx,
                structure["num_cols"],
                structure["num_rows"],
                extra={"slide_idx": slide_idx},
            )
            return structure

    raise ValueError(f"Slide {slide_idx} has no table")


_FONT_BODY = "Trebuchet MS"
_COLOR_BLACK = RGBColor(0, 0, 0)
_COLOR_SEGMENT = RGBColor(190, 43, 187)


def _apply_cell_font(cell, size_pt: int, color: RGBColor) -> None:
    """Apply font name, size, and colour to every run in a cell's text frame."""
    for para in cell.text_frame.paragraphs:
        for run in para.runs:
            run.font.name = _FONT_BODY
            run.font.size = Pt(size_pt)
            run.font.color.rgb = color


def fill_table(
    pptx_bytes: bytes,
    slide_idx: int,
    table_data: list[list[str]],
    column_headers: list[str] | None = None,
    *,
    has_index_column: bool = True,
) -> bytes:
    """
    Fill table cells with table_data and (optionally) replace column headers.

    column_headers: real segment names that replace placeholder header cells.
    table_data:     2-D list of cell values.
    has_index_column: If True (default), col 0 is row-label corner; headers/data
                      go to cols 1+. If False (e.g. SWOT), all cols are data; use 0-based.
    """
    prs = load_presentation(pptx_bytes=pptx_bytes)
    if slide_idx < 0 or slide_idx >= len(prs.slides):
        raise ValueError(f"Invalid slide_idx: {slide_idx}")

    header_col_offset = 1 if has_index_column else 0
    data_col_offset = 1 if has_index_column else 0

    slide = prs.slides[slide_idx]
    for shape in slide.shapes:
        if shape.has_table:
            tbl = shape.table
            num_rows = len(tbl.rows)
            num_cols = len(tbl.columns)

            # ── Write column headers ─────────────────────────────────────
            if column_headers:
                for c, header in enumerate(column_headers):
                    col_idx = c + header_col_offset
                    if col_idx >= num_cols:
                        break
                    cell = tbl.cell(0, col_idx)
                    cell.text = str(header).strip()
                    _apply_cell_font(cell, 16, _COLOR_SEGMENT)
                    logger.debug(
                        "Set header cell (0,%d) = %r",
                        col_idx,
                        header,
                        extra={"slide_idx": slide_idx},
                    )

            # ── Write data cells (rows 1+) ─────────────────────────────────
            for r, row_data in enumerate(table_data):
                data_row_idx = r + 1  # skip header row
                if data_row_idx >= num_rows:
                    break
                for c, value in enumerate(row_data):
                    data_col_idx = c + data_col_offset
                    if data_col_idx >= num_cols:
                        break
                    cell = tbl.cell(data_row_idx, data_col_idx)
                    cell.text = str(value).strip() if value else ""
                    _apply_cell_font(cell, 9, _COLOR_BLACK)
                    logger.debug(
                        "Filled cell (%d,%d) with %r",
                        data_row_idx,
                        data_col_idx,
                        value[:50] if value else "",
                        extra={"slide_idx": slide_idx},
                    )

            output = io.BytesIO()
            prs.save(output)
            output.seek(0)
            logger.info(
                "Filled table on slide %d: %d data rows, column_headers=%s",
                slide_idx,
                len(table_data),
                column_headers,
                extra={"slide_idx": slide_idx},
            )
            return output.read()

    raise ValueError(f"Slide {slide_idx} has no table")
