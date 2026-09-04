"""The per-company mark archive (api/history.py): merged from the backfill file, the publish
ledger and the live run, never invented, and served / inlined for the history chart."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hc_valuation.api.app import create_app
from hc_valuation.api.history import (build_history, history_rows, load_backfill, previous_quarter_label,
                                      quarter_key, quarter_label, quarter_slug)
from hc_valuation.api.publish import publish_run
from hc_valuation.config import repo_root
from hc_valuation.export import write_history_csv, write_static_report
from hc_valuation.pipeline import RunPaths, execute


# ---------------------------------------------------------------- quarter labels

def test_quarter_helpers_parse_and_roll_over():
    assert quarter_key("Q3 2026") == 2026 * 4 + 2
    assert quarter_label(quarter_key("Q3 2026")) == "Q3 2026"
    assert previous_quarter_label("Q1 2027") == "Q4 2026"
    assert previous_quarter_label("Q3 2026") == "Q2 2026"
    assert quarter_slug("Q4 2026") == "2026Q4"
    assert quarter_key("  q2 2025 ".upper()) == 2025 * 4 + 1
    with pytest.raises(ValueError):
        quarter_key("2026Q3")


# ---------------------------------------------------------------- backfill file

def test_backfill_loads_points_and_reports_bad_entries(tmp_path: Path):
    f = tmp_path / "mark_history.yaml"
    f.write_text("""
companies:
  Aravine:
    - {quarter: Q4 2025, mark: 5.2, invested: 6.0, realized: 0, status: Active, note: from the Q4 book}
    - {quarter: Q1 2026, mark: 6.1}
    - {quarter: 2025Q3, mark: 4.0}
    - {quarter: Q2 2025, mark: 3.9, ownership: 0.1}
    - {quarter: Q1 2025, mark: abc}
  Beltrix: not-a-list
""")
    pts, errors = load_backfill(f)
    assert set(pts) == {"Aravine"}
    assert [p["quarter"] for p in pts["Aravine"].values()] == ["Q4 2025", "Q1 2026"]
    q4 = pts["Aravine"]["Q4 2025"]
    assert q4["source"] == "backfill" and q4["moic"] == pytest.approx(5.2 / 6.0, abs=1e-4) and q4["note"] == "from the Q4 book"
    assert pts["Aravine"]["Q1 2026"]["invested"] is None and pts["Aravine"]["Q1 2026"]["moic"] is None
    assert len(errors) == 4
    assert any("entry 3" in e and "Qn YYYY" in e for e in errors)
    assert any("entry 4" in e and "ownership" in e for e in errors)
    assert any("entry 5" in e for e in errors)
    assert any("Beltrix" in e for e in errors)


def test_backfill_missing_or_broken_file_is_not_fatal(tmp_path: Path):
    assert load_backfill(tmp_path / "none.yaml") == ({}, [])
    bad = tmp_path / "bad.yaml"
    bad.write_text("companies: [\n")
    pts, errors = load_backfill(bad)
    assert pts == {} and len(errors) == 1 and "YAML" in errors[0]
    (tmp_path / "list.yaml").write_text("- a\n- b\n")
    assert load_backfill(tmp_path / "list.yaml")[0] == {}
    (tmp_path / "empty.yaml").write_text("companies: {}\n")
    assert load_backfill(tmp_path / "empty.yaml") == ({}, [])


def test_shipped_backfill_file_is_empty_and_valid():
    pts, errors = load_backfill(repo_root() / "data" / "mark_history.yaml")
    assert pts == {} and errors == []


# ---------------------------------------------------------------- assembly

@pytest.fixture()
def scratch(tmp_path: Path) -> RunPaths:
    """A RunPaths rooted in a scratch copy of data/ (no published snapshots) so the archive
    starts from the run alone and each test adds what it needs."""
    root = repo_root()
    data = tmp_path / "data"
    shutil.copytree(root / "data", data, ignore=shutil.ignore_patterns("sample_run.json", "published", "mark_cache"))
    return RunPaths(
        root=tmp_path, policy=root / "rules" / "2026Q3.yaml", workbook=data / "HC_Mock_Portfolio_Data.xlsx",
        overrides=data / "overrides.yaml", proposals_dir=data / "proposals", precedent=data / "precedent.yaml",
        open_items_carry=data / "open_items_carry.yaml",
    )


def test_run_alone_gives_prior_and_live_points(scratch: RunPaths):
    r = execute(scratch, provider="stub")
    h = build_history(r.run, scratch.root)
    assert h["as_of_quarter"] == "Q3 2026" and h["quarters"] == ["Q2 2026", "Q3 2026"]
    assert h["counts"] == {"backfill": 0, "prior": 100, "published": 0, "live": 100}
    assert h["backfill_file"] is None and h["errors"] == []
    c = r.run.by_company()["Aravine"]
    prior, live = h["companies"]["Aravine"]
    assert prior["quarter"] == "Q2 2026" and prior["source"] == "prior" and prior["mark"] == pytest.approx(c.prior_mark)
    assert prior["invested"] == pytest.approx(c.invested_before) and prior["status"] == c.status_before.value
    assert live["quarter"] == "Q3 2026" and live["source"] == "live" and live["mark"] == pytest.approx(c.booked_mark)
    assert live["run_id"] == r.run.manifest.run_id and live["published_at"] is None
    assert live["disposition"] == c.disposition.value and live["moic"] == pytest.approx(c.moic_after, abs=1e-3)
    # every company in the run has exactly these two points, in order
    for pts in h["companies"].values():
        assert [p["quarter"] for p in pts] == ["Q2 2026", "Q3 2026"]


def test_publishing_turns_the_live_point_into_a_published_one(scratch: RunPaths):
    r = execute(scratch, provider="stub")
    publish_run(r.run, scratch.root, approver="IC", published_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
    h = build_history(r.run, scratch.root)
    assert h["counts"]["published"] == 100 and h["counts"]["live"] == 0
    live = h["companies"]["Aravine"][-1]
    assert live["source"] == "published" and live["published_at"].startswith("2026-10-02") and live["note"] is None


def test_live_run_that_moved_since_publish_is_flagged(scratch: RunPaths):
    r = execute(scratch, provider="stub")
    publish_run(r.run, scratch.root, approver="IC")
    # someone changed the published number afterwards: the ledger disagrees with the live run
    p = scratch.root / "data" / "published" / "2026Q3.json"
    raw = json.loads(p.read_text())
    raw["publish"]["run_id"] = "deadbeef0000"
    for c in raw["run"]["companies"]:
        if c["company"] == "Aravine":
            c["booked_mark"] = c["booked_mark"] + 1.0
    p.write_text(json.dumps(raw))
    h = build_history(r.run, scratch.root)
    pt = h["companies"]["Aravine"][-1]
    assert pt["source"] == "live" and pt["mark"] == pytest.approx(r.run.by_company()["Aravine"].booked_mark)
    assert "not been re-published" in pt["note"]
    other = h["companies"]["Beltrix"][-1]
    assert other["source"] == "published" and other["note"] is None   # same mark => the ledger agrees


def test_previous_quarter_prefers_the_ledger_and_notes_a_disagreement(scratch: RunPaths):
    r = execute(scratch, provider="stub")
    # fabricate a Q2 2026 publish from the same run, then move one company's mark away from the workbook's Prior Mark
    d = scratch.root / "data" / "published"
    d.mkdir(parents=True)
    raw = {"publish": {"quarter": "Q2 2026", "slug": "2026Q2", "run_id": "q2run", "published_at": "2026-07-01T00:00:00+00:00"},
           "run": json.loads(r.run.model_dump_json())}
    ara = r.run.by_company()["Aravine"]
    bel = r.run.by_company()["Beltrix"]
    for c in raw["run"]["companies"]:
        c["booked_mark"] = c["prior_mark"] if c["company"] != "Aravine" else c["prior_mark"] + 2.0
    (d / "2026Q2.json").write_text(json.dumps(raw))
    h = build_history(r.run, scratch.root)
    a_prior = h["companies"]["Aravine"][0]
    assert a_prior["source"] == "published" and a_prior["mark"] == pytest.approx(ara.prior_mark + 2.0)
    assert "differs from the workbook's Prior Mark" in a_prior["note"]
    b_prior = h["companies"]["Beltrix"][0]
    assert b_prior["source"] == "published" and b_prior["mark"] == pytest.approx(bel.prior_mark) and b_prior["note"] is None
    assert h["counts"]["prior"] == 0


def test_backfill_extends_the_chart_backwards_and_never_overrides_the_ledger(scratch: RunPaths):
    r = execute(scratch, provider="stub")
    (scratch.root / "data" / "mark_history.yaml").write_text("""
