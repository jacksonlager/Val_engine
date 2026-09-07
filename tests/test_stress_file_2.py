"""What the second stress workbook (HC_Q3_2026_Stress_Test_2.xlsx) found, each as its own case.

* A `New Investment` row on a company the Portfolio tab already carries at the same round is a
  double count: refused (X-924), the position Blocked, nothing booked. A New Investment at a
  different price and a higher stake is a follow-on filed under the wrong label and applies.
* A terminated deal's break fee is cash to HC: realized, the stake unchanged.
* A direct listing has no lock-up unless the row says so; an IPO whose row says the shares are
  freely tradable has none either. No lock-up item, no "cannot sell until" line.
* "no new outside investor set the price" names nobody: a 3.8× step-up on it is a review (X-122).
* The cheque reconciliation uses the round size when the text states it, so a clean pro-rata
  cheque (Jettamar on the shipped book) is not a price error, and only a stake beyond what a pool
  top-up could explain is a finding.
* Words a row's own rule already answers (restated on an ownership adjustment, accrued on a note
  repayment, write-off on a Chapter 11, lock-up on a stock exit) are not raised again by X-105.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import OpenItemKind, Readiness, Severity
from hc_valuation.engine.textscreen import term_in
from tests.conftest import event, make_workbook, position, run_workbook


def _flags(c) -> dict[str, object]:
    return {f.rule_id: f for f in c.flags}


def test_new_investment_that_repeats_the_book_is_refused(tmp_path: Path, cfg):
    pos = position(company="Gablewood", latest_post_money=10.1, ownership=0.063, invested=1.0, prior_mark=0.6,
                   first_investment=date(2024, 7, 8), latest_round=date(2025, 9, 10))
    row = event(EventType.NEW_INVESTMENT, date=date(2026, 9, 4), company="Gablewood", detail="Seed round, recorded as a first check",
                value=10.1, hc_investment=1.0, ownership_after=0.063,
                notes="Recorded as a first investment, but the Portfolio tab already carries this position at 6.3% from the same round.")
    run, issues = run_workbook(make_workbook(tmp_path, [pos], [row]), cfg)
    assert any(i.rule_id == "X-924" and i.blocking and i.row_index == 2 for i in issues)
    c = run.by_company()["Gablewood"]
    assert c.readiness is Readiness.BLOCKED and c.invested_after == pytest.approx(1.0) and c.proposed_mark == pytest.approx(0.6)
    x900 = _flags(c)["X-900"]
    assert "Decide which record is right" in x900.action and x900.evidence["validation"] == ["X-924"]
    assert "X-120" not in _flags(c)


def test_new_investment_at_a_higher_stake_and_a_new_price_is_a_follow_on(tmp_path: Path, cfg):
    pos = position(company="Tidewell", latest_post_money=13.9, ownership=0.087, invested=1.4, prior_mark=1.2)
    row = event(EventType.NEW_INVESTMENT, date=date(2026, 8, 28), company="Tidewell", detail="Seed extension, Fund III",
                value=20.0, hc_investment=0.5, ownership_after=0.10, notes="Filed as a first cheque; it is a follow-on.")
    run, issues = run_workbook(make_workbook(tmp_path, [pos], [row]), cfg)
    assert "X-924" not in {i.rule_id for i in issues}
    c = run.by_company()["Tidewell"]
    assert c.proposed_mark == pytest.approx(2.0) and c.invested_after == pytest.approx(1.9) and c.ownership_after == pytest.approx(0.10)


def test_break_fee_on_a_terminated_deal_is_realized(tmp_path: Path, cfg):
    pos = position(company="Fenwright", latest_post_money=285.1, ownership=0.038, invested=12.4, prior_mark=10.8)
    ann = event(EventType.ACQ_ANNOUNCED, date=date(2026, 7, 30), company="Fenwright", detail="Definitive agreement, all cash", value=340.0,
                notes="All-cash agreement signed, expected to close in Q4 subject to antitrust clearance.")
    term = event(EventType.ACQ_TERMINATED, date=date(2026, 9, 19), company="Fenwright", detail="Buyer withdrew after diligence",
                 ownership_after=0.038, proceeds=0.5,
                 notes="The July agreement was terminated on antitrust grounds. A $0.5M break fee was received. HC's stake is unchanged.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [ann, term]), cfg)
    c = run.by_company()["Fenwright"]
    assert c.realized_cumulative == pytest.approx(0.5) and c.ownership_after == pytest.approx(0.038)
    assert c.proposed_mark == pytest.approx(0.038 * 285.1) and "X-114" in _flags(c) and "X-105" not in _flags(c)
    assert _flags(c)["X-114"].evidence["break_fee"] == pytest.approx(0.5)
    assert any("break fee" in s.rationale for s in c.steps if s.rule_id == "M-051")


def test_direct_listing_has_no_lockup_unless_the_row_says_so(tmp_path: Path, cfg):
    pos = position(company="Mardellan", stage="Series D+", latest_post_money=5699.4, ownership=0.012, invested=10.9, prior_mark=68.4)
    dl = event(EventType.DIRECT_LISTING, date=date(2026, 9, 15), company="Mardellan", detail="Direct listing on the NYSE", value=6400.0,
               ownership_after=0.012, notes="Direct listing; no new capital raised. HC's shares are not subject to a lock-up and were freely tradable from the first day.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [dl]), cfg)
    c = run.by_company()["Mardellan"]
    assert not any(i.kind is OpenItemKind.IPO_LOCKUP for i in c.open_items)
    x101 = _flags(c)["X-101"]
    assert "No lock-up" in x101.points[1] and "cannot sell" not in x101.message and x101.evidence["lockup_end"] is None
    assert "X-105" not in _flags(c)
    ipo = event(EventType.IPO, date=date(2026, 9, 20), company="Mardellan", detail="Listed on Nasdaq", value=6400.0, ownership_after=0.012,
                notes="Priced at the top of the range. HC shares subject to a 180-day lock-up.")
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [ipo], name="b.xlsx"), cfg)
    c2 = run2.by_company()["Mardellan"]
    assert any(i.kind is OpenItemKind.IPO_LOCKUP for i in c2.open_items) and "cannot sell until" in _flags(c2)["X-101"].points[1]


def test_negation_two_words_before_the_term():
    assert not term_in("outside investor", "Existing holders only; no new outside investor set the price.")
    assert not term_in("lock-up", "HC's shares are not subject to any lock-up.")
    assert term_in("outside investor", "An outside investor set the price.")
    assert term_in("lock-up", "HC shares subject to a 180-day lock-up.")


def test_internal_step_up_with_no_outside_investor_is_a_review(tmp_path: Path, cfg):
    pos = position(company="Alderpoint", stage="Seed", latest_post_money=12.5, ownership=0.103, invested=1.0, prior_mark=1.3, arr=0.4)
    rnd = event(date=date(2026, 9, 9), company="Alderpoint", detail="Series A, internal round", value=47.0, hc_investment=0.4, ownership_after=0.088,
                notes="Priced at 3.8x the last round. Existing holders only; no new outside investor set the price.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [rnd]), cfg)
    f = _flags(run.by_company()["Alderpoint"])["X-122"]
    assert f.severity is Severity.REVIEW and f.evidence["new_lead_named"] is False


def test_cheque_reconciliation_uses_the_round_size(tmp_path: Path, cfg):
    # a clean pro-rata cheque: 10.8% diluted by a $10.8M round at $43M post, plus $1.3M bought -> 11.1%
    pos = position(company="Jettamar", latest_post_money=27.0, ownership=0.108, invested=2.5, prior_mark=2.9)
    ok = event(date=date(2026, 7, 8), company="Jettamar", detail="Series A", value=43.0, hc_investment=1.3, ownership_after=0.111,
               notes="$10.8M round led by a new investor. HC participated pro rata.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [ok]), cfg)
    assert "X-119" not in _flags(run.by_company()["Jettamar"])
    # a cheque typed in the wrong units: $20M into a $26M round at $130M post cannot leave HC at 7.9%
    pos2 = position(company="Harrowgate", latest_post_money=86.9, ownership=0.07, invested=5.4, prior_mark=6.1)
    bad = event(date=date(2026, 9, 5), company="Harrowgate", detail="Series B", value=130.0, hc_investment=20.0, ownership_after=0.079,
                notes="$26.0M Series B led by a new investor.")
    run2, _ = run_workbook(make_workbook(tmp_path, [pos2], [bad], name="b.xlsx"), cfg)
    f = _flags(run2.by_company()["Harrowgate"])["X-119"]
    assert f.evidence["round_size"] == 26.0 and f.evidence["expected_ownership"] > 0.2 and "round arithmetic" in f.suggestions[1].label
    # a small gap (a pool top-up's worth) is not a finding; a row that says the figures do not reconcile still reaches a person
    mild = event(date=date(2026, 9, 5), company="Harrowgate", detail="Series B", value=130.0, hc_investment=2.0, ownership_after=0.079,
                 notes="$26.0M Series B led by a new investor. HC's cheque and the stated post-money do not reconcile; confirm pre- or post-money.")
    run3, _ = run_workbook(make_workbook(tmp_path, [pos2], [mild], name="c.xlsx"), cfg)
    fl = _flags(run3.by_company()["Harrowgate"])
    assert "X-119" not in fl and "X-105" in fl and "reconcile" in " ".join(fl["X-105"].evidence["terms"])


def test_words_a_rule_already_answers_are_not_raised_again(tmp_path: Path, cfg):
    book = [position(company="Quindle", latest_post_money=61.1, ownership=0.121, invested=6.0, prior_mark=7.4),
            position(company="Nimbrel", stage="Seed", latest_post_money=18.1, ownership=0.065, invested=0.8, prior_mark=1.2),
            position(company="Stonegather", latest_post_money=18.1, ownership=0.094, invested=1.4, prior_mark=1.7),
            position(company="Zealwick", latest_post_money=92.0, ownership=0.037, invested=4.0, prior_mark=3.4)]
    rows = [
        event(EventType.OWNERSHIP_ADJUSTMENT, date=date(2026, 7, 21), company="Quindle", detail="Option pool expansion", ownership_after=0.109,
              notes="The board expanded the option pool by 200 basis points. No new money and no new price; the cap table was restated."),
        event(EventType.NOTE_REPAID, date=date(2026, 8, 31), company="Nimbrel", detail="March 2026 bridge note repaid at par", ownership_after=0.065, proceeds=0.6,
              notes="The bridge note was repaid in cash at par plus accrued interest rather than converting."),
        event(EventType.BANKRUPTCY_CH11, date=date(2026, 9, 11), company="Stonegather", detail="Filed for reorganisation", ownership_after=0.094,
              notes="Operations continue under debtor-in-possession financing. Recovery to equity is unknown and a write-off has not been decided."),
        event(EventType.ACQ_CLOSED, date=date(2026, 9, 23), company="Zealwick", detail="All-stock acquisition by a listed buyer", value=128.0,
              notes="Consideration was entirely acquirer stock; no cash was received. HC's shares were cancelled and exchanged for listed shares subject to a 90-day lock-up."),
    ]
    run, _ = run_workbook(make_workbook(tmp_path, book, rows), cfg)
    by = run.by_company()
    for name, own in (("Quindle", "X-110"), ("Nimbrel", "X-115"), ("Stonegather", "X-116"), ("Zealwick", "X-112")):
        fl = _flags(by[name])
        assert own in fl and "X-105" not in fl, (name, sorted(fl))
