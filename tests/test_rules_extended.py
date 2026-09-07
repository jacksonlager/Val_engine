"""Unit tests for the extended rule set (training/SPEC.md §3): M-013, M-014, M-022, M-024,
M-025, M-031, M-041, M-051, M-061, the Direct Listing and SAFE aliases, the X-117 / X-118
related-party flags, the new note-screen terms, precedence and open-item resolution.

Same discipline as test_rules.py: one synthetic position, one or two events, exact
arithmetic, and the audit chain asserted alongside the number.
"""
from __future__ import annotations

from datetime import date

import pytest

from conftest import event, flag_ids, make_workbook, only, position, rule_ids, with_policy
from hc_valuation.api.exec_view import DRIVERS, _driver_for
from hc_valuation.connectors.stubs import CARRIED_LISTING_SOURCE, StubMarketDataProvider
from hc_valuation.engine import precedence
from hc_valuation.engine.inputs import EventType, Status
from hc_valuation.engine.marking import _cap_from_detail
from hc_valuation.engine.models import Disposition, MarketData, MarketQuote, OpenItem, OpenItemKind, Severity
from hc_valuation.engine.open_items import RESOLVES
from hc_valuation.ingest.reader import read_workbook

MD = date(2026, 9, 30)


def _chain_ok(c, rule_id: str) -> None:
    assert c.steps[-1].rule_id == rule_id, rule_ids(c)
    assert c.proposed_mark == pytest.approx(c.steps[-1].new_value, abs=1e-9)
    assert [s.sequence for s in c.steps] == list(range(1, len(c.steps) + 1))


def _flag(c, rule_id: str):
    hits = [f for f in c.flags if f.rule_id == rule_id]
    assert hits, f"{rule_id} not raised; have {flag_ids(c)}"
    return hits[0]


def _quote(company: str = "Alpha", cap: float = 600.0) -> MarketData:
    return MarketData(quotes={company: MarketQuote(company=company, market_cap_musd=cap, as_of=MD, source="test:close",
                                                   note="test quote")}, as_of=MD)


# =================================================================== M-013 ownership adjustment

def test_m013_warrant_exercise_remarks_on_last_round_basis(build):
    run, _ = build([position(ownership=0.05)],   # prior mark 5.0 on a $100M post
                   [event(EventType.OWNERSHIP_ADJUSTMENT, detail="Warrant exercise", ownership_after=0.06, hc_investment=0.2)])
    c = only(run)
    _chain_ok(c, "M-013")
    assert c.prior_mark == pytest.approx(5.0) and c.proposed_mark == pytest.approx(6.0), "0.06 × $100M"
    assert c.ownership_after == pytest.approx(0.06) and c.invested_after == pytest.approx(5.2), "the strike is cost"
    assert c.latest_post_money == 100.0 and c.staleness_anchor == date(2025, 6, 15), "no price event: clock untouched"
    assert c.steps[-1].inputs["ownership_before"] == pytest.approx(0.05) and c.steps[-1].evidence.event_type == "Ownership Adjustment"
    f = _flag(c, "X-110")
    assert f.severity == Severity.REVIEW and f.action and f.evidence["ownership_after"] == pytest.approx(0.06)
    assert c.disposition == Disposition.REVIEW and c.status_after == Status.ACTIVE and c.fv_level == 3
    # "warrant" is a note-screen term, but on an Ownership Adjustment row it is the treatment M-013 just applied,
    # not an unhandled one: the policy exempts it, so the position is one REVIEW, not two
    assert "X-105" not in flag_ids(c)


def test_m013_without_ownership_after_keeps_ownership(build):
    run, _ = build([position()], [event(EventType.OWNERSHIP_ADJUSTMENT, detail="Cap table restatement")])
    c = only(run)
    assert c.proposed_mark == pytest.approx(10.0) and c.ownership_after == 0.10 and "X-110" in flag_ids(c)


# =================================================================== M-014 new investment

