"""A whole new version of the Q3 2026 workbook — same schema, different content — must run the same way.

scripts/make_variant_workbooks.py derives five variants from the shipped workbook (renamed and
reshuffled; renumbered with blanks, breakeven and deliberately unreconciled marks; a busy quarter
across every event type; a messy layout; a small book). Each is regenerated here into a temp folder
and pushed through the whole stack on an empty ledger and the fixture comps: engine, bridge, JSON
round trip, cell provenance, mark archive, next-quarter roll-forward and re-ingest, the publish gate,
the executive view, and every read route of the API.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from datetime import date
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from hc_valuation.api.app import create_app
from hc_valuation.api.history import build_history
from hc_valuation.api.publish import exec_payload, outstanding, publish_run
from hc_valuation.api.sources import build_sources
from hc_valuation.config import load_config, repo_root, write_next_policy
from hc_valuation.engine.models import Readiness, ValuationRun
from hc_valuation.export.snapshot import write_next_quarter_workbook
from hc_valuation.ingest.reader import read_workbook
from hc_valuation.ingest.validate import validate
from hc_valuation.pipeline import RunPaths, execute, load_mark_basis
from hc_valuation.workbooks import activity_rows
from tests.conftest import event, make_workbook, position, run_workbook

ROOT = repo_root()


def _generator():
    spec = importlib.util.spec_from_file_location("make_variant_workbooks", ROOT / "scripts" / "make_variant_workbooks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def variants(tmp_path_factory) -> dict[str, Path]:
    out = tmp_path_factory.mktemp("variants")
    return _generator().write_all(out)


@pytest.fixture(scope="module")
def runs(variants, tmp_path_factory):
    """Every variant executed once on an empty ledger with the fixture comps."""
    out = {}
    for name, wb in variants.items():
        root = tmp_path_factory.mktemp(name)
        shutil.copytree(ROOT / "rules", root / "rules")
        paths = RunPaths.default(root=ROOT, workbook=wb, policy=ROOT / "rules" / "2026Q3.yaml", ledger_dir=root / "ledger")
        out[name] = (execute(paths, provider="stub", adjudicate=False), paths, root)
    return out


NAMES = ["v1_renamed", "v2_renumbered", "v3_busy", "v4_messy", "v5_small"]


@pytest.mark.parametrize("name", NAMES)
def test_runs_bridges_and_round_trips(name, runs):
    r, paths, _ = runs[name]
    run = r.run
    assert run.manifest.quarter_label == "Q3 2026" and run.totals.positions == len(run.companies) > 0
    for c in run.companies:      # closing = opening + new investment + gain/loss − realized, on every position
        assert abs((c.booked_mark - c.prior_mark) - (c.new_investment_quarter + c.valuation_change_quarter - c.realized_quarter)) < 1e-6, c.company
    assert abs(sum(c.proposed_mark for c in run.companies) - run.totals.proposed_nav) < 1e-6
    ValuationRun.model_validate(json.loads(run.model_dump_json()))
    assert build_sources(r)
    h = build_history(run, ROOT, published=paths.published_dir)
    assert h["errors"] == [] and h["counts"]["live"] == run.totals.positions


@pytest.mark.parametrize("name", NAMES)
def test_next_quarter_rolls_forward_and_reingests_clean(name, runs, tmp_path):
    r, paths, root = runs[name]
    out = write_next_quarter_workbook(r.run, paths.workbook, tmp_path / "next" / "portfolio_Q4_2026.xlsx", r.config)
    q4 = root / "rules" / "2026Q4.yaml"
    cfg4 = load_config(q4 if q4.exists() else write_next_policy(root / "rules" / "2026Q3.yaml"))
    snap, feed = read_workbook(out, cfg4)
    blocking = [i for i in validate(snap, feed, cfg4, explained_departures=load_mark_basis(tmp_path / "next" / "open_items_carry.yaml")) if i.blocking]
    assert blocking == [], [(i.rule_id, i.company, i.message) for i in blocking]
    placeholders = {c.company for c in r.run.companies if c.invested_after == 0 and c.booked_mark == 0 and c.ownership_after == 0 and c.prior_mark == 0}
    assert len(snap.positions) == r.run.totals.positions - len(placeholders)


@pytest.mark.parametrize("name", NAMES)
def test_publish_gate_executive_view_and_api(name, runs, tmp_path):
    r, paths, _ = runs[name]
    waiting = outstanding(r.run)
    assert (len(waiting) > 0) == any(c.readiness is not Readiness.READY for c in r.run.companies)
    with pytest.raises(Exception):
        publish_run(r.run, ROOT, approver="IC", published=paths.published_dir)          # refused while anything waits
    rec = publish_run(r.run, ROOT, approver="IC", require_decisions=False, published=paths.published_dir)
    view = exec_payload(ROOT, published=paths.published_dir)
    assert view["meta"]["status"] == rec["status"]
    client = TestClient(create_app(paths, provider="stub", static_dir=tmp_path / "no-static"))
    for route in ("/api/run", "/api/sources", "/api/history", "/api/signals", "/api/market", "/api/workbooks", "/api/rules",
                  "/api/rationale", "/api/publish/readiness", "/api/health", "/api/exec"):
        assert client.get(route).status_code == 200, route


def test_renamed_book_values_exactly_like_the_original(runs, variants):
    """Names, sectors, funds and stages are labels: a book with every one changed must produce the
    same marks, the same readiness and the same totals as the original under the fixture comps."""
    v1 = runs["v1_renamed"][0].run
    base = execute(RunPaths.default(root=ROOT, workbook=ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx",
                                    policy=ROOT / "rules" / "2026Q3.yaml", ledger_dir=variants["v1_renamed"].parent / "base-ledger"),
                   provider="stub", adjudicate=False).run
    assert v1.totals.readiness == base.totals.readiness
    assert v1.totals.proposed_nav == pytest.approx(base.totals.proposed_nav) and v1.totals.realized_quarter == pytest.approx(base.totals.realized_quarter)
    assert sorted(c.proposed_mark for c in v1.companies) == pytest.approx(sorted(c.proposed_mark for c in base.companies))
    assert {c.fund for c in v1.companies} == {"Fund III", "Fund IV", "Opportunity Fund"}
    assert "Quantum Hardware" in {c.sector for c in v1.companies}     # a sector no comps basket knows: absolute bounds, no crash
    assert {c.stage for c in v1.companies} >= {"Pre-Seed", "Series E"}


def test_messy_layout_reads_like_the_clean_one(runs):
    v4, base = runs["v4_messy"][0].run, runs["v1_renamed"][0].run
    assert v4.totals.readiness == base.totals.readiness and v4.totals.proposed_nav == pytest.approx(base.totals.proposed_nav)
    ids = {v.rule_id for v in v4.validation}
    assert ids <= {"X-910", "X-911", "X-915", "X-917"} and not any(v.blocking for v in v4.validation)    # every tolerance recorded, nothing refused


def test_renumbered_book_catches_exactly_the_unreconciled_marks(runs):
    run = runs["v2_renumbered"][0].run
    blocked = {v.company for v in run.validation if v.rule_id == "X-904" and v.blocking}
    assert blocked == {"Beltrix", "Quindle", "Xalorin", "Fenwright"}
    for name in blocked:
        assert run.by_company()[name].readiness is Readiness.BLOCKED
    by = run.by_company()
    assert by["Emberfold"].arr is None and not any(f.rule_id.startswith("X-30") for f in by["Emberfold"].flags)   # pre-revenue: no growth screen
    assert by["Fernwave"].runway_months_aged is None                                                            # breakeven: no runway screen


def test_busy_quarter_blocks_what_it_must_and_applies_the_rest(runs):
    run = runs["v3_busy"][0].run
    by = run.by_company()
    for name in ("Brumewell", "Nettlebay"):                       # unknown event types
        assert by[name].readiness is Readiness.BLOCKED and "M-999" in {f.rule_id for f in by[name].flags}, name
    assert by["Nonesuch Ventures"].readiness is Readiness.BLOCKED and "X-900" in {f.rule_id for f in by["Nonesuch Ventures"].flags}
    q = by["Quillbrook Labs"]                                     # a new company with a second row the same quarter
    assert q.readiness is Readiness.BLOCKED and "X-918" in {f.rule_id for f in q.flags} and "X-900" not in {f.rule_id for f in q.flags}
    assert q.proposed_mark == pytest.approx(0.083 * 18.0) and q.invested_after == pytest.approx(1.5) and q.fund == "Fund III"
    assert [i.kind.value for i in q.open_items] == ["term_sheet"]
    assert by["Halcyra"].readiness is Readiness.BLOCKED and "X-112" in {f.rule_id for f in by["Halcyra"].flags}
    assert by["Umberly"].readiness is Readiness.BLOCKED and "X-116" in {f.rule_id for f in by["Umberly"].flags}
    assert by["Thornmill Systems"].listed and by["Thornmill Systems"].readiness is Readiness.BLOCKED
    assert by["Pinwhistle"].proposed_mark == pytest.approx(0.083 * 87.7) and "X-114" in {f.rule_id for f in by["Pinwhistle"].flags}
    assert by["Elmsworth Data"].proposed_mark == pytest.approx(23.8)                       # non-binding LOI holds
    assert by["Kolvani Health"].realized_quarter == pytest.approx(0.9) and by["Kolvani Health"].proposed_mark == 0.0
    assert by["Cindral"].realized_quarter == pytest.approx(29.2) and by["Cindral"].status_after.value == "Acquired"
    assert by["Yarrowbank"].note_at_cost == 0.0 and by["Yarrowbank"].realized_quarter == pytest.approx(0.31)
    assert by["Emberfold"].proposed_mark == pytest.approx(0.065 * 40.0) and by["Emberfold"].open_items == ()
    assert by["Dovelane Systems"].proposed_mark == pytest.approx(0.05 * 83.0) and by["Dovelane Systems"].open_items == ()
    assert by["Vexmoor"].ownership_after == pytest.approx(0.060) and "X-110" in {f.rule_id for f in by["Vexmoor"].flags}
    assert by["Mirthstone"].invested_after == pytest.approx(4.245)


def test_small_book_runs(runs):
    run = runs["v5_small"][0].run
    assert run.totals.positions == 20 and sum(1 for c in run.companies for s in c.steps if s.evidence) == 3


# ---- the two shared-logic fixes these variants found

def test_second_row_on_an_entering_company_applies_to_it(tmp_path, cfg):
    book = [position(company="Alpha")]
    first = event(company="Newco", event_type="New Investment", date=date(2026, 8, 3), detail="Seed — Fund III, SaaS", value=18.0,
                  hc_investment=1.5, ownership_after=0.083, notes="First cheque from Fund III.")
    later = event(company="Newco", event_type="Term Sheet Signed", date=date(2026, 9, 29), detail="Series A term sheet at ~$40M post", value=40.0,
                  notes="Signed six weeks after the seed.")
    run, issues = run_workbook(make_workbook(tmp_path, book, [first, later]), cfg)
    assert not [i for i in issues if i.rule_id == "X-901"]
    c = run.by_company()["Newco"]
    assert "X-900" not in {f.rule_id for f in c.flags} and "X-918" in {f.rule_id for f in c.flags}
    assert [s.rule_id for s in c.steps if s.evidence] == ["M-014", "M-070"]


def test_prior_mark_exactly_at_the_reconciliation_tolerance_is_not_refused(tmp_path, cfg):
    """A mark rounded to $0.1M can sit exactly 0.05 from ownership × post; float noise must not block it."""
    pos = position(company="Alpha", ownership=0.1, latest_post_money=69.5, prior_mark=6.9)     # 6.95 vs 6.9
    run, issues = run_workbook(make_workbook(tmp_path, [pos], []), cfg)
    assert not [i for i in issues if i.rule_id == "X-904"] and run.by_company()["Alpha"].readiness is Readiness.READY
    pos2 = position(company="Alpha", ownership=0.1, latest_post_money=69.5, prior_mark=6.89)     # 0.06: refused
    run2, issues2 = run_workbook(make_workbook(tmp_path, [pos2], [], name="b.xlsx"), cfg)
    assert [i.rule_id for i in issues2 if i.blocking] == ["X-904"]


def test_activity_rows_are_counted_after_the_header_wherever_it_sits(variants):
    assert activity_rows(variants["v4_messy"]) == 18 and activity_rows(variants["v3_busy"]) == 44 and activity_rows(variants["v5_small"]) == 3
