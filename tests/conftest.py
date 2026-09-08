"""Shared fixtures and a synthetic-workbook builder.

Two ways to exercise the engine live here:

* `run_real` — the full pipeline over the real workbook with adjudication off and a
  pinned `generated_at`, so every integration test sees exactly the run the golden
  fixture was regenerated from.
* `make_workbook` / `run_workbook` — a synthetic workbook written with the exact column
  headers from `ingest/schema.py`, and a pure read → validate → run_valuation path that
  bypasses the pipeline (no connectors, no override file, no clock). Edge cases that the
  Q3 feed does not contain are built from these in a few lines.
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import openpyxl
import pytest

from hc_valuation import pipeline
from hc_valuation.config import RuleConfig, load_config
from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import MarketData, OpenItem, OverrideLedger, ValidationIssue, ValuationRun
from hc_valuation.engine.run import run_valuation
from hc_valuation.ingest.reader import read_workbook
from hc_valuation.ingest.schema import ACTIVITY_COLUMNS, PORTFOLIO_COLUMNS
from hc_valuation.ingest.validate import validate

# The suite never reads the working ledger. `data/overrides.yaml` and `data/published/` fill as a
# quarter is decided and closed — that is the product working, not a regression — so every
# `RunPaths.default()` in the suite is pointed at an empty ledger folder through the environment
# (pipeline.RunPaths.default honours HC_LEDGER_DIR / HC_OVERRIDES), one for the session-scoped
# fixtures and a fresh one per test so nothing a test records leaks into the next.
import os as _os
import tempfile as _tempfile

_SESSION_LEDGER = Path(_tempfile.mkdtemp(prefix="hc-test-ledger-"))
_os.environ["HC_LEDGER_DIR"] = str(_SESSION_LEDGER)
_os.environ.pop("HC_OVERRIDES", None)
# The suite never calls a model: the note reader is pinned off and no API key is visible to it,
# whatever the shell that started pytest had exported. A test that wants a reader injects a fake.
_os.environ["HC_NOTE_READER"] = "off"
_os.environ["HC_RECOMMENDER"] = "policy"
_os.environ.pop("ANTHROPIC_API_KEY", None)


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HC_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.delenv("HC_OVERRIDES", raising=False)
    monkeypatch.setenv("HC_NOTE_READER", "off")
    monkeypatch.setenv("HC_RECOMMENDER", "policy")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "rules" / "2026Q3.yaml"
WORKBOOK_PATH = ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx"
GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "golden_q3_2026.json"
GENERATED_AT = datetime(2026, 9, 30)

# Header -> attribute maps inverted, so builders take snake_case keys and emit the
# workbook's own column names.
_POS_HEADER = {attr: hdr for hdr, attr in PORTFOLIO_COLUMNS.items()}
_EVT_HEADER = {attr: hdr for hdr, attr in ACTIVITY_COLUMNS.items()}


# ----------------------------------------------------------------------------- fixtures

@pytest.fixture(scope="session")
def cfg() -> RuleConfig:
    return load_config(POLICY_PATH)


@pytest.fixture(scope="session")
def workbook_path() -> Path:
    assert WORKBOOK_PATH.exists(), f"real workbook missing: {WORKBOOK_PATH}"
    return WORKBOOK_PATH


@pytest.fixture(scope="session")
def run_real() -> ValuationRun:
    """The canonical run: real workbook, adjudication off, fixed generated_at."""
    return execute_real().run


def execute_real(policy: Path | None = None) -> pipeline.PipelineResult:
    paths = pipeline.RunPaths.default(root=ROOT, workbook=WORKBOOK_PATH, policy=policy or POLICY_PATH)
    return pipeline.execute(paths, adjudicate=False, generated_at=GENERATED_AT)


# ----------------------------------------------------------------------------- builders

def position(**overrides: Any) -> dict[str, Any]:
    """A clean, CLEAR-disposition Active position. Every screen sits comfortably inside
    policy (15-month-old round, 20x ARR, 2.0x MOIC, 23 months aged runway) so a test
    only has to state the one thing it wants to be different."""
    p: dict[str, Any] = dict(
        company="Alpha", sector="SaaS", fund="Fund I", stage="Series A", status="Active",
        first_investment=date(2024, 1, 15), latest_round=date(2025, 6, 15),
        latest_post_money=100.0, invested=5.0, ownership=0.10, prior_mark=None, realized=0.0,
        arr=10.0, arr_growth=0.50, gross_margin=0.70, net_burn=0.5, cash=12.0, headcount=50,
    )
    p.update(overrides)
    if p["prior_mark"] is None:
        p["prior_mark"] = round(p["ownership"] * p["latest_post_money"], 6)
    return p


def event(event_type: str | EventType = EventType.PRICED_ROUND, **overrides: Any) -> dict[str, Any]:
    e: dict[str, Any] = dict(
        date=date(2026, 8, 15), company="Alpha",
        event_type=event_type.value if isinstance(event_type, EventType) else event_type,
        detail="", value=None, hc_investment=None, ownership_after=None, proceeds=None, notes="",
    )
    e.update(overrides)
    return e


def make_workbook(tmp_path: Path, positions: list[dict], events: list[dict],
                  activity_sheet: str = "Q3 2026 Activity", *, name: str = "synthetic.xlsx",
                  extra_portfolio_columns: dict[str, Any] | None = None,
                  extra_activity_columns: dict[str, Any] | None = None) -> Path:
    """Write an xlsx with the exact Portfolio / activity / Field Definitions layout the
    reader expects. Position and event dicts use the snake_case attribute names from
    `engine/inputs.py`; unknown keys are written under their own header (so a test can
    plant an unexpected column)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio"
    pos_headers = list(PORTFOLIO_COLUMNS.keys()) + list((extra_portfolio_columns or {}).keys())
    ws.append(pos_headers)
    for p in positions:
        p = dict(p)
        # cached-formula columns tie to the recomputed values unless the test overrides them
        if "sheet_moic" not in p:
            p["sheet_moic"] = _cached_formula(lambda: (p["prior_mark"] + p.get("realized", 0.0)) / p["invested"])
        if "sheet_runway" not in p:
            p["sheet_runway"] = _cached_formula(lambda: p["cash"] / p["net_burn"] if p["net_burn"] > 0 else None)
        row = []
        for hdr in pos_headers:
            attr = PORTFOLIO_COLUMNS.get(hdr)
            if attr is not None:
                row.append(_cell(p.get(attr)))
            else:
                row.append(_cell(p.get(hdr, (extra_portfolio_columns or {}).get(hdr))))
        ws.append(row)

    wa = wb.create_sheet(activity_sheet)
    evt_headers = list(ACTIVITY_COLUMNS.keys()) + list((extra_activity_columns or {}).keys())
    wa.append(evt_headers)
    for e in events:
        row = []
        for hdr in evt_headers:
            attr = ACTIVITY_COLUMNS.get(hdr)
            if attr is not None:
                row.append(_cell(e.get(attr)))
            else:
                row.append(_cell(e.get(hdr, (extra_activity_columns or {}).get(hdr))))
        wa.append(row)

    wd = wb.create_sheet("Field Definitions")
    wd.append(["Field", "Definition"])
    wd.append(["PORTFOLIO TAB", None])
    for hdr in PORTFOLIO_COLUMNS:
        wd.append([hdr, f"Synthetic definition of {hdr}."])
    wd.append([None, None])
    wd.append([f"{activity_sheet.upper()} TAB", None])
    wd.append(["Date", "Date the event occurred or was signed."])
    wd.append(["Event", ", ".join(e.value for e in EventType) + "."])
    for hdr in list(ACTIVITY_COLUMNS)[3:]:
        wd.append([hdr, f"Synthetic definition of {hdr}."])

    out = tmp_path / name
    wb.save(out)
    return out


