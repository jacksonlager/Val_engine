"""Activity-tab situations a venture fund's quarter can contain that the shipped Q3 2026 workbook
and the second stress file do not, each pinned where the engine came out right:

* A funded SAFE with an MFN clause is a bridge (M-060): the cheque sits on its own leg at cost,
  the equity mark does not move, and the bridge question (X-107) reaches a person.
* An event type the fund invents ("Note Extension", "Dividend Recap") blocks under M-999; a
  non-USD currency anywhere in the row's text refuses the row (X-920) and nothing books.
* Two priced rounds in one quarter apply in date order; whichever way round, the down round's
  allocation question (X-102) survives and the final mark is the later round's.
* A secondary at a premium, a secondary purchase at a discount, and a cheque that implies a
  different price than the row all reach a person (X-104, X-119); the stake is marked at the
  round price and the cash is realized.
* An announced deal that closes in the same quarter at a different price books the closing
  price and nothing pending; a term sheet on a company that shuts down the same quarter leaves
  no open item; a shutdown that returns more than the mark asks whether it was really a sale.
* A priced round that leaves HC with nothing, a negative distribution, a closed exit with no
  deal value, a Portfolio row with zero ownership or a prior mark that does not reconcile: each
  holds the prior mark and blocks or reviews, never books.
* Cash arriving on the same day as the shutdown, an IPO whose lock-up ends in the quarter, a
  PIPE into a listed holding, a bridge repaid with no note on the book: the arithmetic is right
  and a person sees what needs seeing.
* With the note reader on (a fake here), a stated pre-money (X-131), an insolvency in an
  operating update and a dissolution filed as a distribution (X-130) all reach a person.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import MarketData, OpenItemKind, OverrideLedger, Readiness, Severity, Status
from hc_valuation.engine.run import run_valuation
from hc_valuation.ingest.reader import read_workbook
from hc_valuation.ingest.validate import validate
from hc_valuation.notes import AspectKind, RowReading
from hc_valuation.notes.schema import Aspect, Conflict
from tests.conftest import GENERATED_AT, event, make_workbook, position, run_workbook


def _flags(c) -> dict[str, object]:
    return {f.rule_id: f for f in c.flags}


def _run(tmp_path: Path, cfg, positions, events, **kw):
    return run_workbook(make_workbook(tmp_path, positions, events), cfg, **kw)


# ---------------------------------------------------------------- notes and SAFEs

def test_funded_safe_with_mfn_is_a_bridge_on_its_own_leg(tmp_path: Path, cfg):
    row = event("SAFE", detail="Post-money SAFE, $150M cap, MFN clause", hc_investment=0.5,
                notes="HC put $0.5M into a post-money SAFE with a $150M cap and a most-favoured-nation clause.")
    run, issues = _run(tmp_path, cfg, [position()], [row])
    c = run.by_company()["Alpha"]
    assert any(i.rule_id == "X-912" for i in issues)                      # "SAFE" read as Convertible Note, recorded
    assert c.equity_mark == pytest.approx(10.0) and c.note_at_cost == pytest.approx(0.5)
    assert c.proposed_mark == pytest.approx(10.5) and c.invested_after == pytest.approx(5.5)
    assert c.readiness is Readiness.NEEDS_REVIEW and _flags(c)["X-107"].severity is Severity.REVIEW
    assert _flags(c)["X-107"].evidence["valuation_cap"] == pytest.approx(150.0)
    assert any(i.kind is OpenItemKind.CONVERTIBLE_NOTE for i in c.open_items)


def test_bridge_funded_and_repaid_in_the_same_quarter_leaves_no_leg(tmp_path: Path, cfg):
    rows = [event(EventType.CONVERTIBLE_NOTE, date=date(2026, 7, 10), detail="$1.0M bridge note, $120.0M valuation cap", hc_investment=1.0),
            event(EventType.NOTE_REPAID, date=date(2026, 9, 10), detail="Bridge repaid at par", hc_investment=1.0, proceeds=1.02)]
    run, _ = _run(tmp_path, cfg, [position()], rows)
    c = run.by_company()["Alpha"]
    assert [s.rule_id for s in c.steps] == ["M-060", "M-061"]
    assert c.note_at_cost == 0.0 and c.proposed_mark == pytest.approx(10.0)
    assert c.invested_after == pytest.approx(6.0) and c.realized_cumulative == pytest.approx(1.02)
    assert not any(i.kind is OpenItemKind.CONVERTIBLE_NOTE for i in c.open_items)


def test_note_repaid_with_no_note_on_the_book_asks_where_the_principal_sat(tmp_path: Path, cfg):
    row = event(EventType.NOTE_REPAID, detail="Bridge repaid at par", proceeds=0.6, hc_investment=0.5,
                notes="Repaid at par plus accrued interest.")
    run, _ = _run(tmp_path, cfg, [position()], [row])
    c = run.by_company()["Alpha"]
    assert c.realized_cumulative == pytest.approx(0.6) and c.note_at_cost == 0.0 and c.proposed_mark == pytest.approx(10.0)
    f = _flags(c)["X-115"]
    assert f.severity is Severity.REVIEW and f.evidence["principal_not_in_note_leg"] == pytest.approx(0.5)
    assert "X-105" not in _flags(c)                                       # "accrued" is the rule's own business


# ---------------------------------------------------------------- unknown events and currency

@pytest.mark.parametrize("raw, detail", [("Note Extension", "Maturity extended to Dec 2027"),
                                         ("Dividend Recap", "Leveraged recapitalisation")])
def test_an_event_type_the_fund_invents_blocks_under_m999(tmp_path: Path, cfg, raw, detail):
    run, issues = _run(tmp_path, cfg, [position()], [event(raw, detail=detail, proceeds=1.5)])
    c = run.by_company()["Alpha"]
    assert any(i.rule_id == "X-909" and i.blocking for i in issues)
    assert c.readiness is Readiness.BLOCKED and "M-999" in _flags(c)
    assert c.proposed_mark == pytest.approx(10.0) and c.realized_cumulative == 0.0   # nothing from the row is booked


def test_a_cheque_in_euros_refuses_the_row(tmp_path: Path, cfg):
    row = event(detail="Series B", value=150.0, hc_investment=1.0, ownership_after=0.105,
                notes="$30M Series B led by a new investor. HC invested EUR 1.0M.")
    run, issues = _run(tmp_path, cfg, [position()], [row])
    c = run.by_company()["Alpha"]
    assert any(i.rule_id == "X-920" and i.blocking for i in issues)
    assert c.readiness is Readiness.BLOCKED and _flags(c)["X-900"].evidence["validation"] == ["X-920"]
    assert c.proposed_mark == pytest.approx(10.0) and c.invested_after == pytest.approx(5.0) and c.ownership_after == pytest.approx(0.10)


# ---------------------------------------------------------------- two rounds in one quarter

def test_up_round_then_down_round_ends_on_the_down_round_and_blocks_on_allocation(tmp_path: Path, cfg):
    rows = [event(date=date(2026, 7, 10), detail="Series B", value=150.0, ownership_after=0.09, notes="$30M round led by a new investor."),
            event(date=date(2026, 9, 20), detail="Series B-1", value=100.0, ownership_after=0.095, hc_investment=0.5, notes="Insider round at a lower price.")]
    run, _ = _run(tmp_path, cfg, [position()], rows)
    c = run.by_company()["Alpha"]
    assert [s.rule_id for s in c.steps] == ["M-010", "M-012"]
    assert c.proposed_mark == pytest.approx(0.095 * 100.0) and c.invested_after == pytest.approx(5.5)
    assert c.latest_post_money == pytest.approx(100.0) and c.staleness_anchor == date(2026, 9, 20)
    fl = _flags(c)
    assert fl["X-102"].severity is Severity.BLOCK and fl["X-102"].evidence["prior_post_money"] == pytest.approx(150.0)
    assert c.alternative_marks["structure_adjusted"] == pytest.approx(9.5 * 0.75)
    assert c.readiness is Readiness.NEEDS_REVIEW


def test_down_round_then_up_round_ends_on_the_up_round_but_the_recap_question_survives(tmp_path: Path, cfg):
    rows = [event(date=date(2026, 7, 10), detail="Series A-1", value=80.0, ownership_after=0.11, hc_investment=0.5, notes="Insider round."),
            event(date=date(2026, 9, 20), detail="Series B", value=200.0, ownership_after=0.095, notes="$40M round led by a new investor.")]
    run, _ = _run(tmp_path, cfg, [position()], rows)
    c = run.by_company()["Alpha"]
    assert [s.rule_id for s in c.steps] == ["M-012", "M-010"]
    assert c.proposed_mark == pytest.approx(19.0) and c.latest_post_money == pytest.approx(200.0)
    assert "X-102" in _flags(c) and c.readiness is Readiness.NEEDS_REVIEW


# ---------------------------------------------------------------- secondaries and cheque prices

def test_secondary_at_a_premium_realizes_cash_and_holds_the_remainder_at_the_round(tmp_path: Path, cfg):
    row = event(EventType.SECONDARY, detail="HC sold 30% of its position", value=130.0, ownership_after=0.07, proceeds=3.9,
                notes="Buyer paid a 30% premium to the Series A price.")
    run, _ = _run(tmp_path, cfg, [position()], [row])
    c = run.by_company()["Alpha"]
    assert c.proposed_mark == pytest.approx(7.0) and c.realized_cumulative == pytest.approx(3.9) and c.ownership_after == pytest.approx(0.07)
    f = _flags(c)["X-104"]
    assert f.severity is Severity.REVIEW and f.evidence["spread"] == pytest.approx(0.30)
    assert c.alternative_marks["at_secondary_price"] == pytest.approx(0.07 * 130.0)


def test_secondary_purchase_at_a_discount_marks_the_whole_stake_at_the_round(tmp_path: Path, cfg):
    row = event(EventType.SECONDARY_PURCHASE, detail="Bought shares from a departing angel", hc_investment=1.0, ownership_after=0.12,
                notes="HC bought 2% from an angel at a 50% discount to the Series A price.")
    run, _ = _run(tmp_path, cfg, [position()], [row])
    c = run.by_company()["Alpha"]
    assert c.proposed_mark == pytest.approx(12.0) and c.invested_after == pytest.approx(6.0) and c.ownership_after == pytest.approx(0.12)
    assert _flags(c)["X-104"].evidence["implied_post_money"] == pytest.approx(50.0)
    assert c.alternative_marks["at_implied_price"] == pytest.approx(0.12 * 50.0)


def test_secondary_then_priced_round_in_date_order(tmp_path: Path, cfg):
    rows = [event(EventType.SECONDARY, date=date(2026, 7, 10), detail="Sold 30%", value=100.0, ownership_after=0.07, proceeds=3.0),
            event(date=date(2026, 9, 10), detail="Series B", value=200.0, ownership_after=0.06, notes="$40M round led by a new investor.")]
    run, _ = _run(tmp_path, cfg, [position()], rows)
    c = run.by_company()["Alpha"]
    assert [s.rule_id for s in c.steps] == ["M-030", "M-010"]
    assert c.proposed_mark == pytest.approx(12.0) and c.realized_cumulative == pytest.approx(3.0) and c.ownership_after == pytest.approx(0.06)


def test_a_cheque_that_implies_a_much_lower_price_is_a_review(tmp_path: Path, cfg):
    row = event(detail="Series B", value=150.0, hc_investment=0.3, ownership_after=0.115, notes="Round priced by a new investor.")
    run, _ = _run(tmp_path, cfg, [position()], [row])
    c = run.by_company()["Alpha"]
    f = _flags(c)["X-119"]
    assert f.severity is Severity.REVIEW and f.evidence["implied_post_from_hc_cheque"] == pytest.approx(20.0)
    assert c.proposed_mark == pytest.approx(0.115 * 150.0) and c.invested_after == pytest.approx(5.3)


def test_hc_funding_less_than_pro_rata_is_not_a_finding(tmp_path: Path, cfg):
    row = event(detail="Series B", value=150.0, hc_investment=0.2, ownership_after=0.085,
                notes="$30M round led by a new investor. HC took part of its pro rata.")
    run, _ = _run(tmp_path, cfg, [position()], [row])
    c = run.by_company()["Alpha"]
    assert c.readiness is Readiness.READY and not ({"X-119", "X-123", "X-103"} & set(_flags(c)))
    assert c.proposed_mark == pytest.approx(12.75) and c.invested_after == pytest.approx(5.2)


# ---------------------------------------------------------------- exits, shutdowns and what follows them

def test_announced_then_closed_at_a_different_price_books_the_closing_price(tmp_path: Path, cfg):
    rows = [event(EventType.ACQ_ANNOUNCED, date=date(2026, 7, 15), detail="Definitive agreement, all cash", value=133.0, notes="Expected to close in Q3."),
            event(EventType.ACQ_CLOSED, date=date(2026, 9, 10), detail="Closed after price adjustment", value=120.0, proceeds=12.0,
                  notes="Closed at $120M after a working-capital adjustment. Cash received.")]
    run, _ = _run(tmp_path, cfg, [position()], rows)
    c = run.by_company()["Alpha"]
    assert c.status_after is Status.ACQUIRED and c.proposed_mark == 0.0 and c.realized_cumulative == pytest.approx(12.0)
    assert [s.rule_id for s in c.steps] == ["M-000", "M-020"]            # the announcement is recorded as skipped
    assert "skipped" in c.steps[0].rationale
    assert not any(i.kind is OpenItemKind.PENDING_ACQUISITION for i in c.open_items)
    assert c.readiness is Readiness.READY and "X-101" not in _flags(c)


def test_term_sheet_then_shutdown_leaves_nothing_pending(tmp_path: Path, cfg):
    rows = [event(EventType.TERM_SHEET, date=date(2026, 7, 20), detail="Series B term sheet at ~$120M post", value=120.0, notes="Diligence underway."),
            event(EventType.SHUTDOWN, date=date(2026, 9, 15), detail="Ceased operations", notes="Lead pulled out; board voted to wind down. No recovery expected.")]
    run, _ = _run(tmp_path, cfg, [position()], rows)
    c = run.by_company()["Alpha"]
    assert c.status_after is Status.SHUT_DOWN and c.proposed_mark == 0.0 and c.realized_cumulative == 0.0
    assert not any(i.kind is OpenItemKind.TERM_SHEET for i in c.open_items)
    assert c.readiness is Readiness.READY


def test_shutdown_with_a_residual_recovery_realizes_it(tmp_path: Path, cfg):
    run, _ = _run(tmp_path, cfg, [position()], [event(EventType.SHUTDOWN, detail="Ceased operations", proceeds=0.4,
                                                        notes="Residual cash distributed to investors.")])
    c = run.by_company()["Alpha"]
    assert c.status_after is Status.SHUT_DOWN and c.proposed_mark == 0.0 and c.realized_cumulative == pytest.approx(0.4)
    assert c.readiness is Readiness.READY


def test_shutdown_returning_more_than_the_mark_asks_if_it_was_a_sale(tmp_path: Path, cfg):
    run, _ = _run(tmp_path, cfg, [position()], [event(EventType.SHUTDOWN, detail="Ceased operations", proceeds=14.0,
                                                        notes="Assets sold; cash distributed to investors.")])
    c = run.by_company()["Alpha"]
    assert c.realized_cumulative == pytest.approx(14.0) and c.proposed_mark == 0.0
    f = _flags(c)["X-101"]
    assert f.severity is Severity.REVIEW and f.evidence["carrying_value"] == pytest.approx(10.0)
    assert c.readiness is Readiness.NEEDS_REVIEW


def test_distribution_dated_the_same_day_as_the_shutdown_is_realized_first(tmp_path: Path, cfg):
    rows = [event(EventType.SHUTDOWN, date=date(2026, 9, 10), detail="Ceased operations"),
            event(EventType.DISTRIBUTION, date=date(2026, 9, 10), detail="Residual cash", proceeds=0.2)]
    run, _ = _run(tmp_path, cfg, [position()], rows)
    c = run.by_company()["Alpha"]
    assert [s.rule_id for s in c.steps] == ["M-022", "M-021"]
    assert c.status_after is Status.SHUT_DOWN and c.realized_cumulative == pytest.approx(0.2) and c.proposed_mark == 0.0


def test_ipo_and_lockup_expiry_in_the_same_quarter(tmp_path: Path, cfg):
    pos = position(stage="Series C", latest_post_money=800.0, ownership=0.03, invested=10.0)
    rows = [event(EventType.IPO, date=date(2026, 7, 5), detail="Listed on Nasdaq", value=1200.0, ownership_after=0.028, notes="HC shares subject to a 180-day lock-up."),
            event(EventType.LOCKUP_EXPIRY, date=date(2026, 9, 25), detail="Lock-up expired early", notes="Underwriters released the lock-up early.")]
    run, _ = _run(tmp_path, cfg, [pos], rows)
    c = run.by_company()["Alpha"]
    assert [s.rule_id for s in c.steps] == ["M-040", "M-042"]
    assert c.listed and c.stage == "Public" and c.proposed_mark == pytest.approx(0.028 * 1200.0)
    assert c.provisional and c.readiness is Readiness.BLOCKED             # no quarter-end quote: the listing print stands in
    assert not any(i.kind is OpenItemKind.IPO_LOCKUP for i in c.open_items)
    assert _flags(c)["X-129"].severity is Severity.MONITOR


def test_pipe_into_a_listed_holding_still_needs_the_close(tmp_path: Path, cfg):
    pos = position(stage="Public", latest_post_money=1000.0, ownership=0.02, invested=8.0)
    row = event(detail="PIPE", value=900.0, hc_investment=1.0, ownership_after=0.021, notes="HC took part in a PIPE at a discount to market.")
    run, _ = _run(tmp_path, cfg, [pos], [row])
    c = run.by_company()["Alpha"]
    assert c.listed and c.readiness is Readiness.BLOCKED and "X-113" in _flags(c)
    assert c.invested_after == pytest.approx(9.0) and c.ownership_after == pytest.approx(0.021)


# ---------------------------------------------------------------- rows and book rows that cannot book

def test_priced_round_taking_hc_to_zero_holds_the_mark(tmp_path: Path, cfg):
    run, _ = _run(tmp_path, cfg, [position()], [event(detail="Series B", value=150.0, ownership_after=0.0, notes="$30M round led by a new investor.")])
    c = run.by_company()["Alpha"]
    assert c.proposed_mark == pytest.approx(10.0) and c.ownership_after == pytest.approx(0.10) and c.latest_post_money == pytest.approx(100.0)
    f = _flags(c)["X-101"]
    assert f.severity is Severity.BLOCK and {s.key for s in f.suggestions} == {"hold_prior", "write_to_zero"}


def test_negative_proceeds_on_a_distribution_refuse_the_row(tmp_path: Path, cfg):
    run, issues = _run(tmp_path, cfg, [position()], [event(EventType.DISTRIBUTION, detail="Partial write-off", proceeds=-2.0,
                                                             notes="Committee wrote the position down by $2M.")])
    c = run.by_company()["Alpha"]
    assert any(i.rule_id == "X-903" and i.blocking for i in issues)
    assert c.readiness is Readiness.BLOCKED and c.realized_cumulative == 0.0 and c.proposed_mark == pytest.approx(10.0)


def test_closed_exit_with_no_deal_value_refuses_the_row(tmp_path: Path, cfg):
    run, issues = _run(tmp_path, cfg, [position()], [event(EventType.ACQ_CLOSED, detail="Acquired", proceeds=12.0,
                                                             notes="Cash received; deal value undisclosed.")])
    c = run.by_company()["Alpha"]
    assert any(i.rule_id == "X-902" and i.blocking for i in issues)
    assert c.readiness is Readiness.BLOCKED and c.status_after is Status.ACTIVE and c.realized_cumulative == 0.0


def test_active_book_row_with_zero_ownership_blocks(tmp_path: Path, cfg):
    run, issues = _run(tmp_path, cfg, [position(ownership=0.0, prior_mark=0.0)], [])
    c = run.by_company()["Alpha"]
    assert any(i.rule_id == "X-903" and i.sheet == "Portfolio" for i in issues)
    assert c.readiness is Readiness.BLOCKED and _flags(c)["X-900"].evidence["sheet"] == "portfolio"


def test_book_row_with_zero_prior_mark_and_a_post_money_blocks(tmp_path: Path, cfg):
    run, issues = _run(tmp_path, cfg, [position(prior_mark=0.0)], [])
    c = run.by_company()["Alpha"]
    assert any(i.rule_id == "X-904" and i.blocking for i in issues)
    assert c.readiness is Readiness.BLOCKED and c.proposed_mark == 0.0


def test_term_sheet_withdrawn_then_a_down_round_from_another_lead(tmp_path: Path, cfg):
    rows = [event(EventType.TERM_SHEET, date=date(2026, 7, 5), detail="Series B TS at ~$120M", value=120.0),
            event(EventType.TERM_SHEET_WITHDRAWN, date=date(2026, 8, 5), detail="Lead walked"),
            event(date=date(2026, 9, 20), detail="Series B", value=90.0, ownership_after=0.085, hc_investment=0.3, notes="$20M round led by a new investor.")]
    run, _ = _run(tmp_path, cfg, [position()], rows)
    c = run.by_company()["Alpha"]
    assert [s.rule_id for s in c.steps] == ["M-070", "M-071", "M-012"]
    assert c.proposed_mark == pytest.approx(0.085 * 90.0) and c.invested_after == pytest.approx(5.3)
    fl = _flags(c)
    assert {"X-125", "X-102"} <= set(fl) and "X-109" not in fl
    assert not any(i.kind is OpenItemKind.TERM_SHEET for i in c.open_items)


# ---------------------------------------------------------------- with the note reader on (a fake)

def _run_read(tmp_path: Path, cfg, positions, events, readings):
    path = make_workbook(tmp_path, positions, events)
    snapshot, feed = read_workbook(path, cfg)
    issues = validate(snapshot, feed, cfg)
    return run_valuation(snapshot, feed, MarketData(as_of=cfg.quarter.measurement_date), OverrideLedger(), cfg,
                         validation=tuple(issues), note_readings=readings, note_reader="fake",
                         input_sha256="x", input_file=path.name, generated_at=GENERATED_AT, market_data_source="test")


def test_reader_conflict_on_a_stated_pre_money_reaches_a_person(tmp_path: Path, cfg):
    row = event(detail="Series B at $150.0M pre-money", value=150.0, ownership_after=0.09,
                notes="$30M Series B led by a new investor at $150M pre-money. HC did not participate.")
    reading = RowReading(row_index=2, source="fake", conflicts=(
        Conflict(column="post_money_or_deal_value", column_value=150.0, note_says="$150M pre-money",
                 why="the column is a post-money; the note states a pre-money"),))
    run = _run_read(tmp_path, cfg, [position()], [row], {2: reading})
    c = run.by_company()["Alpha"]
    assert c.proposed_mark == pytest.approx(13.5)                         # the column is applied; the reader never sets a number
    f = _flags(c)["X-131"]
    assert f.severity is Severity.REVIEW and f.evidence["column"] == "post_money_or_deal_value"
    assert c.readiness is Readiness.NEEDS_REVIEW


def test_reader_distress_on_an_operating_update_reaches_a_person(tmp_path: Path, cfg):
    row = event(EventType.OPERATING_UPDATE, detail="Board update",
                notes="Management reports the company is insolvent and cannot meet October payroll; the board is considering an ABC.")
    reading = RowReading(row_index=2, source="fake", aspects=(
        Aspect(kind=AspectKind.DISTRESS_OR_GOING_CONCERN, quote="the company is insolvent", note="insolvent; ABC considered",
               meaning="the equity is likely worth nothing"),))
    run = _run_read(tmp_path, cfg, [position()], [row], {2: reading})
    c = run.by_company()["Alpha"]
    fl = _flags(c)
    assert c.proposed_mark == pytest.approx(10.0) and "X-126" in fl
    # "insolvent" is on the keyword floor now, so the deterministic screen (X-105) carries the distress and the
    # reader does not raise the same kind a second time; either way a person is told the company is insolvent
    assert ("X-130" in fl and "distress_or_going_concern" in fl["X-130"].evidence["kinds"]) or \
           ("X-105" in fl and "insolvent" in fl["X-105"].evidence["terms"])
    if "X-130" in fl:
        # the mark did not move, so "hold prior" books the same number as "as proposed" and is folded into it
        assert {s.key for s in fl["X-130"].suggestions} == {"as_proposed", "at_cost"}
        assert next(s for s in fl["X-130"].suggestions if s.key == "at_cost").booked == pytest.approx(5.0)


def test_reader_distress_on_a_liquidating_distribution_reaches_a_person(tmp_path: Path, cfg):
    row = event("Liquidating distribution", detail="Final distribution", proceeds=0.3,
                notes="Final liquidating distribution after the wind-down; the company was dissolved on 12 September.")
    reading = RowReading(row_index=2, source="fake", aspects=(
        Aspect(kind=AspectKind.DISTRESS_OR_GOING_CONCERN, quote="the company was dissolved", note="company dissolved",
               meaning="the position is gone; the mark should be zero"),))
    run = _run_read(tmp_path, cfg, [position()], [row], {2: reading})
    c = run.by_company()["Alpha"]
    assert c.realized_cumulative == pytest.approx(0.3) and c.proposed_mark == pytest.approx(10.0)
    assert _flags(c)["X-130"].severity is Severity.REVIEW and c.readiness is Readiness.NEEDS_REVIEW