def test_m014_new_investment_into_placeholder_row(build):
    run, _ = build([position(ownership=0.0, latest_post_money=0.0, invested=0.0, prior_mark=0.0, arr=None, arr_growth=None)],
                   [event(EventType.NEW_INVESTMENT, detail="Seed", value=20.0, ownership_after=0.10, hc_investment=2.0)])
    c = only(run)
    _chain_ok(c, "M-014")
    assert c.prior_mark == 0.0 and c.proposed_mark == pytest.approx(2.0), "0.10 × $20M — entered at cost"
    assert c.invested_after == pytest.approx(2.0) and c.ownership_after == pytest.approx(0.10) and c.latest_post_money == 20.0
    assert c.staleness_anchor == date(2026, 8, 15) and c.stage == "Seed" and c.status_after == Status.ACTIVE and c.fv_level == 3
    assert c.moic_after == pytest.approx(1.0)
    f = _flag(c, "X-120")
    assert f.severity == Severity.MONITOR and f.action == ""
    assert "X-918" not in flag_ids(c), "the company was in the book"
    assert c.disposition == Disposition.MONITOR


def test_m014_company_not_in_book_is_synthesised(build):
    run, issues = build([position()],
                        [event(EventType.NEW_INVESTMENT, company="Beta", detail="Seed round in SaaS", value=20.0,
                               ownership_after=0.10, hc_investment=2.0, notes="Fund II first check.")])
    assert run.totals.positions == 2 and "Beta" in run.by_company()
    c = only(run, "Beta")
    _chain_ok(c, "M-014")
    assert rule_ids(c) == ["M-014"]
    assert c.prior_mark == 0.0 and c.proposed_mark == pytest.approx(2.0) and c.invested_before == 0.0 and c.invested_after == pytest.approx(2.0)
    assert c.fund == "Fund II" and c.sector == "SaaS" and c.stage == "Seed"
    assert c.status_before == Status.ACTIVE and c.status_after == Status.ACTIVE and c.ownership_before == 0.0
    assert c.steps[-1].inputs["position_created"] is True
    assert _flag(c, "X-120").severity == Severity.MONITOR
    f = _flag(c, "X-918")
    assert f.severity == Severity.REVIEW and f.action and f.evidence["fund"] == "Fund II"
    assert c.disposition == Disposition.REVIEW
    # the synthesised position joins the roll-up under its fund
    assert {r.fund for r in run.rollups} == {"Fund I", "Fund II"}
    assert run.totals.proposed_nav == pytest.approx(12.0)
    # Alpha is untouched
    assert only(run).proposed_mark == 10.0 and rule_ids(only(run)) == ["M-000"]
    # ingest validation still names the unknown company (package A downgrades this to X-918)
    assert any(i.rule_id in ("X-901", "X-918") and i.company == "Beta" for i in issues)


def test_m014_synthesised_defaults_when_the_row_says_nothing(build):
    run, _ = build([position()], [event(EventType.NEW_INVESTMENT, company="Gamma", detail="", value=10.0,
                                        ownership_after=0.05, hc_investment=0.5)])
    c = only(run, "Gamma")
    assert c.fund == "Unassigned" and c.sector == "Unclassified" and c.stage == "Unknown"
    assert c.proposed_mark == pytest.approx(0.5)


# =================================================================== M-022 distribution

def test_m022_distribution_on_active_company(build):
    run, _ = build([position()], [event(EventType.DISTRIBUTION, detail="Dividend", proceeds=0.5)])
    c = only(run)
    _chain_ok(c, "M-022")
    assert c.proposed_mark == pytest.approx(10.0) and c.ownership_after == 0.10, "stake and mark unchanged"
    assert c.realized_quarter == pytest.approx(0.5) and c.realized_cumulative == pytest.approx(0.5)
    assert c.steps[-1].prior_value == c.steps[-1].new_value == pytest.approx(10.0)
    f = _flag(c, "X-111")
    assert f.severity == Severity.MONITOR and f.action == "" and f.evidence["proceeds"] == 0.5
    assert c.disposition == Disposition.MONITOR and c.status_after == Status.ACTIVE


def test_m022_distribution_on_acquired_company_is_applied(build):
    run, _ = build([position(status="Acquired", prior_mark=0.0, realized=28.2)],
                   [event(EventType.DISTRIBUTION, detail="Escrow release", proceeds=1.5)])
    c = only(run)
    assert rule_ids(c) == ["M-000", "M-022"]
    assert c.proposed_mark == 0.0 and c.status_after == Status.ACQUIRED
    assert c.realized_quarter == pytest.approx(1.5) and c.realized_cumulative == pytest.approx(29.7)
    # terminal: carry-side noise dropped; the post-exit cash stays a watch item so DPI arriving after the exit is visible
    assert [f.rule_id for f in c.flags] == ["X-111"] and c.disposition == Disposition.MONITOR
    assert "after the exit" in c.steps[-1].rationale
    assert run.totals.realized_quarter == pytest.approx(1.5)


