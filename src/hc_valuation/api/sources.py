"""Where every number in the run came from, down to the cell.

The audit chain records *what* a rule did and *which row* it read; this module supplies
the missing half — the workbook, the sheet, and the column letter — so a reviewer can go
straight to `'Q3 2026 Activity'!E18` instead of hunting for it. The column letters are
derived from the ingest schema rather than hardcoded anywhere, so a change to the reader
cannot silently make a reference wrong.

This lives in `api/` because it needs both the ingest column maps and the run. The engine
stays unaware of spreadsheets.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl.utils import get_column_letter

from ..ingest.reader import read_workbook
from ..ingest.schema import ACTIVITY_COLUMNS, PORTFOLIO_COLUMNS
from ..pipeline import PipelineResult

# A step or flag records its inputs by name. This says which workbook column each name was
# read from, so the detail panel can turn "post_money: 3931.0" into a cell reference.
# Names not listed here are computed by the engine and have no cell of their own.
INPUT_COLUMNS: dict[str, tuple[str, str]] = {
    # --- activity tab
    "post_money": ("activity", "Post-Money / Deal Value ($M)"),
    "deal_value": ("activity", "Post-Money / Deal Value ($M)"),
    "ipo_market_cap": ("activity", "Post-Money / Deal Value ($M)"),
    "indicated_post_money": ("activity", "Post-Money / Deal Value ($M)"),
    "hc_investment": ("activity", "HC Investment ($M)"),
    "ownership_after": ("activity", "HC Ownership After (FD %)"),
    "proceeds": ("activity", "Proceeds to HC ($M)"),
    "detail": ("activity", "Detail"),
    "notes": ("activity", "Notes"),
    # --- portfolio tab (the prior close)
    "prior_mark": ("portfolio", "Prior Mark ($M)"),
    "ownership": ("portfolio", "Ownership (FD %)"),
    "ownership_before": ("portfolio", "Ownership (FD %)"),
    "latest_post_money": ("portfolio", "Latest Post-Money ($M)"),
    "prior_post_money": ("portfolio", "Latest Post-Money ($M)"),
    "last_round_post_money": ("portfolio", "Latest Post-Money ($M)"),
    "arr": ("portfolio", "ARR ($M)"),
    "arr_growth": ("portfolio", "ARR Growth (YoY %)"),
    "cash": ("portfolio", "Cash ($M)"),
    "net_burn": ("portfolio", "Net Burn ($M/mo)"),
    "realized": ("portfolio", "Realized ($M)"),
    "invested": ("portfolio", "Invested ($M)"),
    "status": ("portfolio", "Status"),
}


def _letters(columns: dict[str, str]) -> dict[str, str]:
    """Column name -> spreadsheet letter, in the order the reader expects them."""
    return {name: get_column_letter(i) for i, name in enumerate(columns, start=1)}


def build_sources(result: PipelineResult) -> dict[str, Any]:
    cfg, paths = result.config, result.paths
    snapshot, feed = read_workbook(paths.workbook, cfg)

    companies: dict[str, Any] = {}
    for p in snapshot.positions:
        companies[p.company] = {"portfolio_row": p.row_index, "events": []}
    for e in feed.events:
        companies.setdefault(e.company, {"portfolio_row": None, "events": []})
        companies[e.company]["events"].append(
            {"row": e.row_index, "event_type": e.event_type, "date": e.date.isoformat()}
        )

    wb = Path(paths.workbook)
    return {
        "workbook": {
            "name": wb.name,
            "path": str(wb.resolve()),
            "sha256": result.run.manifest.input_sha256,
        },
        "sheets": {"portfolio": snapshot.sheet_name, "activity": feed.sheet_name},
        "columns": {"portfolio": _letters(PORTFOLIO_COLUMNS), "activity": _letters(ACTIVITY_COLUMNS)},
        "input_columns": {k: {"sheet": s, "column": c} for k, (s, c) in INPUT_COLUMNS.items()},
        "companies": companies,
    }


def input_cell_refs(sources: dict[str, Any], company: str, inputs: dict[str, Any],
                    event_row: int | None) -> dict[str, str]:
    """`{input name: "'Q3 2026 Activity'!E18"}` for every input that has a cell — the same
    resolution the review tool does, so the exported Audit Trail cites the same cells."""
    def token(sheet: str) -> str:
        import re
        return sheet if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", sheet) else "'" + sheet.replace("'", "''") + "'"

    out: dict[str, str] = {}
    sheets, cols = sources["sheets"], sources["columns"]
    prow = (sources["companies"].get(company) or {}).get("portfolio_row")
    for name in inputs:
        where = INPUT_COLUMNS.get(name)
        if where is None:
            continue
        tab, header = where
        letter = cols[tab].get(header)
        row = event_row if tab == "activity" else prow
        if letter is None or row is None:
            continue
        out[name] = f"{token(sheets[tab])}!{letter}{row}"
    return out
