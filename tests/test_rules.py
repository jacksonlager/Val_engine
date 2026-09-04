"""Unit tests per marking rule (M-0xx) and exception rule (X-xxx), one synthetic
position + one event each.

Every marking test asserts the audit chain as well as the number: the last step's
rule id is the rule under test and `proposed_mark == steps[-1].new_value`.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import event, flag_ids, only, position, rule_ids, with_policy
from hc_valuation.engine.inputs import EventType, Status
from hc_valuation.engine.models import Disposition, MarketData, MarketQuote, OpenItemKind, Severity

MD = date(2026, 9, 30)


def _chain_ok(c, rule_id: str) -> None:
    assert c.steps[-1].rule_id == rule_id, rule_ids(c)
    assert c.proposed_mark == pytest.approx(c.steps[-1].new_value, abs=1e-9)
    assert c.steps[-1].evidence is not None and c.steps[-1].evidence.event_type
    assert [s.sequence for s in c.steps] == list(range(1, len(c.steps) + 1))


def _flag(c, rule_id: str):
    hits = [f for f in c.flags if f.rule_id == rule_id]
    assert hits, f"{rule_id} not raised; have {flag_ids(c)}"
    return hits[0]


# =================================================================== baseline

def test_clean_position_carries_clear(build):
    run, issues = build([position()], [])
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-000"]
    assert c.proposed_mark == 10.0 and c.flags == () and c.disposition == Disposition.CLEAR
    assert c.fv_level == 3 and c.staleness_anchor == date(2025, 6, 15)
    assert c.runway_months_aged == pytest.approx(23.0)
    assert c.implied_multiple == pytest.approx(10.0)


# =================================================================== M-010 / 011 / 012

def test_m010_up_round(build):
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09, hc_investment=None)])
    c = only(run)
    _chain_ok(c, "M-010")
    assert c.proposed_mark == pytest.approx(18.0) and c.equity_mark == pytest.approx(18.0)
    assert c.ownership_after == 0.09 and c.invested_after == 5.0 and c.realized_quarter == 0
    assert c.latest_post_money == 200.0 and c.staleness_anchor == date(2026, 8, 15)
    assert c.fv_level == 3 and c.stage == "Series B" and c.status_after == Status.ACTIVE
    assert c.steps[-1].prior_value == 10.0 and c.steps[-1].inputs["post_money"] == 200.0
    assert c.flags == () and c.disposition == Disposition.CLEAR and c.open_items == ()


def test_m010_participation_adds_to_invested(build):
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.11, hc_investment=2.5)])
    c = only(run)
    assert c.invested_after == pytest.approx(7.5) and c.proposed_mark == pytest.approx(22.0)
    assert c.moic_after == pytest.approx(22.0 / 7.5, abs=1e-4)


def test_m010_non_participation_dilution_is_x103_monitor(build):
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.075)])
    c = only(run)
    f = _flag(c, "X-103")
    assert f.severity == Severity.MONITOR and f.evidence["relative_change"] == pytest.approx(-0.25)
    assert c.proposed_mark == pytest.approx(15.0) and c.disposition == Disposition.MONITOR


def test_m011_flat_extension_keeps_anchor_and_reviews(build):
    run, _ = build([position()], [event(detail="Series A extension (same terms)", value=100.0, ownership_after=0.11, hc_investment=1.0)])
    c = only(run)
    _chain_ok(c, "M-011")
    assert c.proposed_mark == pytest.approx(11.0) and c.invested_after == pytest.approx(6.0)
    assert c.staleness_anchor == date(2025, 6, 15), "a flat extension does not reset the staleness clock"
    assert c.latest_post_money == 100.0
    f = _flag(c, "X-106")
    assert f.severity == Severity.REVIEW and f.evidence["anchor"] == "2025-06-15"
    assert c.disposition == Disposition.REVIEW


def test_m011_same_post_money_without_keyword_is_still_flat(build):
    run, _ = build([position()], [event(detail="Series A-1", value=100.0, ownership_after=0.10)])
    assert only(run).steps[-1].rule_id == "M-011"


def test_m012_down_round_blocks(build):
    run, _ = build([position()], [event(detail="Series B", value=50.0, ownership_after=0.09)])
    c = only(run)
    _chain_ok(c, "M-012")
    assert c.proposed_mark == pytest.approx(4.5)
    assert c.staleness_anchor == date(2026, 8, 15)
    f = _flag(c, "X-102")
    assert f.severity == Severity.BLOCK and f.evidence["prior_post_money"] == 100.0 and f.evidence["post_money"] == 50.0
    assert "Down round" in f.message and c.disposition == Disposition.BLOCK


def test_m012_recap_keyword_blocks_even_when_post_is_up(build):
    run, _ = build([position()], [event(detail="Series B (recap)", value=120.0, ownership_after=0.05, hc_investment=0.3,
                                        notes="Insider-led round.")])
    c = only(run)
    _chain_ok(c, "M-012")
    assert c.proposed_mark == pytest.approx(6.0) and c.invested_after == pytest.approx(5.3)
    f = _flag(c, "X-102")
    assert "Recap" in f.message and f.evidence["insider_led"] is True
    assert c.disposition == Disposition.BLOCK
    assert "X-103" not in flag_ids(c), "HC funded → no dilution flag"


# =================================================================== M-020 / M-021

def test_m020_closed_exit(build):
    run, _ = build([position(realized=2.0)], [event(EventType.ACQ_CLOSED, detail="All-cash", value=300.0, proceeds=30.0)])
    c = only(run)
    _chain_ok(c, "M-020")
    assert c.proposed_mark == 0.0 and c.equity_mark == 0.0 and c.note_at_cost == 0.0
    assert c.realized_quarter == 30.0 and c.realized_cumulative == 32.0
    assert c.status_after == Status.ACQUIRED and c.fv_level is None
    assert c.flags == () and c.disposition == Disposition.CLEAR and c.open_items == ()
    assert c.steps[-1].inputs["implied_from_deal_value"] == pytest.approx(30.0)
    # A closed exit is not a write-off: the prior mark leaves the book as "exited", and cash comes back.
    assert run.totals.written_off == pytest.approx(0.0) and run.totals.exited_at_prior_mark == pytest.approx(10.0)
    assert run.totals.active_after == 0


def test_m020_proceeds_far_from_deal_value_is_flagged_in_chain_inputs(build):
    """Proceeds that do not tie to ownership × deal value: the step records both figures."""
    run, _ = build([position()], [event(EventType.ACQ_CLOSED, value=300.0, proceeds=20.0)])
    c = only(run)
    assert c.steps[-1].inputs["proceeds"] == 20.0 and c.steps[-1].inputs["implied_from_deal_value"] == pytest.approx(30.0)
    assert c.realized_quarter == 20.0


def test_m020_missing_proceeds_must_not_clear_silently(build):
    run, _ = build([position()], [event(EventType.ACQ_CLOSED, value=300.0, proceeds=None)])
    c = only(run)
    assert "X-101" in flag_ids(c) or c.disposition != Disposition.CLEAR


def test_m021_shutdown_with_residual(build):
    run, _ = build([position()], [event(EventType.SHUTDOWN, detail="Ceased operations", proceeds=0.4)])
    c = only(run)
    _chain_ok(c, "M-021")
    assert c.proposed_mark == 0.0 and c.realized_quarter == pytest.approx(0.4) and c.realized_cumulative == pytest.approx(0.4)
    assert c.status_after == Status.SHUT_DOWN and c.fv_level is None
    assert c.flags == () and c.disposition == Disposition.CLEAR
    assert "residual" in c.steps[-1].rationale


def test_m021_shutdown_without_residual(build):
    run, _ = build([position()], [event(EventType.SHUTDOWN, detail="Ceased operations")])
    c = only(run)
    _chain_ok(c, "M-021")
    assert c.realized_quarter == 0.0 and c.proposed_mark == 0.0 and c.status_after == Status.SHUT_DOWN
    assert "no recovery" in c.steps[-1].rationale
    assert run.totals.written_off == pytest.approx(10.0) and run.totals.exited_at_prior_mark == pytest.approx(0.0)


# =================================================================== M-030

def test_m030_secondary_at_last_round_price(build):
    run, _ = build([position()], [event(EventType.SECONDARY, detail="Sold 30%", ownership_after=0.07, proceeds=3.0)])
    c = only(run)
    _chain_ok(c, "M-030")
    assert c.proposed_mark == pytest.approx(7.0) and c.ownership_after == 0.07 and c.realized_quarter == 3.0
    assert c.steps[-1].inputs["implied_post_money"] == pytest.approx(100.0)
    assert c.steps[-1].inputs["remainder_basis"] == "last_round"
    assert c.alternative_marks == {"at_secondary_price": pytest.approx(7.0)}
    assert "X-104" not in flag_ids(c) and c.disposition == Disposition.CLEAR


def test_m030_spread_flag_and_remainder_basis_last_round(build):
    run, _ = build([position()], [event(EventType.SECONDARY, ownership_after=0.07, proceeds=3.6)])   # implies $120M
    c = only(run)
    assert c.proposed_mark == pytest.approx(7.0), "last_round basis: remainder stays at 0.07 × 100"
    assert c.alternative_marks["at_secondary_price"] == pytest.approx(8.4)
    f = _flag(c, "X-104")
    assert f.severity == Severity.REVIEW and f.evidence["spread"] == pytest.approx(0.2) and f.evidence["basis"] == "last_round"
    assert c.disposition == Disposition.REVIEW


def test_m030_remainder_basis_secondary_price(build, cfg):
    alt = with_policy(cfg, **{"marking.secondary.remainder_basis": "secondary_price"})
    run, _ = build([position()], [event(EventType.SECONDARY, ownership_after=0.07, proceeds=3.6)], cfg_=alt)
    c = only(run)
    _chain_ok(c, "M-030")
    assert c.proposed_mark == pytest.approx(8.4)
    assert c.alternative_marks["at_last_round"] == pytest.approx(7.0)
    assert c.steps[-1].inputs["remainder_basis"] == "secondary_price"
    assert _flag(c, "X-104").evidence["basis"] == "secondary_price"


def test_m030_spread_inside_tolerance_is_quiet(build):
    run, _ = build([position()], [event(EventType.SECONDARY, ownership_after=0.07, proceeds=3.12)])   # +4%
    assert "X-104" not in flag_ids(only(run))


def test_m030_nothing_sold_must_not_crash(build):
    run, _ = build([position()], [event(EventType.SECONDARY, ownership_after=0.10, proceeds=1.0)])
    assert only(run).steps


# =================================================================== M-040

def _ipo(**kw):
    return event(EventType.IPO, date=date(2026, 9, 10), detail="Listed on Nasdaq", value=500.0, ownership_after=0.09, **kw)


def _quote(cap: float = 600.0) -> MarketData:
    return MarketData(quotes={"Alpha": MarketQuote(company="Alpha", market_cap_musd=cap, as_of=MD, source="test:close",
                                                   note="test quote")}, as_of=MD)


def test_m040_ipo_with_measurement_date_quote(build, cfg):
    run, _ = build([position()], [_ipo()], market=_quote(600.0))
    c = only(run)
    _chain_ok(c, "M-040")
    assert c.proposed_mark == pytest.approx(54.0), "0.09 × $600M measurement-date cap"
    assert c.fv_level == 1 and c.listed and c.stage == "Public" and c.latest_post_money == 600.0
    assert c.steps[-1].inputs["price_source"] == "test:close" and c.steps[-1].inputs["measurement_date_market_cap"] == 600.0
    assert c.alternative_marks["at_ipo_print"] == pytest.approx(45.0)
    f = _flag(c, "X-101")
    assert f.severity == Severity.BLOCK and f.evidence["price_source"] == "test:close"
    assert c.disposition == Disposition.BLOCK
    assert run.totals.level1_positions == 1
    items = [i for i in c.open_items if i.kind == OpenItemKind.IPO_LOCKUP]
    assert len(items) == 1
    assert items[0].expected_resolution == date(2026, 9, 10) + timedelta(days=cfg.open_items.ipo_lockup_days)
    assert items[0].expected_resolution == date(2027, 3, 9)
    assert "X-201" not in flag_ids(c) and "X-202" not in flag_ids(c), "listed positions have a daily price"


def test_m040_ipo_without_quote_falls_back_to_print(build):
    run, _ = build([position()], [_ipo()])
    c = only(run)
    assert c.proposed_mark == pytest.approx(45.0)
    assert c.steps[-1].inputs["price_source"] == "ipo_print"
    assert c.alternative_marks["at_ipo_print"] == pytest.approx(45.0)
    assert c.disposition == Disposition.BLOCK and c.fv_level == 1


def test_m040_price_source_ipo_print_ignores_quote(build, cfg):
    alt = with_policy(cfg, **{"marking.ipo.price_source": "ipo_print"})
    run, _ = build([position()], [_ipo()], cfg_=alt, market=_quote(600.0))
    c = only(run)
    assert c.proposed_mark == pytest.approx(45.0) and c.steps[-1].inputs["price_source"] == "ipo_print"


def test_m040_lockup_discount_from_config(build, cfg):
    alt = with_policy(cfg, **{"marking.ipo.lockup_discount_pct": 0.10})
    run, _ = build([position()], [_ipo()], cfg_=alt)
    c = only(run)
    assert c.proposed_mark == pytest.approx(40.5), "0.09 × 500 × (1 − 0.10)"
    assert c.steps[-1].inputs["lockup_discount_pct"] == 0.10 and "lock-up discount" in c.steps[-1].rationale
    assert c.alternative_marks["at_ipo_print"] == pytest.approx(45.0), "the print is recorded undiscounted"


def test_m040_lockup_days_from_config(build, cfg):
    alt = with_policy(cfg, **{"open_items.ipo_lockup_days": 90})
    run, _ = build([position()], [_ipo()], cfg_=alt)
    assert only(run).open_items[0].expected_resolution == date(2026, 12, 9)


# =================================================================== M-050

_ANN = event(EventType.ACQ_ANNOUNCED, detail="Definitive agreement signed, all cash", value=400.0,
             notes="Expected to close next quarter.")


@pytest.mark.parametrize("treatment,expected", [
    ("probability_weighted", 36.0),
    ("full_deal_value", 40.0),
    ("hold_prior", 10.0),
])
def test_m050_treatments(build, cfg, treatment, expected):
    alt = with_policy(cfg, **{"marking.announced.treatment": treatment})
    run, _ = build([position()], [_ANN], cfg_=alt)
    c = only(run)
    _chain_ok(c, "M-050")
    assert c.proposed_mark == pytest.approx(expected)
    assert c.steps[-1].inputs["treatment"] == treatment and c.steps[-1].inputs["close_probability"] == 0.90
    assert c.alternative_marks == {"at_full_deal_value": pytest.approx(40.0), "hold_prior": pytest.approx(10.0),
                                   "probability_weighted": pytest.approx(36.0)}
    f = _flag(c, "X-101")
    assert f.severity == Severity.BLOCK and f.evidence["treatment"] == treatment
    assert c.disposition == Disposition.BLOCK and c.status_after == Status.ACTIVE and c.fv_level == 3
    assert [i.kind for i in c.open_items] == [OpenItemKind.PENDING_ACQUISITION]
    assert c.open_items[0].amount_musd == 400.0 and c.open_items[0].opened_quarter == cfg.quarter.label


def test_m050_close_probability_from_config(build, cfg):
    alt = with_policy(cfg, **{"marking.announced.close_probability": 0.5})
    run, _ = build([position()], [_ANN], cfg_=alt)
    assert only(run).proposed_mark == pytest.approx(20.0)


# =================================================================== M-060

def test_m060_funded_note(build):
    run, _ = build([position()], [event(EventType.CONVERTIBLE_NOTE, detail="$3.0M bridge note, $120.0M valuation cap",
                                        hc_investment=1.0, notes="Converts at next priced round.")])
    c = only(run)
    _chain_ok(c, "M-060")
    assert c.equity_mark == pytest.approx(10.0) and c.note_at_cost == pytest.approx(1.0) and c.proposed_mark == pytest.approx(11.0)
    assert c.invested_after == pytest.approx(6.0) and c.ownership_after == 0.10
    assert c.staleness_anchor == date(2025, 6, 15), "a note is not a price; the clock does not reset"
    assert c.steps[-1].inputs["valuation_cap"] == 120.0 and c.steps[-1].inputs["cap_vs_last_round"] == pytest.approx(0.2)
    f = _flag(c, "X-107")
    assert f.severity == Severity.REVIEW and f.evidence["hc_investment"] == 1.0
    assert c.disposition == Disposition.REVIEW
    assert [i.kind for i in c.open_items] == [OpenItemKind.CONVERTIBLE_NOTE] and c.open_items[0].amount_musd == 1.0
    assert "X-105" not in flag_ids(c), "'conversion' is a screened term, 'converts' is not"


def test_m060_unfunded_note(build):
    run, _ = build([position()], [event(EventType.CONVERTIBLE_NOTE, detail="$3.0M bridge note, $120.0M valuation cap")])
    c = only(run)
    _chain_ok(c, "M-060")
    assert c.proposed_mark == pytest.approx(10.0) and c.note_at_cost == 0.0 and c.invested_after == 5.0
    f = _flag(c, "X-108")
    assert f.severity == Severity.MONITOR and "X-107" not in flag_ids(c)
    assert c.disposition == Disposition.MONITOR
    assert c.open_items[0].amount_musd is None and "did not participate" in c.open_items[0].detail


def test_m060_note_without_parsable_cap_must_not_crash(build):
    run, _ = build([position()], [event(EventType.CONVERTIBLE_NOTE, detail="$3.0M uncapped bridge note", hc_investment=1.0)])
    assert only(run).note_at_cost == pytest.approx(1.0)


# =================================================================== M-070

def test_m070_term_sheet(build):
    run, _ = build([position()], [event(EventType.TERM_SHEET, detail="Series B term sheet at ~$50.0M post", value=50.0,
                                        notes="Not closed; diligence underway.")])
    c = only(run)
    _chain_ok(c, "M-070")
    assert c.proposed_mark == pytest.approx(10.0) and c.latest_post_money == 100.0 and c.staleness_anchor == date(2025, 6, 15)
    assert c.alternative_marks == {"term_sheet_indicated": pytest.approx(5.0)}
    f = _flag(c, "X-109")
    assert f.severity == Severity.MONITOR and f.evidence["indicated_mark"] == pytest.approx(5.0)
    assert c.disposition == Disposition.MONITOR
    assert [i.kind for i in c.open_items] == [OpenItemKind.TERM_SHEET] and c.open_items[0].amount_musd == 50.0


def test_m070_term_sheet_without_value(build):
    run, _ = build([position()], [event(EventType.TERM_SHEET, detail="Term sheet signed")])
    c = only(run)
    assert c.proposed_mark == 10.0 and c.alternative_marks == {} and c.disposition == Disposition.MONITOR


# =================================================================== M-999

def test_m999_unknown_event_blocks_and_names_itself(build):
    run, issues = build([position()], [event("SPAC Merger", detail="De-SPAC with Acme Corp", value=400.0, ownership_after=0.08)])
    c = only(run)
    _chain_ok(c, "M-999")
    assert c.proposed_mark == pytest.approx(10.0) and c.ownership_after == 0.10, "an unknown event never moves the mark"
    assert c.steps[-1].inputs["event_type"] == "SPAC Merger"
    f = _flag(c, "M-999")
    assert f.severity == Severity.BLOCK and f.evidence["signature"] == "spac merger" and "SPAC Merger" in f.message
    assert c.disposition == Disposition.BLOCK
    assert [i.rule_id for i in issues] == ["X-909"] and run.blocked


def test_m999_signature_carries_tags(build):
    run, _ = build([position()], [event("SPAC Merger", detail="recap extension", hc_investment=1.0, proceeds=2.0)])
    assert _flag(only(run), "M-999").evidence["signature"] == "spac merger|extension|hc_funded|proceeds|recap"


# =================================================================== X-2xx staleness

@pytest.mark.parametrize("latest_round,expected", [
    (date(2024, 9, 15), set()),          # 24 months: not > 24
    (date(2024, 8, 15), {"X-201"}),      # 25 months
    (date(2022, 9, 15), {"X-201"}),      # 48 months: still MONITOR
    (date(2022, 8, 15), {"X-202"}),      # 49 months: REVIEW
])
def test_staleness_thresholds(build, latest_round, expected):
    run, _ = build([position(latest_round=latest_round)], [])
    c = only(run)
    assert flag_ids(c) & {"X-201", "X-202"} == expected
    if expected:
        f = _flag(c, next(iter(expected)))
        assert f.family == "staleness" and f.evidence["anchor"] == latest_round.isoformat()


def test_staleness_thresholds_come_from_config(build, cfg):
    alt = with_policy(cfg, **{"exceptions.staleness.monitor_months": 12})
    run, _ = build([position()], [], cfg_=alt)   # 15 months old
    assert "X-201" in flag_ids(only(run))


# =================================================================== X-3xx growth / runway

@pytest.mark.parametrize("growth,expected", [(0.0, set()), (-0.10, {"X-301"}), (-0.15, {"X-301"}), (-0.20, {"X-302"})])
def test_arr_growth_thresholds(build, growth, expected):
    run, _ = build([position(arr_growth=growth)], [])
    c = only(run)
    assert flag_ids(c) & {"X-301", "X-302"} == expected
    for rid in expected:
        assert _flag(c, rid).family == "growth"


@pytest.mark.parametrize("cash,burn,expected,aged", [
    (13.0, 1.0, set(), 12.0),          # 13 − 1 = 12: not < 12
    (12.0, 1.0, {"X-303"}, 11.0),
    (7.0, 1.0, {"X-303"}, 6.0),        # 7 − 1 = 6: not < 6
    (6.5, 1.0, {"X-304"}, 5.5),        # raw 6.5 would pass; the reporting lag makes it REVIEW
    (0.0, 0.0, set(), None),           # breakeven: no runway concept
])
def test_runway_thresholds_with_reporting_lag(build, cfg, cash, burn, expected, aged):
    assert cfg.metrics.reporting_lag_months == 1
    run, _ = build([position(cash=cash, net_burn=burn)], [])
    c = only(run)
    assert flag_ids(c) & {"X-303", "X-304"} == expected
    assert c.runway_months_aged == (pytest.approx(aged) if aged is not None else None)
    for rid in expected:
        f = _flag(c, rid)
        assert f.family == "liquidity" and f.evidence["runway_months_aged"] == pytest.approx(aged)


def test_runway_reporting_lag_is_config_driven(build, cfg):
    alt = with_policy(cfg, **{"metrics.reporting_lag_months": 0})
    run, _ = build([position(cash=6.5, net_burn=1.0)], [], cfg_=alt)
    c = only(run)
    assert "X-303" in flag_ids(c) and "X-304" not in flag_ids(c) and c.runway_months_aged == pytest.approx(6.5)


# =================================================================== X-4xx mark vs performance

def test_x401_high_multiple(build):
    run, _ = build([position(arr=2.0)], [])          # 50x
    c = only(run)
    f = _flag(c, "X-401")
    assert f.severity == Severity.MONITOR and f.evidence["implied_multiple"] == pytest.approx(50.0) and f.evidence["threshold"] == 30
    assert c.implied_multiple == pytest.approx(50.0) and c.disposition == Disposition.MONITOR


def test_x402_low_multiple(build):
    run, _ = build([position(arr=50.0)], [])         # 2x
    f = _flag(only(run), "X-402")
    assert f.evidence["implied_multiple"] == pytest.approx(2.0) and f.evidence["threshold"] == 3


def test_x403_arr_below_floor(build):
    run, _ = build([position(arr=0.3)], [])
    c = only(run)
    assert _flag(c, "X-403").family == "valuation"
    assert not flag_ids(c) & {"X-401", "X-402"} and c.implied_multiple is None


def test_x40x_no_arr_no_multiple_screen(build):
    run, _ = build([position(arr=None, arr_growth=None)], [])
    c = only(run)
    assert not flag_ids(c) & {"X-401", "X-402", "X-403"} and c.implied_multiple is None


def test_x401_relative_to_comps_mode(build, cfg):
    from hc_valuation.engine.models import SectorComp
    alt = with_policy(cfg, **{"exceptions.multiple.mode": "relative_to_comps"})
    comps = MarketData(comps={"SaaS": SectorComp(sector="SaaS", ev_to_arr=4.0, as_of=MD, source="test")}, as_of=MD)
    run, _ = build([position()], [], cfg_=alt, market=comps)   # 10x vs 2 × 4 = 8x ceiling
    f = _flag(only(run), "X-401")
    assert f.evidence["threshold"] == pytest.approx(8.0) and "sector comp 4.0" in f.message


def test_x404_moic_outlier_on_stale_round(build):
    run, _ = build([position(invested=1.0, latest_round=date(2024, 6, 15))], [])   # 10x MOIC, 27 months
    c = only(run)
    f = _flag(c, "X-404")
    assert f.evidence["moic"] == pytest.approx(10.0) and f.evidence["months"] == 27 and f.severity == Severity.MONITOR
    assert "X-201" in flag_ids(c) and c.disposition == Disposition.MONITOR


def test_x404_needs_both_moic_and_staleness(build):
    fresh, _ = build([position(invested=1.0)], [])                                   # 10x but 15 months
    stale, _ = build([position(latest_round=date(2024, 6, 15))], [])                 # 27 months but 2x
    assert "X-404" not in flag_ids(only(fresh)) and "X-404" not in flag_ids(only(stale))


# =================================================================== X-105 note screen

def test_x105_fires_on_escrow_in_notes(build):
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09,
                                        notes="Part of the consideration is held in escrow.")])
    c = only(run)
    f = _flag(c, "X-105")
    assert f.severity == Severity.REVIEW and f.evidence["terms"] == ["escrow"] and f.evidence["row_index"] == 2
    assert c.proposed_mark == pytest.approx(18.0), "the screen never touches the number"
    assert c.disposition == Disposition.REVIEW


def test_x105_does_not_fire_on_plain_text(build):
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09,
                                        notes="Led by a new investor. HC did not participate.")])
    assert "X-105" not in flag_ids(only(run))


def test_x105_disabled_by_config(build, cfg):
    alt = with_policy(cfg, **{"note_screen.enabled": False})
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09, notes="escrow")], cfg_=alt)
    assert "X-105" not in flag_ids(only(run))


# =================================================================== escalation

def test_two_review_families_escalate_to_block(build):
    run, _ = build([position(arr_growth=-0.20, cash=5.0, net_burn=1.0)], [])   # growth + liquidity
    c = only(run)
    assert {f.family for f in c.flags if f.severity == Severity.REVIEW} == {"growth", "liquidity"}
    assert not any(f.severity == Severity.BLOCK for f in c.flags)
    assert c.disposition == Disposition.BLOCK


def test_two_reviews_in_one_family_stay_review(build):
    """Two REVIEW flags from the same family are one concern, not two."""
    run, _ = build([position()], [event(detail="Series A extension (same terms)", value=100.0, ownership_after=0.11,
                                        notes="escrow arrangement")])   # X-106 + X-105, both 'treatment'
    c = only(run)
    assert {f.rule_id for f in c.flags if f.severity == Severity.REVIEW} == {"X-105", "X-106"}
    assert c.disposition == Disposition.REVIEW


def test_one_review_family_is_review(build):
    run, _ = build([position(arr_growth=-0.20)], [])
    assert only(run).disposition == Disposition.REVIEW


def test_monitor_only_is_monitor(build):
    run, _ = build([position(arr_growth=-0.10)], [])
    c = only(run)
    assert all(f.severity == Severity.MONITOR for f in c.flags) and c.disposition == Disposition.MONITOR


def test_terminal_clears_and_empties_flags(build):
    run, _ = build([position(arr_growth=-0.20, cash=5.0, net_burn=1.0)],
                   [event(EventType.SHUTDOWN, detail="Ceased operations", notes="escrow holdback")])
    c = only(run)
    assert c.flags == () and c.disposition == Disposition.CLEAR and c.status_after == Status.SHUT_DOWN


def test_escalation_threshold_from_config(build, cfg):
    alt = with_policy(cfg, **{"exceptions.escalation.review_rules_to_block": 3})
    run, _ = build([position(arr_growth=-0.20, cash=5.0, net_burn=1.0)], [], cfg_=alt)
    assert only(run).disposition == Disposition.REVIEW


def test_flags_never_change_a_mark(build):
    run, _ = build([position(arr_growth=-0.20, cash=5.0, net_burn=1.0, arr=2.0, latest_round=date(2022, 8, 15))], [])
    c = only(run)
    assert len(c.flags) >= 4 and c.proposed_mark == pytest.approx(10.0) and rule_ids(c) == ["M-000"]
