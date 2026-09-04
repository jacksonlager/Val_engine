"""Quarter-over-quarter mark history per company — the archive the review tool charts.

The engine values one quarter at a time and never looks back; the *archive* is assembled
here, at read time, from what is already on disk. Nothing is invented: a company's
history is exactly the set of quarters something recorded a booked mark for.

Three sources, merged by (company, quarter), in ascending authority:

1. `data/mark_history.yaml` — an optional backfill HC fills from its own records for the
   quarters before the engine's first run. Tagged `backfill`. Shipped empty.
2. `data/published/<slug>.json` — the publish ledger. Every quarter released to executives
   contributes one point per company: the booked mark that was actually shown. Tagged
   `published`. A re-publish replaces the point (the superseded snapshot moves to
   `history/` and is not read here). This is what makes the archive grow one quarter at a
   time without anyone maintaining it.
3. The current run. Its `prior_mark` is the previous quarter's close as the workbook
   carried it, so it fills the previous quarter when nothing else has (tagged `prior`);
   when a published point exists for that quarter it wins, and a disagreement beyond the
   policy tolerance is noted on the point rather than hidden. The current quarter is
   always the live run (tagged `published` when a snapshot with the same run id or the
   same booked mark exists, else `live` — i.e. not yet released, or changed since).

The JSON shape (`GET /api/history`, inlined as `window.__HC_HISTORY__` by `build`):

    {
      "as_of_quarter": "Q3 2026",
      "quarters": ["Q2 2026", "Q3 2026"],            # every quarter any company has a point for
      "counts": {"backfill": 0, "published": 0, "prior": 24, "live": 24},
      "backfill_file": "data/mark_history.yaml" | null,   # present only when the file has points
      "errors": [],                                   # a malformed backfill file is reported, not fatal
      "companies": {
        "Aravine": [
          {"quarter": "Q2 2026", "slug": "2026Q2", "mark": 6.9, "invested": 6.0, "realized": 0.0,
           "moic": 1.15, "status": "Active", "disposition": null, "source": "prior",
           "overridden": false, "run_id": null, "published_at": null, "note": null},
          ...
        ]
      }
    }

Points are sorted by quarter. `mark` is the booked mark ($M) — after any override —
because that is the number the book carried; `overridden` says when it differs from the
engine's proposal. `moic` is (mark + realized) / invested, null when nothing was invested.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from ..engine.models import ValuationRun
from .publish import published_dir

_QUARTER_RX = re.compile(r"^\s*Q([1-4])\s+(\d{4})\s*$")
_BACKFILL_KEYS = {"quarter", "mark", "invested", "realized", "status", "note"}
BACKFILL_FILE = Path("data") / "mark_history.yaml"
SOURCE_RANK = {"backfill": 0, "prior": 1, "published": 2, "live": 3}


# ---------------------------------------------------------------- quarter labels

def quarter_key(label: str) -> int:
    """'Q3 2026' -> 8107; sorts chronologically. Raises on anything else."""
    m = _QUARTER_RX.match(label)
    if not m:
        raise ValueError(f"quarter label {label!r} is not of the form 'Qn YYYY'")
    return int(m.group(2)) * 4 + int(m.group(1)) - 1


def quarter_label(key: int) -> str:
    return f"Q{key % 4 + 1} {key // 4}"


def previous_quarter_label(label: str) -> str:
    """'Q1 2027' -> 'Q4 2026'. Parsed, never typed."""
    return quarter_label(quarter_key(label) - 1)


def quarter_slug(label: str) -> str:
    k = quarter_key(label)
    return f"{k // 4}Q{k % 4 + 1}"


# ---------------------------------------------------------------- points

def _moic(mark: float | None, realized: float | None, invested: float | None) -> float | None:
    if mark is None or invested is None or invested <= 0:
        return None
    return round((mark + (realized or 0.0)) / invested, 4)


def _point(quarter: str, mark: float, source: str, *, invested: float | None = None, realized: float | None = None,
           status: str | None = None, disposition: str | None = None, overridden: bool = False,
           run_id: str | None = None, published_at: str | None = None, note: str | None = None) -> dict[str, Any]:
    return {
        "quarter": quarter, "slug": quarter_slug(quarter), "mark": round(float(mark), 6),
        "invested": None if invested is None else round(float(invested), 6),
        "realized": None if realized is None else round(float(realized), 6),
        "moic": _moic(mark, realized, invested),
        "status": status, "disposition": disposition, "source": source, "overridden": overridden,
        "run_id": run_id, "published_at": published_at, "note": note,
    }


def _company_point(c: dict[str, Any], quarter: str, source: str, run_id: str | None,
                   published_at: str | None) -> dict[str, Any]:
    """A point from a serialised CompanyResult (published snapshot or the live run)."""
    return _point(
        quarter, c["booked_mark"], source,
        invested=c.get("invested_after"), realized=c.get("realized_cumulative"),
        status=c.get("status_after"), disposition=c.get("disposition"),
        overridden=c.get("override") is not None, run_id=run_id, published_at=published_at,
    )


# ---------------------------------------------------------------- sources

def load_backfill(path: Path) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
    """`data/mark_history.yaml` -> {company: {quarter: point}} plus the problems found.

    Strict on shape (an unknown key or a bad quarter label is an error naming the entry) but
    never fatal: a broken file yields no points and one error line, and the rest of the
    history still renders."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    errors: list[str] = []
    if not path.exists():
        return out, errors
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        return out, [f"{path.name}: not valid YAML ({exc})"]
    if not isinstance(raw, dict):
        return out, [f"{path.name}: expected a mapping with a `companies` key"]
    companies = raw.get("companies") or {}
    if not isinstance(companies, dict):
        return out, [f"{path.name}: `companies` must be a mapping of company name -> list of quarters"]
    for company, entries in companies.items():
        if not isinstance(entries, list):
            errors.append(f"{path.name}: {company}: expected a list of quarter entries")
            continue
        for i, e in enumerate(entries, start=1):
            where = f"{path.name}: {company} entry {i}"
            if not isinstance(e, dict):
                errors.append(f"{where}: expected a mapping")
                continue
            unknown = set(e) - _BACKFILL_KEYS
            if unknown:
                errors.append(f"{where}: unknown key(s) {sorted(unknown)}; allowed {sorted(_BACKFILL_KEYS)}")
                continue
            try:
                q = quarter_label(quarter_key(str(e.get("quarter", ""))))
                mark = float(e["mark"])
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{where}: needs `quarter: Qn YYYY` and a numeric `mark` ({exc})")
                continue
            try:
                invested = None if e.get("invested") is None else float(e["invested"])
                realized = None if e.get("realized") is None else float(e["realized"])
            except (TypeError, ValueError):
                errors.append(f"{where}: `invested` and `realized` must be numbers when given")
                continue
            out.setdefault(str(company), {})[q] = _point(
                q, mark, "backfill", invested=invested, realized=realized,
                status=None if e.get("status") is None else str(e["status"]),
                note=None if e.get("note") is None else str(e["note"]),
            )
    return out, errors


