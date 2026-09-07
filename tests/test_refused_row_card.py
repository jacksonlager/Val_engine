"""What a reviewer sees when a row is refused: one finding, one fix.

A stress workbook with two identical `Acquisition (Closed)` rows on Glintworks produced five
findings for one problem — X-900 once per copy, X-105 once per copy (the note screen ran on rows
the engine had just refused), each repeating the check's full text. The card now carries one
X-900 naming both rows and the fix ("Delete one of the duplicate rows and rerun"), the note
screen waits for the corrected row, and a long note is clipped at a word, never mid-word.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hc_valuation.engine.exceptions import _clip
from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import Readiness
from tests.conftest import event, make_workbook, position, run_workbook

NOTE = ("Confirmed HC entitlement $15.5M: $13.5M cash received and $2.0M in an 18-month indemnity escrow. No equity "
        "remains; assess the escrow claim separately.")


def test_duplicate_rows_are_one_finding_with_the_fix(tmp_path: Path, cfg):
    pos = position(company="Glintworks", latest_post_money=110.0, ownership=0.13, invested=6.0, prior_mark=14.3)
    row = event(EventType.ACQ_CLOSED, date=date(2026, 9, 27), company="Glintworks", detail="Cash acquisition",
                value=120.0, ownership_after=0.0, proceeds=13.5, notes=NOTE)
    run, issues = run_workbook(make_workbook(tmp_path, [pos], [row, dict(row)]), cfg)
    assert sorted(i.row_index for i in issues if i.rule_id == "X-906") == [2, 3]
    c = run.by_company()["Glintworks"]
    assert c.readiness is Readiness.BLOCKED and c.proposed_mark == pytest.approx(14.3) and c.realized_cumulative == 0.0
    ids = [f.rule_id for f in c.flags]
    assert ids.count("X-900") == 1 and "X-105" not in ids, ids       # one finding; the note waits for the corrected row
    f = next(f for f in c.flags if f.rule_id == "X-900")
    assert f.evidence["rows"] == [2, 3] and f.evidence["validation"] == ["X-906"]
    assert f.points[0].startswith("Rows **2** and **3** (Acquisition (Closed)) could not be applied.")
    assert "(company, event" not in f.points[0]                        # the column list is for the data checks, not the card
    assert "Delete one of the duplicate rows and rerun" in f.points[1] and "Delete one of the duplicate rows" in f.action
    assert "X-906" in f.message and len(f.message) < 400
    assert [s.rule_id for s in c.steps] == ["M-000", "M-000", "M-000"]   # each copy recorded, then the carry
    assert all("not applied (X-906)" in s.rationale for s in c.steps[:2])


def test_rows_refused_for_different_reasons_are_one_finding_with_one_line_each(tmp_path: Path, cfg):
    pos = position(company="Alpha")
    late = event(date=date(2026, 10, 2), detail="Series B", value=150.0, ownership_after=0.09)          # X-905
    blank = event(date=date(2026, 8, 2), detail="Series B", value=None, ownership_after=0.09)           # X-902
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [late, blank]), cfg)
    c = run.by_company()["Alpha"]
    x900 = [f for f in c.flags if f.rule_id == "X-900"]
    assert len(x900) == 1 and x900[0].evidence["rows"] == [2, 3]
    body = [p for p in x900[0].points if "could not be applied" in p]
    assert len(body) == 2 and any("X-905" in p for p in body) and any("X-902" in p for p in body)
    assert x900[0].action.startswith("Fill in the missing figure on the row; correct the row's date, then rerun (rows 2 and 3")
    assert len(x900[0].points) == 3 and x900[0].points[2].startswith("**Fill in the missing figure on the row; correct the row's date, then rerun.**")


def test_a_refused_row_does_not_get_the_note_screen_but_a_superseded_one_does(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.05, latest_post_money=100.0, prior_mark=5.0)
    announced = event(EventType.ACQ_ANNOUNCED, date=date(2026, 8, 1), detail="Definitive agreement", value=120.0,
                      notes="Signed; $1.0M holdback for indemnities.")
    closed = event(EventType.ACQ_CLOSED, date=date(2026, 9, 1), detail="Closed", value=120.0, ownership_after=0.0, proceeds=6.0)
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [announced, closed]), cfg)
    c = run.by_company()["Alpha"]
    assert "X-105" in {f.rule_id for f in c.flags}          # the superseded announcement's note is still read
    bad = event(date=date(2026, 10, 2), detail="Series B", value=150.0, ownership_after=0.09, notes="$2.0M escrow on the round.")
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [bad], name="b.xlsx"), cfg)
    assert {f.rule_id for f in run2.by_company()["Alpha"].flags if f.rule_id in ("X-105", "X-900")} == {"X-900"}


def test_note_clip_breaks_at_a_word():
    assert _clip("short note") == "short note"
    long = "word " * 60
    out = _clip(long.strip(), 100)
    assert out.endswith(" …") and len(out) <= 103 and not out[:-2].endswith("wor")
    assert _clip(NOTE, 100).endswith(" …") and "asse" not in _clip(NOTE, 100).split()[-2]
