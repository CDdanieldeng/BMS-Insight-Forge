"""Render PPTX slides to PNG using matplotlib with BMS-branded table styling."""

from __future__ import annotations

import io
import textwrap
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.table import Table as MplTable

from pptx import Presentation

from fill_engine.pptx_handler import extract_table_as_dict, get_slide_title

# BMS brand-ish palette
_HEADER_BG = "#1B3A5C"
_HEADER_FG = "white"
_INDEX_BG = "#E8EDF2"
_INDEX_FG = "#1B3A5C"
_CELL_BG = "white"
_CELL_FG = "#333333"
_TITLE_COLOR = "#1B3A5C"

# Dynamic figure height constants
_MIN_INCHES_PER_UNIT = 0.22   # physical inches needed per row_unit at 7.5pt font
_TITLE_MARGIN_INCHES = 1.2    # space reserved for title + top/bottom padding
_BASE_FIG_HEIGHT = 7.875      # default figure height (16:9 baseline)
_MAX_FIG_HEIGHT = 24.0        # hard cap to avoid absurdly tall images


def render_slide_to_png(prs: Presentation, slide_idx: int) -> bytes:
    """Render a slide to an in-memory PNG using matplotlib."""
    title = get_slide_title(prs, slide_idx)
    table_data = extract_table_as_dict(prs, slide_idx)

    # Pre-compute layout so we know the required figure height before creating
    # the figure — this is the key to eliminating row overlap.
    layout = _prepare_table_layout(table_data) if table_data is not None else None

    if layout is not None:
        row_units = layout["row_units"]
        required = sum(row_units) * _MIN_INCHES_PER_UNIT + _TITLE_MARGIN_INCHES
        fig_height = min(_MAX_FIG_HEIGHT, max(_BASE_FIG_HEIGHT, required))
    else:
        fig_height = _BASE_FIG_HEIGHT

    fig, ax = plt.subplots(figsize=(14, fig_height))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        0.5, 0.95, title,
        ha="center", va="top",
        fontsize=22, fontweight="bold", color=_TITLE_COLOR,
    )

    if layout is None:
        ax.text(
            0.5, 0.5, "(No table on this slide)",
            ha="center", va="center", fontsize=14, color="#999999",
        )
    else:
        _draw_table(ax, layout)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _wrap_text(text: str, max_chars: int = 30, max_lines: int | None = None) -> str:
    """
    Wrap text to multiple lines for matplotlib table cells.

    Uses hard-wrapping for long tokens (e.g., URLs, codes, CJK text without spaces)
    so a single long chunk cannot overflow and visually overlap neighboring rows.
    If max_lines is given, the result is truncated to that many lines with a
    trailing ellipsis so a runaway cell cannot dominate the table layout.
    """
    if not text:
        return ""

    wrapped_parts: list[str] = []
    for para in str(text).splitlines() or [str(text)]:
        if not para.strip():
            wrapped_parts.append("")
            continue
        wrapped_parts.append(
            textwrap.fill(
                para,
                width=max_chars,
                break_long_words=True,
                break_on_hyphens=False,
            )
        )
    result = "\n".join(wrapped_parts)

    if max_lines is not None:
        lines = result.splitlines()
        if len(lines) > max_lines:
            result = "\n".join(lines[: max_lines - 1]) + "\n\u2026"

    return result


def _estimate_index_col_width(row_index: list[str]) -> float:
    """
    Estimate index-column width ratio (0-1) from label length.

    Keeps width in a safe range so the index column can grow for long labels
    without starving data columns.
    """
    if not row_index:
        return 0.34

    max_chars = max(len((label or "").replace("\n", " ").strip()) for label in row_index)
    # Aggressive widening: prioritize non-overlap in index cells.
    width = 0.34 + max(0, max_chars - 12) * 0.009
    return min(0.58, max(0.34, width))


