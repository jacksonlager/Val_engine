"""Review workbook: the run laid out the way a valuation committee reads it.

Deterministic by construction — the only timestamp in the file is the manifest's
`generated_at`, which the caller controls. Two runs over the same input produce
byte-comparable sheets.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..engine.models import ValuationRun
from .tables import DATE, INT, MULT, MUSD, NUM, PCT, TEXT, Table, all_tables, summary_rows

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
FORMATS = {MUSD: "0.00", PCT: "0.0%", MULT: '0.00"x"', NUM: "0.00", INT: "0", TEXT: "General", DATE: "yyyy-mm-dd"}
MIN_WIDTH, MAX_WIDTH = 8, 60


def _style_header(ws, ncols: int) -> None:
    for i in range(1, ncols + 1):
        cell = ws.cell(row=1, column=i)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _autosize(ws, headers: list[str], rows: list[list], kinds: list[str]) -> None:
    for i, h in enumerate(headers, start=1):
        longest = len(h)
        for r in rows[:200]:   # sample; enough to size sensibly without scanning everything
            v = r[i - 1]
            if v is not None:
                longest = max(longest, len(f"{v:.2f}") if isinstance(v, float) else len(str(v)))
        width = min(MAX_WIDTH, max(MIN_WIDTH, longest + 2))
        if kinds[i - 1] == TEXT and longest > 40:
            width = MAX_WIDTH
        ws.column_dimensions[get_column_letter(i)].width = width


def _write_table(wb: Workbook, table: Table) -> None:
    ws = wb.create_sheet(table.name)
    ws.append(table.headers)
    for row in table.rows:
        ws.append(row)
    for j, kind in enumerate(table.kinds, start=1):
        fmt = FORMATS[kind]
        for i in range(2, len(table.rows) + 2):
            c = ws.cell(row=i, column=j)
            c.number_format = fmt
            if kind == TEXT and isinstance(c.value, str) and len(c.value) > 60:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    _style_header(ws, len(table.headers))
    _autosize(ws, table.headers, table.rows, table.kinds)
    ws.auto_filter.ref = ws.dimensions


def _write_summary(wb: Workbook, run: ValuationRun) -> None:
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Item", "Value"])
    for label, value, kind in summary_rows(run):
        ws.append([label, value])
        ws.cell(row=ws.max_row, column=2).number_format = FORMATS[kind]
        if kind == TEXT:
            ws.cell(row=ws.max_row, column=2).alignment = Alignment(horizontal="left")
    _style_header(ws, 2)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 70


def write_workbook(run: ValuationRun, path: str | Path) -> Path:
    """Write the review workbook and return its path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    _write_summary(wb, run)
    for table in all_tables(run):
        _write_table(wb, table)
    wb.save(out)
    return out
