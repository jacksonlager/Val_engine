"""What the pre-demo gauntlet found (scratchpad agentA_report.md), each pinned after its fix.

Two crashes: a second row on a company entering this quarter with a blank cell took the whole run
down; one unfamiliar Status word (or a blank Latest Round) refused the whole workbook. And a set of
rows that came out Ready with a wrong picture: a distribution larger than the mark, a secondary that
sold everything, a secondary whose two prices disagree, a row with no company, a figure in a column
the rule never reads, a first cheque with no amount, a cheque larger than the post-money, a round
labelled "down" at a higher price, a round dated on the prior close that the book already carries,
excess proceeds described as an escrow shortfall, a stale Chapter 11 question after the write-off,
and a retained stake closed to zero.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import OpenItemKind, Readiness, Severity
from tests.conftest import event, make_workbook, position, run_workbook


def _flags(c) -> dict[str, object]:
    return {f.rule_id: f for f in c.flags}


# ---------------------------------------------------------------- the crashes

@pytest.mark.parametrize("second", [
    event(EventType.IPO, date=date(2026, 9, 10), company="Newco", detail="Listed", value=600.0),                  # no ownership
    event(EventType.ACQ_ANNOUNCED, date=date(2026, 9, 10), company="Newco", detail="Offer", notes="Price not disclosed."),   # no value
    event(EventType.SECONDARY, date=date(2026, 9, 10), company="Newco", detail="Secondary", value=20.0, proceeds=0.5),   # no ownership
    event(date=date(2026, 9, 10), company="Newco", detail="Series A", value=60.0, notes="HC did not participate."),   # no ownership
])
def test_a_blank_cell_on_a_second_row_of_an_entering_company_refuses_the_row_not_the_run(tmp_path: Path, cfg, second):
    first = event(EventType.NEW_INVESTMENT, date=date(2026, 7, 10), company="Newco", detail="Seed, Fund III", value=20.0,
                  hc_investment=1.0, ownership_after=0.08, notes="Initial investment.")
    run, issues = run_workbook(make_workbook(tmp_path, [position(company="Alpha")], [first, second]), cfg)
    assert any(i.rule_id == "X-902" and i.row_index == 3 for i in issues)
    c = run.by_company()["Newco"]
    assert c.readiness is Readiness.BLOCKED and c.invested_after == pytest.approx(1.0) and "X-900" in _flags(c)
    assert run.by_company()["Alpha"].readiness is Readiness.READY          # the rest of the book is untouched


@pytest.mark.parametrize("status, expect", [("Exited", "Acquired"), ("Public", "Active"), ("Dissolved", "Shut Down"), ("Realised", "Acquired")])
def test_a_status_synonym_is_read_and_recorded(tmp_path: Path, cfg, status, expect):
    pos = position(company="Alpha", status=status, ownership=0.0 if expect != "Active" else 0.10,
                   prior_mark=0.0 if expect != "Active" else None, realized=12.0 if expect == "Acquired" else 0.0)
    run, issues = run_workbook(make_workbook(tmp_path, [pos, position(company="Beta")], []), cfg)
    assert run.by_company()["Alpha"].status_before.value == expect
    assert any(i.rule_id == "X-915" for i in issues) and "X-925" not in {i.rule_id for i in issues}


def test_an_unknown_status_or_a_blank_round_date_blocks_that_row_and_values_the_rest(tmp_path: Path, cfg):
    weird = position(company="Alpha", status="Pending", ownership=0.10, prior_mark=10.0)
    blank = position(company="Gamma", latest_round=None, first_investment=None)
    run, issues = run_workbook(make_workbook(tmp_path, [weird, blank, position(company="Beta")], []), cfg)
    by = run.by_company()
    assert {i.rule_id for i in issues if i.blocking} == {"X-925"} and len([i for i in issues if i.rule_id == "X-925"]) == 2
    assert by["Alpha"].readiness is Readiness.BLOCKED and "X-925" in _flags(by["Alpha"])["X-900"].message
    assert by["Gamma"].readiness is Readiness.BLOCKED
    assert by["Beta"].readiness is Readiness.READY and run.totals.positions == 3


# ---------------------------------------------------------------- the misses

def test_a_distribution_larger_than_the_mark_is_a_review_not_a_dividend(tmp_path: Path, cfg):
    pos = position(company="Alpha", invested=5.0, prior_mark=10.0)
    big = event(EventType.DISTRIBUTION, date=date(2026, 8, 1), company="Alpha", detail="Cash distribution", proceeds=50.0,
                notes="Distribution to shareholders.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [big]), cfg)
    c = run.by_company()["Alpha"]
    f = _flags(c)["X-111"]
    assert f.severity is Severity.REVIEW and c.realized_cumulative == pytest.approx(50.0) and c.proposed_mark == pytest.approx(10.0)
    assert {s.key for s in f.suggestions} == {"as_proposed", "write_to_zero"}
    small = event(EventType.DISTRIBUTION, date=date(2026, 8, 1), company="Alpha", detail="Dividend", proceeds=0.4, notes="Quarterly dividend.")
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [small], name="b.xlsx"), cfg)
    assert _flags(run2.by_company()["Alpha"])["X-111"].severity is Severity.MONITOR
    liq = event(EventType.DISTRIBUTION, date=date(2026, 9, 12), company="Alpha", detail="Final distribution", proceeds=0.3,
                notes="Final liquidating distribution after the wind-down; the company was dissolved on 12 September.")
    run3, _ = run_workbook(make_workbook(tmp_path, [pos], [liq], name="c.xlsx"), cfg)
    fl = _flags(run3.by_company()["Alpha"])
    assert "X-105" in fl and {"liquidating", "dissolved"} & set(fl["X-105"].evidence["terms"])


def test_selling_the_whole_stake_is_an_exit(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.10, latest_post_money=100.0, prior_mark=10.0, invested=5.0)
    whole = event(EventType.SECONDARY, date=date(2026, 8, 20), company="Alpha", detail="HC sold its entire position", value=100.0,
                  ownership_after=0.0, proceeds=10.0, notes="Whole stake sold to a secondary fund.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [whole]), cfg)
    c = run.by_company()["Alpha"]
    assert c.status_after.value == "Acquired" and c.proposed_mark == 0.0 and c.ownership_after == 0.0 and c.realized_cumulative == pytest.approx(10.0)
    assert c.action.value == "Full exit" and "X-104" not in _flags(c)
    cheap = event(EventType.SECONDARY, date=date(2026, 8, 20), company="Alpha", detail="Sold everything", value=50.0, ownership_after=0.0, proceeds=5.0)
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [cheap], name="b.xlsx"), cfg)
    assert "X-104" in _flags(run2.by_company()["Alpha"])


def test_a_secondary_whose_two_prices_disagree_is_a_review(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.10, latest_post_money=100.0, prior_mark=10.0)
    row = event(EventType.SECONDARY, date=date(2026, 8, 19), company="Alpha", detail="HC sold 30% of its position", value=100.0,
                ownership_after=0.07, proceeds=1.5, notes="Buyer paid a price consistent with the latest round.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [row]), cfg)
    f = _flags(run.by_company()["Alpha"])["X-104"]
    assert f.evidence["implied_from_proceeds"] == pytest.approx(50.0) and f.evidence["gap_pct"] == pytest.approx(-0.5)
    assert any(s.key == "at_proceeds_price" and s.booked == pytest.approx(0.07 * 50.0) for s in f.suggestions)


def test_a_row_with_no_company_is_a_blocking_data_check(tmp_path: Path, cfg):
    stray = event(date=date(2026, 8, 15), company="", detail="Series B", value=150.0, ownership_after=0.09)
    run, issues = run_workbook(make_workbook(tmp_path, [position(company="Alpha")], [stray]), cfg)
    assert any(i.rule_id == "X-914" and i.blocking and "no company" in i.message for i in issues)


def test_a_figure_in_a_column_the_rule_does_not_read_reaches_a_person(tmp_path: Path, cfg):
    pos = position(company="Alpha")
    rows = [event(EventType.TERM_SHEET, date=date(2026, 8, 1), company="Alpha", detail="Series B term sheet at ~$120M post", value=120.0, proceeds=2.0),
            event(EventType.DISTRIBUTION, date=date(2026, 8, 2), company="Alpha", detail="Cash distribution", proceeds=1.5, ownership_after=0.07)]
    run, _ = run_workbook(make_workbook(tmp_path, [pos], rows), cfg)
    c = run.by_company()["Alpha"]
    x134 = [f for f in c.flags if f.rule_id == "X-134"]
    assert len(x134) == 2 and "Proceeds to HC" in x134[0].points[0] and "HC Ownership After" in x134[1].points[0]
    clean = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, hc_investment=1.0, ownership_after=0.105,
                  notes="$30M round led by a new investor.")
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [clean], name="b.xlsx"), cfg)
    assert "X-134" not in _flags(run2.by_company()["Alpha"])


def test_a_first_cheque_with_no_amount_and_a_cheque_above_the_post_money_are_refused(tmp_path: Path, cfg):
    book = [position(company="Alpha")]
    no_cheque = event(EventType.NEW_INVESTMENT, date=date(2026, 8, 1), company="Newco", detail="Seed round, Fund III", value=20.0, ownership_after=0.08)
    run, issues = run_workbook(make_workbook(tmp_path, book, [no_cheque]), cfg)
    assert any(i.rule_id == "X-902" and "cheque" in i.message for i in issues) and run.by_company()["Newco"].readiness is Readiness.BLOCKED
    huge = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, hc_investment=500.0, ownership_after=0.105,
                 notes="Led by a new investor.")
    run2, issues2 = run_workbook(make_workbook(tmp_path, book, [huge], name="b.xlsx"), cfg)
    assert any(i.rule_id == "X-903" and "larger than" in i.message for i in issues2)
    assert run2.by_company()["Alpha"].readiness is Readiness.BLOCKED and run2.by_company()["Alpha"].invested_after == pytest.approx(5.0)


def test_a_down_round_label_on_a_higher_price_is_a_review(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=100.0, ownership=0.10, prior_mark=10.0)
    row = event(date=date(2026, 8, 15), company="Alpha", detail="Series B down round", value=150.0, ownership_after=0.09, notes="Round led by a new investor.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [row]), cfg)
    c = run.by_company()["Alpha"]
    assert "X-135" in _flags(c) and c.readiness is Readiness.NEEDS_REVIEW and c.proposed_mark == pytest.approx(0.09 * 150.0)


# ---------------------------------------------------------------- the wrong ones

def test_a_round_the_book_already_carries_is_not_applied_twice(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_round=date(2026, 6, 30), latest_post_money=100.0, ownership=0.10, invested=5.0, prior_mark=10.0)
    again = event(date=date(2026, 6, 30), company="Alpha", detail="Series A", value=100.0, hc_investment=5.0, ownership_after=0.10,
                  notes="$20M round led by a new investor.")
    run, issues = run_workbook(make_workbook(tmp_path, [pos], [again]), cfg)
    assert any(i.rule_id == "X-927" for i in issues)
    c = run.by_company()["Alpha"]
    assert c.invested_after == pytest.approx(5.0) and c.readiness is Readiness.BLOCKED and "X-927" in _flags(c)["X-900"].message


def test_excess_proceeds_are_a_preference_question_not_an_escrow_shortfall(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.10, prior_mark=10.0)
    row = event(EventType.ACQ_CLOSED, date=date(2026, 8, 20), company="Alpha", detail="All-cash acquisition", value=100.0, proceeds=20.0,
                notes="Cash received at closing.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [row]), cfg)
    c = run.by_company()["Alpha"]
    f = _flags(c)["X-101"]
    assert f.evidence["excess"] == pytest.approx(10.0) and "preference" in f.message and "escrow" not in f.message.lower()
    assert c.open_items == () and c.realized_cumulative == pytest.approx(20.0) and c.status_after.value == "Acquired"


def test_a_shutdown_after_chapter_11_settles_the_chapter_11_question(tmp_path: Path, cfg):
    pos = position(company="Alpha", prior_mark=10.0)
    rows = [event(EventType.BANKRUPTCY_CH11, date=date(2026, 7, 20), company="Alpha", detail="Filed Chapter 11", ownership_after=0.10),
            event(EventType.SHUTDOWN, date=date(2026, 9, 20), company="Alpha", detail="Converted to Chapter 7",
                  notes="Case converted to Chapter 7; equity cancelled. No recovery expected.")]
    run, _ = run_workbook(make_workbook(tmp_path, [pos], rows), cfg)
    c = run.by_company()["Alpha"]
    assert c.status_after.value == "Shut Down" and c.proposed_mark == 0.0 and "X-116" not in _flags(c)
    assert c.readiness is not Readiness.BLOCKED


def test_a_retained_stake_on_an_exit_is_a_position_not_an_escrow(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.10, prior_mark=10.0, invested=5.0)
    row = event(EventType.ACQ_CLOSED, date=date(2026, 8, 20), company="Alpha", detail="Acquisition, HC rolls part of its stake", value=100.0,
                proceeds=8.0, ownership_after=0.02, notes="HC received $8.0M cash for 8% and rolled the remaining 2% into the buyer.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [row]), cfg)
    c = run.by_company()["Alpha"]
    assert c.status_after.value == "Active" and c.ownership_after == pytest.approx(0.02) and c.proposed_mark == pytest.approx(2.0)
    assert c.realized_cumulative == pytest.approx(8.0) and "X-112" in _flags(c) and c.readiness is Readiness.BLOCKED
    assert any(i.kind is OpenItemKind.ACQUIRER_SHARES for i in c.open_items) and not any(i.kind is OpenItemKind.UNCONFIRMED_EXIT for i in c.open_items)
