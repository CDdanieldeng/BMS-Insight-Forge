"""Render PPTX slides to PNG using matplotlib with BMS-branded table styling."""

from __future__ import annotations

import io
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


def render_slide_to_png(prs: Presentation, slide_idx: int) -> bytes:
    """Render a slide to an in-memory PNG using matplotlib."""
    title = get_slide_title(prs, slide_idx)
    table_data = extract_table_as_dict(prs, slide_idx)

    fig, ax = plt.subplots(figsize=(14, 7.875))  # 16:9 ratio
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        0.5, 0.95, title,
        ha="center", va="top",
        fontsize=22, fontweight="bold", color=_TITLE_COLOR,
    )

    if table_data is None:
        ax.text(
            0.5, 0.5, "(No table on this slide)",
            ha="center", va="center", fontsize=14, color="#999999",
        )
    else:
        _draw_table(ax, table_data)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _wrap_text(text: str, max_chars: int = 30) -> str:
    """Insert newlines so no line exceeds max_chars."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return "\n".join(lines)


def _draw_table(ax: plt.Axes, table_data: dict[str, Any]) -> None:
    columns = table_data["columns"]
    row_index = table_data["row_index"]
    data = table_data["data"]

    n_rows = len(row_index) + 1  # +1 for header
    n_cols = len(columns) + 1    # +1 for row-index column

    num_cols = max(len(columns), 1)
    col_widths = [0.22] + [0.78 / num_cols] * num_cols
    header_wrap = 18
    index_wrap = 20
    data_wrap = 24

    # Dynamic row heights to avoid text overlapping between rows.
    wrapped_headers = [_wrap_text(col, header_wrap) for col in columns]
    wrapped_index: list[str] = []
    wrapped_data: list[list[str]] = []
    row_units: list[float] = [1.15]  # header row gets a bit more room

    for row_label in row_index:
        idx_text = _wrap_text(row_label, index_wrap)
        wrapped_index.append(idx_text)
        row_cells: list[str] = []
        max_lines = max(1, idx_text.count("\n") + 1)
        for col_label in columns:
            cell_text = data.get(row_label, {}).get(col_label, "")
            wrapped = _wrap_text(cell_text, data_wrap)
            row_cells.append(wrapped)
            max_lines = max(max_lines, wrapped.count("\n") + 1)
        wrapped_data.append(row_cells)
        # 1 line baseline + incremental room for wrapped lines
        row_units.append(1.0 + (max_lines - 1) * 0.55)

    table_height = 0.74
    unit_sum = sum(row_units) if row_units else 1.0
    row_heights = [table_height * u / unit_sum for u in row_units]

    table_top = 0.82
    table_left = 0.02

    tbl = MplTable(ax, bbox=None)

    # Header row
    tbl.add_cell(0, 0, col_widths[0], row_heights[0], text="", loc="center",
                 facecolor=_HEADER_BG, edgecolor="white")
    for ci, col in enumerate(columns):
        cell = tbl.add_cell(
            0, ci + 1, col_widths[ci + 1], row_heights[0],
            text=wrapped_headers[ci], loc="center",
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
        idx_cell.get_text().set_fontsize(8)
        idx_cell.get_text().set_weight("bold")
        idx_cell.get_text().set_va("center")
        idx_cell.get_text().set_ha("center")

        for ci, col_label in enumerate(columns):
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
