"""An identical activity row pasted twice is refused on both copies (HARDENING_REPORT.md, D-10).

Found by the synthetic Q4 2026 malformed set: a duplicated funded round carried a non-blocking X-906
REVIEW and was applied twice, so HC's 1.0 cheque went on the book as 2.0 of invested capital with
nothing stopping the quarter. A duplicated secondary would have doubled realized cash the same way.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import Readiness
from tests.conftest import event, make_workbook, position, run_workbook


def test_duplicated_funded_round_blocks_both_rows_and_is_applied_nowhere(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=75.5, ownership=0.118, prior_mark=8.909, invested=5.1)
    row = event(detail="Series B", value=100.0, hc_investment=1.0, ownership_after=0.128, notes="$24.0M round led by a new investor.")
    run, issues = run_workbook(make_workbook(tmp_path, [pos], [row, dict(row)]), cfg)
    dup = [i for i in issues if i.rule_id == "X-906"]
    assert [(i.row_index, i.blocking) for i in dup] == [(2, True), (3, True)]
    c = run.by_company()["Alpha"]
    assert c.readiness is Readiness.BLOCKED and "X-900" in {f.rule_id for f in c.flags}
    assert c.invested_after == pytest.approx(5.1) and c.proposed_mark == pytest.approx(8.909)   # not 2.0 of cheque, not 12.8
    assert [s.rule_id for s in c.steps] == ["M-000", "M-000", "M-000"] or "M-010" not in [s.rule_id for s in c.steps]


def test_duplicated_secondary_does_not_double_the_proceeds(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=1837.9, ownership=0.040, prior_mark=73.516, invested=10.3)
    row = event(EventType.SECONDARY, detail="HC sold 25% of its position", value=1837.9, ownership_after=0.030, proceeds=18.379)
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [row, dict(row)]), cfg)
    c = run.by_company()["Alpha"]
    assert c.realized_quarter == 0.0 and c.readiness is Readiness.BLOCKED


def test_two_tranches_that_differ_are_not_duplicates(tmp_path: Path, cfg):
    """Same day, same round, different cheques: two real rows, both applied, nothing blocks."""
    pos = position(company="Alpha", latest_post_money=75.5, ownership=0.118, prior_mark=8.909, invested=5.1)
    a = event(detail="Series B", value=100.0, hc_investment=1.0, ownership_after=0.128, notes="First close.")
    b = event(detail="Series B", value=100.0, hc_investment=0.5, ownership_after=0.133, notes="Second close, same day.")
    run, issues = run_workbook(make_workbook(tmp_path, [pos], [a, b]), cfg)
    assert not [i for i in issues if i.rule_id == "X-906"]
    c = run.by_company()["Alpha"]
    assert c.invested_after == pytest.approx(6.6) and c.readiness is not Readiness.BLOCKED