def _cached_formula(fn) -> Any:
    """Mimic the sheet's live MOIC / Runway cells: a number when computable, '-' otherwise."""
    try:
        v = fn()
    except (TypeError, ZeroDivisionError, KeyError):
        return "-"
    return "-" if v is None else round(v, 12)


def _cell(v: Any) -> Any:
    if isinstance(v, date) and not isinstance(v, datetime):
        return datetime(v.year, v.month, v.day)
    return v


def run_workbook(path: Path, cfg: RuleConfig, market: MarketData | None = None,
                 overrides: OverrideLedger | None = None, prior_open_items: Iterable[OpenItem] = (),
                 explained: dict[str, str] | None = None,
                 ) -> tuple[ValuationRun, list[ValidationIssue]]:
    """read_workbook → validate → run_valuation. Pure: no connectors, no ledger file, no clock.
    `explained` plays the sidecar's mark_basis: company -> why the prior mark departs from
    ownership × last-round post (otherwise X-904 blocks the row, and with it the position)."""
    snapshot, feed = read_workbook(path, cfg)
    issues = validate(snapshot, feed, cfg, explained_departures=explained)
    run = run_valuation(
        snapshot, feed, market or MarketData(as_of=cfg.quarter.measurement_date), overrides or OverrideLedger(), cfg,
        validation=tuple(issues), prior_open_items=tuple(prior_open_items),
        input_sha256="synthetic", input_file=path.name, generated_at=GENERATED_AT, market_data_source="test",
    )
    return run, issues