def test_m061_note_repaid_on_shut_down_company_is_applied(build):
    run, _ = build([position(status="Shut Down", prior_mark=0.0, realized=0.4)],
                   [event(EventType.NOTE_REPAID, detail="Bridge repaid from liquidation", proceeds=0.3)])
    c = only(run)
    assert rule_ids(c) == ["M-000", "M-061"]
    assert c.realized_cumulative == pytest.approx(0.7) and c.proposed_mark == 0.0 and c.disposition == Disposition.CLEAR


def test_priced_round_on_acquired_company_is_still_not_applied(build):
    run, _ = build([position(status="Acquired", prior_mark=0.0, realized=28.2)],
                   [event(detail="Series B", value=200.0, ownership_after=0.09)])
    c = only(run)
    # refused and recorded: the carry step, then the refused row, and X-900 naming it
    assert rule_ids(c) == ["M-000", "M-000"] and c.proposed_mark == 0.0
    assert [f.rule_id for f in c.flags] == ["X-900"]


def test_distribution_after_a_same_quarter_exit_is_applied(build):
    run, _ = build([position()], [
        event(EventType.ACQ_CLOSED, date=date(2026, 8, 1), detail="All-cash", value=300.0, proceeds=28.0),
        event(EventType.DISTRIBUTION, date=date(2026, 9, 15), detail="Holdback released", proceeds=2.0),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-020", "M-022"]
    assert c.realized_quarter == pytest.approx(30.0) and c.proposed_mark == 0.0 and c.disposition == Disposition.MONITOR
    assert [f.rule_id for f in c.flags] == ["X-111"], "the escrow release closed the exit's proceeds gap; the cash stays visible"


# =================================================================== M-024 stock-consideration exit

def test_m024_all_stock_exit(build):
    run, _ = build([position()], [event(EventType.ACQ_CLOSED, detail="All-stock acquisition by Acme Corp", value=300.0, proceeds=None)])
    c = only(run)
    _chain_ok(c, "M-024")
    assert rule_ids(c) == ["M-024"]
    assert c.proposed_mark == pytest.approx(30.0), "0.10 × $300M deal = value of shares received"
    assert c.status_after == Status.ACTIVE and c.stage == "Acquired (stock)" and c.fv_level == 3
    assert c.latest_post_money == 300.0 and c.staleness_anchor == date(2026, 8, 15) and c.realized_quarter == 0.0
    f = _flag(c, "X-112")
    assert f.severity == Severity.BLOCK and "acquirer" in f.action and f.evidence["value_of_shares"] == pytest.approx(30.0)
    assert c.disposition == Disposition.BLOCK
    assert [i.kind for i in c.open_items] == [OpenItemKind.ACQUIRER_SHARES] and c.open_items[0].amount_musd == pytest.approx(30.0)
    assert run.totals.exited_at_prior_mark == 0.0 and run.totals.active_after == 1


def test_m024_detected_from_notes_with_zero_proceeds(build):
    run, _ = build([position()], [event(EventType.ACQ_CLOSED, detail="Merger", value=300.0, proceeds=0.0,
                                        notes="Equity consideration only; HC received acquirer shares.")])
    assert rule_ids(only(run)) == ["M-024"]


def test_m020_wins_when_cash_was_received_even_if_stock_is_mentioned(build):
    run, _ = build([position()], [event(EventType.ACQ_CLOSED, detail="Cash and stock", value=300.0, proceeds=30.0)])
    c = only(run)
    assert rule_ids(c) == ["M-020"] and c.status_after == Status.ACQUIRED and c.proposed_mark == 0.0


# =================================================================== M-025 chapter 11

def test_m025_chapter_11_holds_and_blocks(build):
    run, _ = build([position()], [event(EventType.BANKRUPTCY_CH11, detail="Chapter 11 filing")])
    c = only(run)
    _chain_ok(c, "M-025")
    assert c.proposed_mark == pytest.approx(10.0) and c.status_after == Status.ACTIVE and c.fv_level == 3
    f = _flag(c, "X-116")
    assert f.severity == Severity.BLOCK and "recovery" in f.action
    assert c.disposition == Disposition.BLOCK
    assert run.totals.written_off == 0.0 and run.totals.active_after == 1, "not terminal"


def test_m025_is_not_terminal_so_carry_side_screens_still_run(build):
    run, _ = build([position(cash=3.0, net_burn=1.0)], [event(EventType.BANKRUPTCY_CH11, detail="Chapter 11 filing")])
    assert "X-304" in flag_ids(only(run))


# =================================================================== M-031 secondary purchase

def test_m031_purchase_at_last_round_price(build):
    run, _ = build([position()], [event(EventType.SECONDARY_PURCHASE, detail="Bought 2% from a departing angel",
                                        ownership_after=0.12, hc_investment=2.0)])
    c = only(run)
    _chain_ok(c, "M-031")
    assert c.ownership_after == pytest.approx(0.12) and c.invested_after == pytest.approx(7.0)
    assert c.proposed_mark == pytest.approx(12.0), "0.12 × $100M"
    assert c.steps[-1].inputs["implied_post_money"] == pytest.approx(100.0) and c.steps[-1].inputs["ownership_bought"] == pytest.approx(0.02)
    assert c.alternative_marks["at_implied_price"] == pytest.approx(12.0)
    f = _flag(c, "X-121")
    assert f.severity == Severity.MONITOR and f.action == "" and "X-104" not in flag_ids(c)
    assert c.disposition == Disposition.MONITOR and c.realized_quarter == 0.0


def test_m031_purchase_above_last_round_price_is_x104(build):
    run, _ = build([position()], [event(EventType.SECONDARY_PURCHASE, ownership_after=0.12, hc_investment=3.0)])
    c = only(run)
    assert c.proposed_mark == pytest.approx(12.0), "policy holds the stake at the round price"
    assert c.steps[-1].inputs["implied_post_money"] == pytest.approx(150.0)
    assert c.alternative_marks["at_implied_price"] == pytest.approx(18.0)
    f = _flag(c, "X-104")
    assert f.severity == Severity.REVIEW and f.evidence["spread"] == pytest.approx(0.5) and f.evidence["direction"] == "purchase"
    assert "X-121" not in flag_ids(c) and c.disposition == Disposition.REVIEW


def test_m031_nothing_bought_blocks(build):
    run, _ = build([position()], [event(EventType.SECONDARY_PURCHASE, ownership_after=0.10, hc_investment=1.0)])
    c = only(run)
    assert c.proposed_mark == pytest.approx(10.0) and _flag(c, "X-101").severity == Severity.BLOCK


# =================================================================== M-041 listed carry

def _public(**kw):
    return position(stage="Public", latest_post_money=500.0, ownership=0.05, arr=None, arr_growth=None, **kw)


def test_m041_listed_carry_with_quote(build):
    run, _ = build([_public()], [], market=_quote(cap=600.0))
    c = only(run)
    assert rule_ids(c) == ["M-041"]
    assert c.prior_mark == pytest.approx(25.0) and c.proposed_mark == pytest.approx(30.0), "0.05 × $600M close"
    assert c.listed and c.fv_level == 1 and c.latest_post_money == 600.0 and c.staleness_anchor == MD
    assert c.steps[-1].inputs["price_source"] == "test:close" and c.steps[-1].evidence is None
    assert not flag_ids(c) & {"X-201", "X-202", "X-404", "X-113"}
    assert c.disposition == Disposition.CLEAR and run.totals.level1_positions == 1


def test_m041_listed_carry_without_quote_blocks(build):
    run, _ = build([_public()], [])
    c = only(run)
    assert rule_ids(c) == ["M-000"] and c.proposed_mark == pytest.approx(25.0)
    assert c.listed and c.fv_level == 1
    f = _flag(c, "X-113")
    assert f.severity == Severity.BLOCK and "closing" in f.action.lower()
    assert c.disposition == Disposition.BLOCK
    assert "X-201" not in flag_ids(c), "a listed position is never 'stale' by round age"


def test_m041_not_applied_to_private_positions(build):
    run, _ = build([position()], [], market=_quote(cap=600.0))
    c = only(run)
    assert rule_ids(c) == ["M-000"] and c.proposed_mark == 10.0 and not c.listed


def test_stub_quotes_a_carried_public_position(tmp_path, cfg):
    path = make_workbook(tmp_path, [_public(company="Alpha"), position(company="Beta")], [])
    snapshot, feed = read_workbook(path, cfg)
    stub = StubMarketDataProvider(feed, snapshot=snapshot)
    assert stub.carried_listings == ["Alpha"]
    q = stub.quote("Alpha", MD)
    assert q is not None and q.market_cap_musd == pytest.approx(500.0) and q.source == CARRIED_LISTING_SOURCE
    assert "replace" in q.note.lower()
    assert stub.quote("Beta", MD) is None


# =================================================================== M-051 deal terminated

_PENDING = OpenItem(company="Alpha", kind=OpenItemKind.PENDING_ACQUISITION, opened=date(2026, 5, 1),
                    opened_quarter="Q2 2026", amount_musd=400.0, detail="Definitive agreement, all cash")


def test_m051_terminated_reverts_to_last_round_and_drops_the_item(build):
    # prior mark is the probability-weighted deal value booked last quarter: 0.10 × 400 × 0.9
    # (explained by the sidecar, as the pipeline does; unexplained it would block the position on X-904)
    run, _ = build([position(prior_mark=36.0)],
                   [event(EventType.ACQ_TERMINATED, detail="Buyer walked", notes="Terminated after regulatory review.")],
                   prior_open_items=[_PENDING], explained={"Alpha": "probability-weighted pending acquisition"})
    c = only(run)
    _chain_ok(c, "M-051")
    assert c.prior_mark == 36.0 and c.proposed_mark == pytest.approx(10.0), "back to 0.10 × $100M last round"
    assert c.steps[-1].prior_value == pytest.approx(36.0) and c.alternative_marks["hold_deal_based"] == pytest.approx(36.0)
    assert c.staleness_anchor == date(2025, 6, 15) and c.latest_post_money == 100.0
    assert c.open_items == (), "the pending_acquisition item is resolved by the termination"
    f = _flag(c, "X-114")
    assert f.severity == Severity.REVIEW and "round basis" in f.action and f.evidence["reverted_to"] == pytest.approx(10.0)
    assert c.disposition == Disposition.REVIEW and c.status_after == Status.ACTIVE


def test_pending_item_survives_when_nothing_resolves_it(build):
    run, _ = build([position(prior_mark=36.0)], [], prior_open_items=[_PENDING])
    c = only(run)
    assert [i.kind for i in c.open_items] == [OpenItemKind.PENDING_ACQUISITION] and c.open_items[0].age_quarters == 1


def test_announced_then_terminated_in_one_quarter(build):
    run, _ = build([position()], [
        event(EventType.ACQ_ANNOUNCED, date=date(2026, 8, 1), detail="Definitive agreement", value=400.0),
        event(EventType.ACQ_TERMINATED, date=date(2026, 9, 1), detail="Deal terminated"),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-000", "M-051"], "the announcement is superseded by its own termination"
    assert "superseded" in c.steps[0].rationale
    assert c.proposed_mark == pytest.approx(10.0) and c.open_items == () and "X-101" not in flag_ids(c)


# =================================================================== M-061 note repaid

def test_m061_note_funded_then_repaid_in_quarter(build):
    run, _ = build([position()], [
        event(EventType.CONVERTIBLE_NOTE, date=date(2026, 7, 10), detail="$2.0M bridge note, $120.0M valuation cap", hc_investment=0.5),
        event(EventType.NOTE_REPAID, date=date(2026, 9, 10), detail="Note repaid at par", proceeds=0.5),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-060", "M-061"]
    _chain_ok(c, "M-061")
    assert c.steps[0].new_value == pytest.approx(10.5) and c.steps[-1].prior_value == pytest.approx(10.5)
    assert c.note_at_cost == 0.0 and c.equity_mark == pytest.approx(10.0) and c.proposed_mark == pytest.approx(10.0)
    assert c.realized_quarter == pytest.approx(0.5) and c.invested_after == pytest.approx(5.5)
    assert c.steps[-1].inputs["principal"] == 0.5 and c.steps[-1].inputs["principal_not_in_note_leg"] == 0.0
    f = _flag(c, "X-115")
    assert f.severity == Severity.REVIEW and "principal" in f.action
    assert c.open_items == (), "the note item opened this quarter is closed by the repayment"
    assert c.disposition == Disposition.REVIEW


def test_m061_principal_from_hc_investment_when_given(build):
    run, _ = build([position()], [
        event(EventType.CONVERTIBLE_NOTE, date=date(2026, 7, 10), detail="$2.0M note, $120.0M cap", hc_investment=1.0),
        event(EventType.NOTE_REPAID, date=date(2026, 9, 10), detail="Repaid with interest", proceeds=1.08, hc_investment=1.0),
    ])
    c = only(run)
    assert c.note_at_cost == 0.0 and c.realized_quarter == pytest.approx(1.08) and c.proposed_mark == pytest.approx(10.0)


def test_m061_note_inside_prior_mark_is_named_not_netted(build):
    run, _ = build([position()], [event(EventType.NOTE_REPAID, detail="Bridge repaid", proceeds=0.5)])
    c = only(run)
    _chain_ok(c, "M-061")
    assert c.proposed_mark == pytest.approx(10.0) and c.realized_quarter == pytest.approx(0.5)
    assert c.steps[-1].inputs["principal_not_in_note_leg"] == pytest.approx(0.5)
    assert "overstated" in _flag(c, "X-115").message


def test_prior_quarter_note_item_resolved_by_repayment(build):
    note = OpenItem(company="Alpha", kind=OpenItemKind.CONVERTIBLE_NOTE, opened=date(2026, 5, 1), opened_quarter="Q2 2026",
                    amount_musd=0.5, detail="bridge")
    run, _ = build([position()], [event(EventType.NOTE_REPAID, proceeds=0.5)], prior_open_items=[note])
    assert only(run).open_items == ()


# =================================================================== note then round: conversion

def test_note_converts_into_a_priced_round_in_the_same_quarter(build):
    run, _ = build([position()], [
        event(EventType.CONVERTIBLE_NOTE, date=date(2026, 7, 10), detail="$3.0M bridge note, $120.0M valuation cap", hc_investment=1.0),
        event(date=date(2026, 9, 1), detail="Series B", value=200.0, ownership_after=0.09),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-060", "M-010"]
    _chain_ok(c, "M-010")
    assert c.steps[0].new_value == pytest.approx(11.0) and c.steps[1].prior_value == pytest.approx(11.0)
    assert c.proposed_mark == pytest.approx(18.0) and c.note_at_cost == 0.0 and c.invested_after == pytest.approx(6.0)
    assert c.steps[-1].inputs["note_converted"] == pytest.approx(1.0) and "converts" in c.steps[-1].rationale
    assert not [i for i in c.open_items if i.kind == OpenItemKind.CONVERTIBLE_NOTE]


# =================================================================== aliases: Direct Listing, SAFE

def test_direct_listing_is_m040(build):
    run, _ = build([position()], [event(EventType.DIRECT_LISTING, date=date(2026, 9, 10), detail="Direct listing on NYSE",
                                        value=500.0, ownership_after=0.09)], market=_quote(cap=600.0))
    c = only(run)
    _chain_ok(c, "M-040")
    assert c.proposed_mark == pytest.approx(54.0) and c.fv_level == 1 and c.listed and c.stage == "Public"
    assert _flag(c, "X-101").severity == Severity.BLOCK and c.disposition == Disposition.BLOCK
    assert [i.kind for i in c.open_items] == [OpenItemKind.IPO_LOCKUP]


def test_safe_is_m060_with_post_money_cap(build):
    run, _ = build([position()], [event(EventType.CONVERTIBLE_NOTE, detail="post-money SAFE, $12M post-money cap", hc_investment=0.25)])
    c = only(run)
    _chain_ok(c, "M-060")
    assert c.steps[-1].inputs["valuation_cap"] == 12.0 and c.steps[-1].inputs["cap_vs_last_round"] == pytest.approx(-0.88)
    assert c.note_at_cost == pytest.approx(0.25) and c.proposed_mark == pytest.approx(10.25)
    assert _flag(c, "X-107").severity == Severity.REVIEW and "X-101" not in flag_ids(c), "the cap parsed"


@pytest.mark.parametrize("detail,cap", [
    ("$3.0M bridge note, $120.0M valuation cap", 120.0),
    ("post-money SAFE, $12M post-money cap", 12.0),
    ("pre-money SAFE, $12.5M pre-money cap", 12.5),
    ("SAFE, $12M cap", 12.0),
    ("SAFE with a cap of $12M", 12.0),
    ("SAFE, valuation cap $12M", 12.0),
    ("post-money cap $1,200M", 1200.0),
    ("$3.0M uncapped bridge note", None),
    ("$3.0M note; no cap", None),
])
def test_cap_regex_forms(detail, cap):
    assert _cap_from_detail(detail) == cap


# =================================================================== X-117 / X-118 related-party pricing

@pytest.mark.parametrize("notes", ["Round led by HC.", "HC-led Series B.", "HC led the round with two insiders.",
                                   "Human Capital led; insider round."])
def test_x117_hc_led_round_is_review(build, notes):
    # $4.0M for +2.0% is $200M: the cheque reconciles to the stated post, so only the related-party question is open
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.12, hc_investment=4.0, notes=notes)])
    c = only(run)
    assert c.proposed_mark == pytest.approx(24.0), "the mark is still mechanical"
    f = _flag(c, "X-117")
    assert f.severity == Severity.REVIEW and "independent" in f.action and f.evidence["rule"] == "M-010"
    assert "X-118" not in flag_ids(c) and c.disposition == Disposition.REVIEW


def test_x117_on_flat_extension_and_recap_paths(build):
    flat, _ = build([position()], [event(detail="Series A extension (same terms)", value=100.0, ownership_after=0.11,
                                         hc_investment=1.0, notes="Led by HC.")])
    assert _flag(only(flat), "X-117").evidence["rule"] == "M-011"
    recap, _ = build([position()], [event(detail="Series B (recap)", value=50.0, ownership_after=0.2, hc_investment=1.0,
                                          notes="HC-led recap.")])
    assert _flag(only(recap), "X-117").evidence["rule"] == "M-012" and only(recap).disposition == Disposition.BLOCK


@pytest.mark.parametrize("notes", ["$7.8M insider-led round. HC did not participate.", "Insider round; existing investors only."])
def test_x118_insider_led_not_hc_is_monitor(build, notes):
    run, _ = build([position()], [event(detail="Series B", value=150.0, ownership_after=0.09, notes=notes)])   # 1.5× step-up
    c = only(run)
    f = _flag(c, "X-118")
    assert f.severity == Severity.MONITOR and f.action == "" and f.evidence["insider_led"] is True and f.evidence["step_up"] == 1.5
    assert f.family == "related_party" and "X-117" not in flag_ids(c) and c.disposition == Disposition.MONITOR


def test_x118_insider_step_up_at_or_above_the_line_is_review(build, cfg):
    """Insiders re-pricing their own position 2× with nobody outside testing it: a reviewer could book less."""
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09, notes="Insider round; existing investors only.")])
    c = only(run)
    f = _flag(c, "X-118")
    assert f.severity == Severity.REVIEW and f.evidence["step_up"] == 2.0 and f.evidence["threshold"] == 2.0
    assert c.disposition == Disposition.REVIEW and c.proposed_mark == pytest.approx(18.0), "still priced at the round"
    assert [sg.key for sg in f.suggestions] == ["as_proposed", "hold_prior"] and f.suggestions[1].booked == pytest.approx(10.0)
    strict = with_policy(cfg, **{"exceptions.indications.insider_round_review_step_up": 3.0})
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09, notes="Insider round; existing investors only.")], cfg_=strict)
    assert _flag(only(run), "X-118").severity == Severity.MONITOR