companies:
  Aravine:
    - {quarter: Q4 2025, mark: 5.2, invested: 6.0}
    - {quarter: Q2 2026, mark: 99.0}
""")
    h = build_history(r.run, scratch.root)
    assert h["backfill_file"] == "data/mark_history.yaml"
    pts = h["companies"]["Aravine"]
    assert [p["quarter"] for p in pts] == ["Q4 2025", "Q2 2026", "Q3 2026"]
    assert pts[0]["source"] == "backfill" and pts[0]["mark"] == 5.2
    # the workbook's Prior Mark outranks a backfill entry for the same quarter
    assert pts[1]["source"] == "prior" and pts[1]["mark"] == pytest.approx(r.run.by_company()["Aravine"].prior_mark)
    assert "backfill entry $99.000M differs" in pts[1]["note"]
    assert h["quarters"] == ["Q4 2025", "Q2 2026", "Q3 2026"] and h["counts"]["backfill"] == 1
    # a corrupt file is reported, not fatal
    (scratch.root / "data" / "mark_history.yaml").write_text("companies: [\n")
    h2 = build_history(r.run, scratch.root)
    assert len(h2["errors"]) == 1 and len(h2["companies"]["Aravine"]) == 2


def test_history_csv_is_one_row_per_company_quarter(scratch: RunPaths, tmp_path: Path):
    r = execute(scratch, provider="stub")
    h = build_history(r.run, scratch.root)
    headers, rows = history_rows(h)
    assert headers[:3] == ["Company", "Quarter", "Booked Mark ($M)"] and len(rows) == 200
    p = write_history_csv(h, tmp_path / "out" / "mark_history.csv")
    lines = p.read_text().splitlines()
    assert lines[0].startswith("Company,Quarter,Booked Mark") and len(lines) == 201
    assert any(line.startswith("Aravine,Q3 2026,") and ",live," in line for line in lines)


# ---------------------------------------------------------------- served and exported

def test_api_history_route_and_static_inlining(scratch: RunPaths, tmp_path: Path):
    client = TestClient(create_app(scratch, static_dir=tmp_path / "no-static"))
    h = client.get("/api/history").json()
    assert set(h) == {"as_of_quarter", "quarters", "counts", "backfill_file", "errors", "companies"}
    assert len(h["companies"]) == 100 and h["companies"]["Aravine"][-1]["source"] == "live"
    r = execute(scratch, provider="stub")
    html = write_static_report(r.run, tmp_path / "r.html", None, history=build_history(r.run, scratch.root)).read_text()
    assert "window.__HC_HISTORY__ = " in html and "window.__HC_RUN__ = " in html
    assert "window.__HC_HISTORY__" not in write_static_report(r.run, tmp_path / "r2.html", None).read_text()
