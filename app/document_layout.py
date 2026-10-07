"""Consistent Ukrainian report tables: wrap whole words and fit row height.

Used by generated Excel registers, statistics and donor templates.  Excel does
not automatically resize row height for wrapped cells in all viewers, so row
heights are estimated at export time.  Long *words* are not manually broken.
"""
from __future__ import annotations

from copy import copy
from math import ceil
from textwrap import wrap

from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter


def word_lines(value: object, width: int) -> list[str]:
    """Keep words intact; treat explicit newlines as separate lines."""
    if value is None:
        return []
    text = str(value)
    if not text:
        return []
    return [line for paragraph in text.splitlines() for line in
            (wrap(paragraph, width=max(5, width), break_long_words=False,
                  break_on_hyphens=False, replace_whitespace=False) or [""])]


def apply_excel_word_wrap(ws, *, first_row: int = 1, last_row: int | None = None,
                          min_height: float = 17, max_height: float = 409) -> None:
    """Preserve cell styles, wrap on words, grow rows without exceeding Excel limits.

    Do not resize a donor's columns or break long identifiers mid-word.  With
    merged cells the entire merged width is used when estimating line count.
    """
    merged_widths: dict[str, float] = {}
    for area in ws.merged_cells.ranges:
        first = ws.cell(area.min_row, area.min_col)
        merged_widths[first.coordinate] = sum(
            ws.column_dimensions[get_column_letter(col)].width or 13
            for col in range(area.min_col, area.max_col + 1)
        )
    stop = ws.max_row if last_row is None else min(last_row, ws.max_row)
    for row in ws.iter_rows(min_row=first_row, max_row=stop):
        required = 0.0
        for cell in row:
            if isinstance(cell, MergedCell) or cell.value is None:
                continue
            current = copy(cell.alignment)
            current.wrap_text = True
            current.shrink_to_fit = False
            current.vertical = current.vertical or "top"
            cell.alignment = current
            if not isinstance(cell.value, str) or not cell.value.strip():
                continue
            width = merged_widths.get(
                cell.coordinate,
                ws.column_dimensions[get_column_letter(cell.column)].width or 13,
            )
            chars = max(5, int(width - 3))
            lines = word_lines(cell.value, chars)
            # Explicitly account for line breaks and long Cyrillic glyph widths.
            count = sum(max(1, ceil(len(line) / max(chars, 1))) if " " not in line else 1
                        for line in lines)
            font_size = float(cell.font.sz or 11)
            required = max(required, count * (font_size * 1.35 + 2) + 4)
        if required:
            dimension = ws.row_dimensions[row[0].row]
            dimension.height = min(max_height, max(min_height, float(dimension.height or 0), required))


def enable_docx_word_wrap(doc) -> None:
    """Let Word increase row heights and wrap on word boundaries in all tables."""
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml.ns import qn

    for table in doc.tables:
        table.autofit = True
        for row in table.rows:
            row.height = None  # Remove fixed donor-template row heights.
            for cell in row.cells:
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
                tc_pr = cell._tc.get_or_add_tcPr()
                for element in list(tc_pr):
                    if element.tag == qn("w:noWrap"):
                        tc_pr.remove(element)
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.keep_together = False