def test_arms_length_round_raises_neither(build):
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09,
                                        notes="$28.7M round led by a new investor. HC did not participate.")])
    assert not flag_ids(only(run)) & {"X-117", "X-118"}


# =================================================================== X-105 new note-screen terms

@pytest.mark.parametrize("term", ["warrant", "ratchet", "pay-to-play", "cram-down", "escrow", "holdback", "earn-out",
                                  "lock-up", "related party", "restated", "going concern", "covenant", "default"])
def test_x105_new_terms_fire_on_a_priced_round(build, term):
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09, notes=f"Note: {term} applies.")])
    c = only(run)
    f = _flag(c, "X-105")
    assert f.severity == Severity.REVIEW and term in f.evidence["terms"]
    assert c.proposed_mark == pytest.approx(18.0), "the screen never touches the number"


def test_x105_lockup_is_exempt_on_a_listing_but_not_elsewhere(build):
    ipo, _ = build([position()], [event(EventType.IPO, date=date(2026, 9, 10), detail="Listed on Nasdaq", value=500.0,
                                        ownership_after=0.09, notes="HC shares subject to a 180-day lock-up.")])
    assert "X-105" not in flag_ids(only(ipo))
    dl, _ = build([position()], [event(EventType.DIRECT_LISTING, date=date(2026, 9, 10), detail="Direct listing", value=500.0,
                                       ownership_after=0.09, notes="180-day lock-up on insiders.")])
    assert "X-105" not in flag_ids(only(dl))
    rnd, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09, notes="Shares subject to lock-up.")])
    assert _flag(only(rnd), "X-105").evidence["terms"] == ["lock-up"]


