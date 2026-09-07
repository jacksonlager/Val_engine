"""Command line: validate / build / rules / version through typer's CliRunner."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hc_valuation.cli import app

runner = CliRunner()


def test_help_and_version():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for cmd in ("run", "build", "validate", "export", "rules", "version"):
        assert cmd in r.output
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "engine 0.1.0" in r.output and "policy 2026Q3-0.2" in r.output


def test_validate_real_workbook_exit_zero():
    r = runner.invoke(app, ["validate"])
    assert r.exit_code == 0, r.output
    assert "100 positions, 18 events" in r.output
    assert "OK: 0 blocking" in r.output


def test_validate_missing_file_exit_one(tmp_path: Path):
    r = runner.invoke(app, ["validate", "--input", str(tmp_path / "nope.xlsx")])
    assert r.exit_code == 1
    assert "INGEST ERROR" in r.output


def test_build_produces_files(tmp_path: Path):
    out = tmp_path / "dist"
    # the IC pack rides along whenever a published snapshot exists: release one into the suite's own ledger first
    assert runner.invoke(app, ["publish", "--approver", "IC", "--proposed"]).exit_code == 0
    r = runner.invoke(app, ["build", "--out", str(out)])
    assert r.exit_code == 0, r.output
    for name in ("report.html", "valuation_Q3_2026.xlsx", "marks.csv", "exceptions.csv", "audit_trail.csv",
                 "open_items.csv", "portfolio_Q4_2026.xlsx", "open_items_carry.yaml", "run.json", "manifest.json",
                 "exec_report.html"):            # the IC pack rides along whenever a published snapshot exists
        assert (out / name).exists(), name
    assert "proposed 1,184.3" in r.output
    run = json.loads((out / "run.json").read_text())
    assert run["totals"]["positions"] == 100
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["quarter_label"] == "Q3 2026"


def test_build_refuses_to_roll_a_book_with_a_blocking_ingest_issue(tmp_path: Path):
    """A row the reader refused is reviewable but not rollable: report and workbook are written,
    the next-quarter input is not, and the exit code says so."""
    import openpyxl
    from conftest import WORKBOOK_PATH
    bad = tmp_path / "bad.xlsx"
    wb = openpyxl.load_workbook(WORKBOOK_PATH)
    ws = wb["Q3 2026 Activity"]
    ws.cell(row=2, column=2).value = "Zorblax Industries"       # a company not in the book -> X-901 BLOCK
    wb.save(bad)
    out = tmp_path / "dist"
    r = runner.invoke(app, ["build", "--out", str(out), "-i", str(bad)])
    assert r.exit_code == 2, r.output
    assert "refused" in r.output and "X-901" in r.output and "next-quarter workbook is not emitted" in r.output
    assert (out / "report.html").exists() and (out / "valuation_Q3_2026.xlsx").exists() and (out / "run.json").exists()
    assert not (out / "portfolio_Q4_2026.xlsx").exists() and not (out / "open_items_carry.yaml").exists()


def test_export_subset(tmp_path: Path):
    out = tmp_path / "x"
    r = runner.invoke(app, ["export", "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert (out / "valuation_Q3_2026.xlsx").exists() and (out / "marks.csv").exists()
    assert not (out / "report.html").exists()


def test_rules_lists_m010():
    r = runner.invoke(app, ["rules"])
    assert r.exit_code == 0
    assert "M-010" in r.output and "Priced Equity Round" in r.output


def test_next_policy_rolls_the_window_and_refuses_to_overwrite(tmp_path: Path):
    import shutil
    from hc_valuation.config import load_config, repo_root

    rules = tmp_path / "rules"
    rules.mkdir()
    shutil.copy(repo_root() / "rules" / "2026Q3.yaml", rules / "2026Q3.yaml")
    r = runner.invoke(app, ["next-policy", "--policy", str(rules / "2026Q3.yaml"), "--note", "refresh"])
    assert r.exit_code == 0, r.output
    q4 = load_config(rules / "2026Q4.yaml")
    assert q4.inherits == "2026Q3" and q4.quarter.label == "Q4 2026"
    assert str(q4.quarter.window_start) == "2026-10-01" and str(q4.quarter.measurement_date) == "2026-12-31"
    assert str(q4.quarter.prior_close) == "2026-09-30"
    assert q4.exceptions.staleness.review_months == load_config(rules / "2026Q3.yaml").exceptions.staleness.review_months
    # year-end rollover is parsed, not hardcoded
    r = runner.invoke(app, ["next-policy", "--policy", str(rules / "2026Q4.yaml")])
    assert r.exit_code == 0 and load_config(rules / "2027Q1.yaml").quarter.label == "Q1 2027"
    assert str(load_config(rules / "2027Q1.yaml").quarter.window_end) == "2027-03-31"
    r = runner.invoke(app, ["next-policy", "--policy", str(rules / "2026Q4.yaml")])
    assert r.exit_code == 1 and "already exists" in r.output


def test_refresh_round_trip_validates_with_sidecar_beside_workbook(tmp_path: Path):
    """build -> next-policy -> validate the emitted book under the new policy: the X-904
    departures explained by the sidecar next to the workbook must not block."""
    out = tmp_path / "dist"
    assert runner.invoke(app, ["build", "--out", str(out)]).exit_code == 0
    rules = tmp_path / "rules"
    rules.mkdir()
    import shutil
    from hc_valuation.config import repo_root
    shutil.copy(repo_root() / "rules" / "2026Q3.yaml", rules / "2026Q3.yaml")
    assert runner.invoke(app, ["next-policy", "--policy", str(rules / "2026Q3.yaml")]).exit_code == 0
    r = runner.invoke(app, ["validate", "--input", str(out / "portfolio_Q4_2026.xlsx"), "--policy", str(rules / "2026Q4.yaml")])
    assert r.exit_code == 0, r.output
    assert "open items carried from" in r.output and "X-904" in r.output and "BLOCKED" not in r.output
