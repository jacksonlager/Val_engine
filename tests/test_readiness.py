"""Readiness, action and approval — three questions that used to be one field.

`Disposition` counts findings; a position with four flags still has one readiness. And the
quarter's movement splits into capital activity and performance on one convention, so an exit
that returned more cash than its carrying value reads as the gain it was.
"""
from __future__ import annotations

import pytest
from conftest import run_real  # noqa: F401 — fixture

from hc_valuation.engine.models import Approval, Readiness, Severity, ValuationAction
from hc_valuation.engine.readiness import action_of, readiness_of, unresolved, valuation_change


def flag(rule_id: str, severity=Severity.REVIEW, family="treatment"):
    from hc_valuation.engine.models import Flag
    return Flag(rule_id=rule_id, family=family, severity=severity, message="m", action="a")


def override(*rule_ids: str):
    from datetime import date
    from hc_valuation.engine.models import OverrideRecord
    return OverrideRecord(company="X", quarter="Q3 2026", proposed=1.0, booked=1.0, reason="r",
                          approver="a", created_at=date(2026, 9, 30), rule_ids_addressed=tuple(rule_ids))


# ---------------------------------------------------------------- readiness

def test_a_missing_input_blocks_and_a_judgment_does_not():
    """Both were BLOCK. One cannot be booked at any price; the other has a defensible number."""
    assert readiness_of((flag("X-113", Severity.BLOCK),), None) is Readiness.BLOCKED
    assert readiness_of((flag("X-101", Severity.BLOCK),), None) is Readiness.NEEDS_REVIEW
    assert readiness_of((flag("X-102", Severity.BLOCK),), None) is Readiness.NEEDS_REVIEW


def test_a_provisional_mark_blocks_until_a_decision_names_it():
    """A stand-in is never proposed as final — but a committee that names the rule has accepted
    it knowingly, and the ledger carries the reason."""
    assert readiness_of((flag("X-101", Severity.BLOCK),), None, provisional_rule="X-101") is Readiness.BLOCKED
    assert readiness_of((flag("X-101", Severity.BLOCK),), override("X-101"),
                        provisional_rule="X-101") is Readiness.READY


def test_monitor_findings_never_hold_a_position_back():
    assert readiness_of((flag("X-201", Severity.MONITOR, "staleness"),), None) is Readiness.READY
    assert readiness_of((), None) is Readiness.READY


def test_a_decision_clears_only_what_it_names():
    flags = (flag("X-102", Severity.BLOCK), flag("X-302", Severity.REVIEW, "growth"))
    assert readiness_of(flags, override("X-102")) is Readiness.NEEDS_REVIEW      # X-302 still open
    assert readiness_of(flags, override("X-102", "X-302")) is Readiness.READY
    assert [f.rule_id for f in unresolved(flags, override("X-102"))] == ["X-302"]


# ---------------------------------------------------------------- action

@pytest.mark.parametrize("rules,terminal,expected", [
    ((), False, ValuationAction.CARRY),
    (("M-000",), False, ValuationAction.CARRY),
    (("M-010",), False, ValuationAction.REVALUE),
    (("M-014",), False, ValuationAction.NEW_INVESTMENT),
    (("M-030",), False, ValuationAction.PARTIAL_EXIT),
    (("M-020",), True, ValuationAction.FULL_EXIT),
    (("M-021",), True, ValuationAction.WRITE_OFF),
])
def test_the_action_is_the_shape_of_the_quarter(rules, terminal, expected):
    assert action_of(rules, terminal=terminal, realized_quarter=0.0, new_investment=0.0) is expected


def test_a_company_that_left_the_book_earlier_does_not_exit_again():
    """Cash arriving after a prior-quarter exit is a distribution, not this quarter's exit."""
    assert action_of(("M-000", "M-022"), terminal=True, realized_quarter=0.8, new_investment=0.0,
                     already_terminal=True) is ValuationAction.CARRY


# ---------------------------------------------------------------- movement

def test_an_exit_above_its_carrying_value_is_a_gain_not_a_loss():
    """Cindral: opened at 18.2, returned 28.2, closes at zero. The change in carrying value is
    -18.2; the performance is +10.0, and the bridge must say the second."""
    assert valuation_change(18.2, 0.0, new_investment=0.0, realized_quarter=28.2) == 10.0


def test_new_money_is_capital_not_performance():
    """Duskfern put 0.5 into a note and the mark rose by exactly that: no gain."""
    assert valuation_change(6.1, 6.6, new_investment=0.5, realized_quarter=0.0) == 0.0
    assert valuation_change(38.5, 73.52, new_investment=0.0, realized_quarter=0.0) == 35.02


# ---------------------------------------------------------------- the real book

def test_the_book_reconciles_on_one_convention(run_real):
    """opening + new investment + valuation gain/loss - realized = closing, position by position
    and in total. If this ever fails, the bridge and the table are telling different stories."""
    t = run_real.totals
    assert t.prior_nav + t.new_investment + t.valuation_change - t.realized_quarter == pytest.approx(t.booked_nav, abs=1e-6)
    for c in run_real.companies:
        assert (c.prior_mark + c.new_investment_quarter + c.valuation_change_quarter
                - c.realized_quarter) == pytest.approx(c.booked_mark, abs=1e-6), c.company


def test_readiness_counts_companies_and_dispositions_count_findings(run_real):
    t = run_real.totals
    assert sum(t.readiness.values()) == t.positions == 100
    assert set(t.readiness) == {"Blocked", "Needs Review", "Ready"}
    assert t.readiness["Blocked"] == 1 and t.readiness["Needs Review"] == 26 and t.readiness["Ready"] == 73
    assert t.monitor_positions == 57, "a watch item rides alongside any readiness, including Ready"
    assert sum(1 for c in run_real.companies if c.monitor and c.readiness is Readiness.READY) > 0


def test_drayvenn_is_blocked_on_a_missing_price_and_says_so(run_real):
    d = run_real.by_company()["Drayvenn"]
    assert d.readiness is Readiness.BLOCKED and d.provisional
    assert "closing price" in d.provisional_reason and "30 Sep 2026" in d.provisional_reason
    assert d.approval is Approval.NONE, "nothing is approved until a person signs it"


def test_cindral_is_a_full_exit_at_a_gain(run_real):
    c = run_real.by_company()["Cindral"]
    assert c.action is ValuationAction.FULL_EXIT and c.readiness is Readiness.READY
    assert c.booked_mark == 0.0 and c.realized_quarter == 28.2
    assert c.valuation_change_quarter == pytest.approx(10.0)