def load_published_points(root: Path) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
    """One point per company per published quarter, from the current snapshot of each."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    errors: list[str] = []
    d = published_dir(root)
    if not d.exists():
        return out, errors
    for p in sorted(d.glob("*.json")):
        if p.name == "latest.json":
            continue
        try:
            raw = json.loads(p.read_text())
            rec, run = raw["publish"], raw["run"]
            quarter = quarter_label(quarter_key(rec["quarter"]))
            for c in run["companies"]:
                out.setdefault(c["company"], {})[quarter] = _company_point(
                    c, quarter, "published", rec.get("run_id"), rec.get("published_at"))
        except Exception as exc:  # noqa: BLE001 - one corrupt snapshot must not blank the archive
            errors.append(f"published/{p.name}: unreadable ({exc})")
    return out, errors


# ---------------------------------------------------------------- assembly

def build_history(run: ValuationRun, root: Path, *, backfill_path: Path | None = None,
                  tolerance_musd: float = 0.01) -> dict[str, Any]:
    """The `/api/history` payload. See the module docstring for the contract."""
    root = Path(root)
    backfill_path = backfill_path if backfill_path is not None else root / BACKFILL_FILE
    backfill, errors = load_backfill(backfill_path)
    published, perr = load_published_points(root)
    errors += perr

    current = quarter_label(quarter_key(run.manifest.quarter_label))
    previous = previous_quarter_label(current)
    live_run_id = run.manifest.run_id
    run_json = json.loads(run.model_dump_json())
    live_by_company = {c["company"]: c for c in run_json["companies"]}

    merged: dict[str, dict[str, dict[str, Any]]] = {}
    for src in (backfill, published):
        for company, by_q in src.items():
            for q, pt in by_q.items():
                have = merged.setdefault(company, {}).get(q)
                if have is None or SOURCE_RANK[pt["source"]] >= SOURCE_RANK[have["source"]]:
                    merged[company][q] = pt

    for company, c in live_by_company.items():
        by_q = merged.setdefault(company, {})
        # previous quarter: the workbook's Prior Mark, unless the archive already has that close
        prior_realized = float(c.get("realized_cumulative", 0.0)) - float(c.get("realized_quarter", 0.0))
        prior_pt = _point(previous, c["prior_mark"], "prior", invested=c.get("invested_before"),
                          realized=prior_realized, status=c.get("status_before"))
        have = by_q.get(previous)
        if have is None or SOURCE_RANK[have["source"]] < SOURCE_RANK["prior"]:
            if have is not None and abs(float(have["mark"]) - float(c["prior_mark"])) > tolerance_musd:
                prior_pt["note"] = (f"{have['source']} entry ${float(have['mark']):.3f}M differs from the workbook's "
                                    f"Prior Mark ${float(c['prior_mark']):.3f}M, which is what this run started from")
            by_q[previous] = prior_pt
        elif abs(float(have["mark"]) - float(c["prior_mark"])) > tolerance_musd:
            have["note"] = (f"{have['source']} mark ${float(have['mark']):.3f}M differs from the workbook's "
                            f"Prior Mark ${float(c['prior_mark']):.3f}M that this run started from")
        # current quarter: always the live run; published only when the ledger agrees
        pub = published.get(company, {}).get(current)
        same = pub is not None and (pub.get("run_id") == live_run_id
                                    or abs(float(pub["mark"]) - float(c["booked_mark"])) <= tolerance_musd)
        pt = _company_point(c, current, "published" if same else "live", live_run_id, pub.get("published_at") if same else None)
        if pub is not None and not same:
            pt["note"] = (f"published ${float(pub['mark']):.3f}M on {str(pub.get('published_at') or '')[:10]}; "
                          f"the live run now books ${float(c['booked_mark']):.3f}M and has not been re-published")
        by_q[current] = pt

    companies = {name: sorted(by_q.values(), key=lambda p: quarter_key(p["quarter"]))
                 for name, by_q in sorted(merged.items())}
    quarters = sorted({p["quarter"] for pts in companies.values() for p in pts}, key=quarter_key)
    counts = {k: 0 for k in SOURCE_RANK}
    for pts in companies.values():
        for p in pts:
            counts[p["source"]] += 1
    return {
        "as_of_quarter": current,
        "quarters": quarters,
        "counts": counts,
        "backfill_file": str(backfill_path.relative_to(root)) if backfill and backfill_path.is_relative_to(root)
        else (str(backfill_path) if backfill else None),
        "errors": errors,
        "companies": companies,
    }


def history_rows(history: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    """The archive as a flat table (`mark_history.csv`): one row per company per quarter."""
    headers = ["Company", "Quarter", "Booked Mark ($M)", "Invested ($M)", "Realized ($M)", "MOIC (x)", "Status",
               "Disposition", "Source", "Overridden", "Run ID", "Published At", "Note"]
    rows: list[list[Any]] = []
    for company, pts in history["companies"].items():
        for p in pts:
            rows.append([company, p["quarter"], p["mark"], p["invested"], p["realized"], p["moic"], p["status"],
                         p["disposition"], p["source"], "yes" if p["overridden"] else "no", p["run_id"],
                         p["published_at"], p["note"]])
    return headers, rows
