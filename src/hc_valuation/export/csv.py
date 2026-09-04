"""CSV exports — the same tables as the workbook, for anyone who would rather use pandas."""
from __future__ import annotations

import csv as _csv
from pathlib import Path

from ..engine.models import ValuationRun
from .tables import Table, audit_table, exceptions_table, marks_table, open_items_table

FILES: dict[str, callable] = {
    "marks.csv": marks_table,
    "exceptions.csv": exceptions_table,
    "audit_trail.csv": audit_table,
    "open_items.csv": open_items_table,
}


def _write(table: Table, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(table.headers)
        for row in table.rows:
            w.writerow(["" if v is None else v for v in row])


def write_csvs(run: ValuationRun, directory: str | Path) -> list[Path]:
    """Write marks / exceptions / audit_trail / open_items CSVs into `directory`."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, builder in FILES.items():
        p = d / name
        _write(builder(run), p)
        written.append(p)
    return written