def test_x105_terms_come_from_config(cfg):
    for term in ("warrant", "pay-to-play", "cram-down", "lock-up", "related party", "going concern", "covenant", "default"):
        assert term in cfg.note_screen.terms


# =================================================================== precedence, resolution, coverage, drivers

def test_new_types_have_tiers_and_resolutions():
    for et in EventType:
        assert et.value in precedence.TIER, et
    assert precedence.TIER["Acquisition (Terminated)"] <= precedence.TIER["Acquisition (Announced)"]
    assert precedence.TIER["Bankruptcy (Chapter 11)"] == 2 and "Bankruptcy (Chapter 11)" not in precedence.TERMINAL
    assert precedence.TIER["New Investment"] == 3
    assert all(precedence.TIER[t] == 4 for t in ("Distribution", "Ownership Adjustment", "Note Repaid", "Secondary Purchase"))
    assert precedence.ALLOWED_AFTER_TERMINAL == {"Distribution", "Note Repaid"}
    assert RESOLVES["Acquisition (Terminated)"] == {OpenItemKind.PENDING_ACQUISITION}
    assert RESOLVES["Note Repaid"] == {OpenItemKind.CONVERTIBLE_NOTE}
    assert OpenItemKind.CONVERTIBLE_NOTE in RESOLVES["Priced Equity Round"]
    assert RESOLVES["Direct Listing"] == RESOLVES["IPO"]