def with_policy(cfg: RuleConfig, **updates: Any) -> RuleConfig:
    """A modified copy of a config. Keys are dotted paths into the YAML structure, e.g.
    ``with_policy(cfg, **{"marking.secondary.remainder_basis": "secondary_price"})``.
    Goes through the same strict validation as a policy file."""
    raw = copy.deepcopy(cfg.model_dump(by_alias=True, mode="python"))
    for dotted, value in updates.items():
        node = raw
        *parents, leaf = dotted.split(".")
        for k in parents:
            node = node[k]
        node[leaf] = value
    return RuleConfig.model_validate(raw)


@pytest.fixture
def build(tmp_path: Path, cfg: RuleConfig):
    """`build(positions, events, ...)` → (run, issues) on a synthetic workbook.
    Pass `cfg=` to use a modified policy, `market=` / `overrides=` / `prior_open_items=`
    straight through to run_valuation, `explained=` to validate (the sidecar's mark basis)."""
    counter = {"n": 0}

    def _build(positions: list[dict], events: list[dict], *, cfg_: RuleConfig | None = None,
               activity_sheet: str = "Q3 2026 Activity", **kw: Any):
        counter["n"] += 1
        path = make_workbook(tmp_path, positions, events, activity_sheet, name=f"synthetic_{counter['n']}.xlsx")
        return run_workbook(path, cfg_ or cfg, **kw)

    return _build


def canonical(run: ValuationRun) -> dict:
    """model_dump_json → dict round-trip, so comparisons see exactly what the fixture stores."""
    return json.loads(run.model_dump_json())


def diff_runs(old: dict, new: dict, *, limit: int = 60) -> list[str]:
    """Human-readable differences between two serialised runs: per company / per field,
    with old vs new. Company entries are matched by name, not position, so an inserted
    row reads as one addition rather than 99 shifted mismatches."""
    lines: list[str] = []

    def walk(a: Any, b: Any, path: str) -> None:
        if len(lines) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a:
                    lines.append(f"{path}.{k}: added → {b[k]!r}")
                elif k not in b:
                    lines.append(f"{path}.{k}: removed (was {a[k]!r})")
                else:
                    walk(a[k], b[k], f"{path}.{k}")
        elif isinstance(a, list) and isinstance(b, list):
            if a and b and all(isinstance(x, dict) and "company" in x for x in a + b):
                ka = {x["company"]: x for x in a}
                kb = {x["company"]: x for x in b}
                for name in sorted(set(ka) | set(kb)):
                    if name not in ka:
                        lines.append(f"{path}[{name}]: added")
                    elif name not in kb:
                        lines.append(f"{path}[{name}]: removed")
                    else:
                        walk(ka[name], kb[name], f"{path}[{name}]")
            else:
                if len(a) != len(b):
                    lines.append(f"{path}: length {len(a)} → {len(b)}")
                for i, (x, y) in enumerate(zip(a, b)):
                    walk(x, y, f"{path}[{i}]")
        elif a != b:
            lines.append(f"{path}: {a!r} → {b!r}")

    walk(old, new, "run")
    if len(lines) >= limit:
        lines.append(f"... (truncated at {limit} lines)")
    return lines


def only(run: ValuationRun, company: str = "Alpha"):
    return run.by_company()[company]


def rule_ids(result) -> list[str]:
    return [s.rule_id for s in result.steps]


def flag_ids(result) -> set[str]:
    return {f.rule_id for f in result.flags}


def next_quarter_cfg(cfg):
    """`cfg` rolled to the following quarter (label, window, measurement date) — what
    `hc-valuation next-policy` writes, as an object. X-922 refuses a book run under the wrong
    quarter's policy, so tests that read a next-quarter workbook must use this."""
    from hc_valuation.config import QuarterCfg, next_quarter_window
    return cfg.model_copy(update={"quarter": QuarterCfg(**next_quarter_window(cfg.quarter))})
