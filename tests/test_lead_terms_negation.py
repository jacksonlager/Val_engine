"""'No new investor' names nobody (HARDENING_REPORT.md, D-6).

X-122 is REVIEW when a ≥3× step-up has no outside investor named on the row and MONITOR when one
is. The lead test used a plain substring match, so the negated phrase counted as a named lead and
the finding was downgraded. It now reads the sentence the way the note screen does.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from hc_valuation.engine.textscreen import any_term_in, term_in
from tests.conftest import event, make_workbook, position, run_workbook


def _x122(run):
    return next(f for f in run.by_company()["Alpha"].flags if f.rule_id == "X-122")


def test_reader_handles_negation_and_whole_words():
    assert term_in("new investor", "round led by a new investor")
    assert not term_in("new investor", "insider-led round. No new investor.")
    assert not term_in("lead", "misleading paperwork")


def test_step_up_with_a_negated_lead_phrase_is_review(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=4.3, ownership=0.099, prior_mark=0.4257, latest_round=date(2026, 3, 15))
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [event(detail="Series A", value=13.0, ownership_after=0.085,
                                                                 notes="$3.0M insider-led round. No new investor.")]), cfg)
    assert _x122(run).severity.value == "REVIEW" and _x122(run).evidence["new_lead_named"] is False


def test_step_up_with_a_named_lead_is_monitor(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=4.3, ownership=0.099, prior_mark=0.4257, latest_round=date(2026, 3, 15))
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [event(detail="Series A", value=13.0, ownership_after=0.085,
                                                                 notes="$3.0M round led by a new investor.")], name="b.xlsx"), cfg)
    assert _x122(run).severity.value == "MONITOR" and _x122(run).evidence["new_lead_named"] is True