def test_every_event_type_is_registered(cfg):
    from hc_valuation.engine.run import build_registry
    reg = build_registry(cfg)
    assert len(EventType) == 18      # the sixteen in the assignment plus Term Sheet Withdrawn and Operating Update
    for et in EventType:
        meta, _ = reg.handler_for(et.value, cfg.quarter.measurement_date)
        assert meta.rule_id != "M-999", et


def test_exec_view_drivers_cover_the_new_rules(build):
    keys = [k for k, _, _ in DRIVERS]
    for k in ("distributions", "adjustments", "new_investments", "stock_exits", "impairments"):
        assert k in keys
    assert keys[-1] == "overrides"
    cases = {
        "M-013": (event(EventType.OWNERSHIP_ADJUSTMENT, ownership_after=0.12), "adjustments"),
        "M-014": (event(EventType.NEW_INVESTMENT, value=20.0, ownership_after=0.1, hc_investment=2.0), "new_investments"),
        "M-022": (event(EventType.DISTRIBUTION, proceeds=1.0), "distributions"),
        "M-024": (event(EventType.ACQ_CLOSED, detail="all-stock", value=300.0), "stock_exits"),
        "M-025": (event(EventType.BANKRUPTCY_CH11), "impairments"),
        "M-031": (event(EventType.SECONDARY_PURCHASE, ownership_after=0.12, hc_investment=2.0), "secondary"),
        "M-051": (event(EventType.ACQ_TERMINATED), "announced"),
        "M-061": (event(EventType.NOTE_REPAID, proceeds=0.5), "notes"),
    }
    for rid, (ev, key) in cases.items():
        run, _ = build([position()], [ev])
        c = only(run)
        assert rid in rule_ids(c), (rid, rule_ids(c))
        assert _driver_for(c) == key, rid
    listed, _ = build([_public()], [], market=_quote(cap=600.0))
    assert _driver_for(only(listed)) == "ipo"