def _prepare_table_layout(table_data: dict[str, Any]) -> dict[str, Any]:
    """
    Pre-compute all wrapping, column widths, and row_units for a table.

    Separating this from the render step lets `render_slide_to_png` know
    the total row_units *before* the figure is created, so it can size the
    figure to guarantee every row has enough physical space for its text.
    """
    columns = table_data["columns"]
    row_index = table_data["row_index"]
    data = table_data["data"]

    num_cols = max(len(columns), 1)
    table_width = 0.96
    index_col_ratio = _estimate_index_col_width(row_index)
    data_col_ratio = 1.0 - index_col_ratio
    col_widths = (
        [table_width * index_col_ratio]
        + [table_width * data_col_ratio / num_cols] * num_cols
    )

    # Character budgets per column, kept in sync with dynamic widths.
    index_wrap = max(26, int(index_col_ratio * 130))
    data_wrap = max(12, int((data_col_ratio / num_cols) * 98))
    header_wrap = max(10, int((data_col_ratio / num_cols) * 82))

    wrapped_headers = [_wrap_text(col, header_wrap) for col in columns]
    wrapped_index: list[str] = []
    wrapped_data: list[list[str]] = []
    row_units: list[float] = [1.35]  # header row is visibly taller

    for row_label in row_index:
        idx_text = _wrap_text(row_label, index_wrap)
        wrapped_index.append(idx_text)
        row_cells: list[str] = []
        max_lines = max(1, idx_text.count("\n") + 1)
        for col_label in columns:
            cell_text = data.get(row_label, {}).get(col_label, "")
            # max_lines=4 caps any single cell at 4 lines in the PNG preview
            # so one dense cell cannot force all other rows into tiny slivers.
            wrapped = _wrap_text(cell_text, data_wrap, max_lines=4)
            row_cells.append(wrapped)
            max_lines = max(max_lines, wrapped.count("\n") + 1)
        wrapped_data.append(row_cells)
        # 1.05 increment gives each additional wrapped line slightly more than
        # 1 unit, providing breathing room and reducing visual collisions.
        row_units.append(1.0 + (max_lines - 1) * 1.05)

    return {
        "columns": columns,
        "row_index": row_index,
        "data": data,
        "col_widths": col_widths,
        "wrapped_headers": wrapped_headers,
        "wrapped_index": wrapped_index,
        "wrapped_data": wrapped_data,
        "row_units": row_units,
    }


def _draw_table(ax: plt.Axes, layout: dict[str, Any]) -> None:
    col_widths = layout["col_widths"]
    wrapped_headers = layout["wrapped_headers"]
    wrapped_index = layout["wrapped_index"]
    wrapped_data = layout["wrapped_data"]
    row_units = layout["row_units"]
    row_index = layout["row_index"]

    table_height = 0.78
    unit_sum = sum(row_units) if row_units else 1.0
    row_heights = [table_height * u / unit_sum for u in row_units]

    table_top = 0.82
    table_left = 0.02

    tbl = MplTable(ax, bbox=None)

    # Header row
    tbl.add_cell(0, 0, col_widths[0], row_heights[0], text="", loc="center",
                 facecolor=_HEADER_BG, edgecolor="white")
    for ci, col in enumerate(wrapped_headers):
        cell = tbl.add_cell(
            0, ci + 1, col_widths[ci + 1], row_heights[0],
            text=col, loc="center",
            facecolor=_HEADER_BG, edgecolor="white",
        )
        cell.get_text().set_color(_HEADER_FG)
        cell.get_text().set_fontsize(9)
        cell.get_text().set_weight("bold")
        cell.get_text().set_va("center")
        cell.get_text().set_ha("center")

    # Data rows
    for ri, row_label in enumerate(row_index):
        r = ri + 1
        row_height = row_heights[r]
        # Index cell
        idx_cell = tbl.add_cell(
            r, 0, col_widths[0], row_height,
            text=wrapped_index[ri], loc="center",
            facecolor=_INDEX_BG, edgecolor="white",
        )
        idx_cell.get_text().set_color(_INDEX_FG)
        idx_cell.get_text().set_fontsize(7.5)
        idx_cell.get_text().set_weight("bold")
        idx_cell.get_text().set_va("center")
        idx_cell.get_text().set_ha("left")

        for ci in range(len(wrapped_headers)):
            cell = tbl.add_cell(
                r, ci + 1, col_widths[ci + 1], row_height,
                text=wrapped_data[ri][ci], loc="center",
                facecolor=_CELL_BG, edgecolor="#CCCCCC",
            )
            cell.get_text().set_color(_CELL_FG)
            cell.get_text().set_fontsize(7.5)
            cell.get_text().set_va("center")
            cell.get_text().set_ha("center")

    tbl.auto_set_font_size(False)
    ax.add_table(tbl)
    tbl.set_transform(ax.transAxes)

    # Position the table within the axes
    for (row, col), cell in tbl.get_celld().items():
        cell.set_transform(ax.transAxes)
        x = table_left + sum(col_widths[:col])
        y = table_top - sum(row_heights[: row + 1])
        cell.set_x(x)
        cell.set_y(y)
