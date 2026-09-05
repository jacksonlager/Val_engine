"""Edge cases the Q3 2026 feed does not contain.

The engine must be deterministic and honest on these before any later quarter relies on
it: multi-event companies, precedence, terminal companies, declarative rules from the
policy file, overrides, open-item carry and the calibration alternative.
"""
from __future__ import annotations

from datetime import date

import pytest

from conftest import event, flag_ids, only, position, rule_ids, with_policy
from hc_valuation.engine import run as engine_run
from hc_valuation.engine.dsl import DSLError
from hc_valuation.engine.inputs import EventType, Status
from hc_valuation.engine.models import (
    Disposition, MarketData, OpenItem, OpenItemKind, OverrideLedger, OverrideRecord, Severity,
)

MD = date(2026, 9, 30)


# =================================================================== multi-event chains

def test_round_then_secondary_chronological_chain(build):
    run, _ = build([position()], [
        event(EventType.SECONDARY, date=date(2026, 8, 20), detail="Sold a third", ownership_after=0.06, proceeds=6.0),
        event(date=date(2026, 8, 1), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=1.0),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-010", "M-030"], "applied in date order regardless of sheet order"
    assert [s.evidence.date for s in c.steps] == [date(2026, 8, 1), date(2026, 8, 20)]
    assert c.steps[0].prior_value == 10.0 and c.steps[0].new_value == pytest.approx(18.0)
    assert c.steps[1].prior_value == pytest.approx(18.0) and c.steps[1].new_value == pytest.approx(12.0)
    assert c.steps[1].inputs["implied_post_money"] == pytest.approx(200.0), "secondary priced off the new round"
    assert c.proposed_mark == pytest.approx(12.0) and c.ownership_after == 0.06
    assert c.invested_after == pytest.approx(6.0) and c.realized_quarter == pytest.approx(6.0)
    assert c.staleness_anchor == date(2026, 8, 1)
    assert "X-104" not in flag_ids(c)


def test_round_then_closed_exit_same_quarter(build):
    run, _ = build([position()], [
        event(date=date(2026, 7, 10), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=2.0),
        event(EventType.ACQ_CLOSED, date=date(2026, 9, 1), detail="All-cash", value=300.0, proceeds=27.0),
        event(EventType.TERM_SHEET, date=date(2026, 9, 15), detail="Stray row after the exit", value=999.0),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-010", "M-020", "M-000"]
    assert c.invested_after == pytest.approx(7.0), "the July round's money is counted before September returns it"
    assert c.proposed_mark == 0.0 and c.status_after == Status.ACQUIRED
    assert c.realized_quarter == pytest.approx(27.0) and c.moic_after == pytest.approx(27.0 / 7.0, abs=1e-4)
    suppressed = c.steps[-1]
    assert suppressed.inputs["suppressed_event"] == EventType.TERM_SHEET.value
    assert suppressed.prior_value == 0.0 and suppressed.new_value == 0.0 and "not applied" in suppressed.rationale
    assert suppressed.evidence is not None and suppressed.evidence.date == date(2026, 9, 15)
    assert c.open_items == () and c.alternative_marks == {}, "nothing from the suppressed term sheet leaks through"
    assert c.disposition == Disposition.CLEAR and c.flags == ()


def test_same_day_round_and_exit_applies_money_flow_first(build):
    run, _ = build([position()], [
        event(EventType.ACQ_CLOSED, date=date(2026, 9, 1), value=300.0, proceeds=27.0),
        event(date=date(2026, 9, 1), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=2.0),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-010", "M-020"] and c.invested_after == pytest.approx(7.0)


def test_announced_superseded_by_closed(build):
    run, _ = build([position()], [
        event(EventType.ACQ_ANNOUNCED, date=date(2026, 8, 1), detail="Definitive agreement", value=300.0),
        event(EventType.ACQ_CLOSED, date=date(2026, 9, 1), detail="Closed", value=300.0, proceeds=30.0),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-000", "M-020"]
    skipped = c.steps[0]
    assert skipped.inputs["skipped_event"] == EventType.ACQ_ANNOUNCED.value and "superseded" in skipped.rationale
    assert skipped.prior_value == 10.0 and skipped.new_value == 10.0
    assert c.proposed_mark == 0.0 and c.realized_quarter == 30.0
    assert c.open_items == () and "probability_weighted" not in c.alternative_marks
    assert c.disposition == Disposition.CLEAR


def test_announced_after_closed_is_still_superseded(build):
    """Order in the sheet does not matter: a closed deal wins even if the announcement row is dated later."""
    run, _ = build([position()], [
        event(EventType.ACQ_CLOSED, date=date(2026, 8, 1), value=300.0, proceeds=30.0),
        event(EventType.ACQ_ANNOUNCED, date=date(2026, 9, 1), value=300.0),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-020", "M-000"] and c.proposed_mark == 0.0
    assert c.steps[-1].inputs.get("suppressed_event") == EventType.ACQ_ANNOUNCED.value


def test_shutdown_then_round_is_suppressed(build):
    run, _ = build([position()], [
        event(EventType.SHUTDOWN, date=date(2026, 8, 1), detail="Ceased operations"),
        event(date=date(2026, 9, 1), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=5.0),
    ])
    c = only(run)
    assert rule_ids(c) == ["M-021", "M-000"]
    assert c.proposed_mark == 0.0 and c.invested_after == 5.0, "money on a suppressed event is not counted"


# =================================================================== terminal companies

def test_event_on_already_terminal_company_is_not_applied(build):
    run, issues = build([position(status="Acquired", prior_mark=0.0, ownership=0.0, invested=5.0, realized=20.0,
                                  arr=None, arr_growth=None, net_burn=None, cash=None)],
                        [event(detail="Series B", value=200.0, ownership_after=0.09, hc_investment=1.0)])
    c = only(run)
    assert [i.rule_id for i in issues] == ["X-907"] and issues[0].company == "Alpha" and issues[0].blocking
    assert rule_ids(c) == ["M-000"] and "Already Acquired" in c.steps[0].rationale
    assert c.proposed_mark == 0.0 and c.invested_after == 5.0 and c.ownership_after == 0.0
    assert c.status_after == Status.ACQUIRED and c.fv_level is None and c.flags == ()
    assert c.realized_cumulative == 20.0 and c.realized_quarter == 0.0
    assert run.blocked, "the validation issue blocks the run even though the position itself is CLEAR"


def test_terminal_companies_do_not_count_as_written_off(build):
    run, _ = build([position(status="Shut Down", prior_mark=0.0, ownership=0.0, arr=None, net_burn=None, cash=None)], [])
    assert run.totals.written_off == 0.0 and run.totals.active_after == 0


# =================================================================== declarative rules (E-08 / E-09)

SPAC_RULE = dict(rule_id="M-110", version="1", event_type="SPAC Merger",
                 formula="ownership_after * deal_value * close_probability", severity="REVIEW",
                 rationale="De-SPAC treated like an announced acquisition: probability-weighted deal value.",
                 approver="J. Doe", effective_from=date(2026, 7, 1), source_proposal="prop-0001")


def test_custom_rule_is_registered_and_applied(build, cfg):
    alt = with_policy(cfg, custom_rules=[SPAC_RULE])
    reg = engine_run.build_registry(alt)
    meta, _ = reg.handler_for("SPAC Merger", MD)
    assert meta.rule_id == "M-110" and meta.source == "declarative" and meta.severity == Severity.REVIEW
    assert "SPAC Merger" in reg.covered_event_types(MD)

    run, _ = build([position()], [event("SPAC Merger", detail="De-SPAC", value=400.0, ownership_after=0.08)], cfg_=alt)
    c = only(run)
    assert rule_ids(c) == ["M-110"]
    step = c.steps[-1]
    assert c.proposed_mark == pytest.approx(0.08 * 400.0 * 0.90) == pytest.approx(step.new_value)
    assert step.inputs["approver"] == "J. Doe" and step.inputs["formula"] == SPAC_RULE["formula"]
    assert step.inputs["source_proposal"] == "prop-0001" and step.inputs["effective_from"] == "2026-07-01"
    assert step.inputs["close_probability"] == 0.90 and step.inputs["deal_value"] == 400.0
    assert "J. Doe" in step.rationale
    assert "M-999" not in flag_ids(c) and "M-999" not in rule_ids(c)
    assert flag_ids(c) == {"M-110"} and c.disposition == Disposition.REVIEW
    assert c.ownership_after == 0.08


def test_custom_rule_not_yet_effective_falls_back_to_m999(build, cfg):
    alt = with_policy(cfg, custom_rules=[{**SPAC_RULE, "effective_from": date(2026, 10, 1)}])
    run, _ = build([position()], [event("SPAC Merger", value=400.0, ownership_after=0.08)], cfg_=alt)
    c = only(run)
    assert rule_ids(c) == ["M-999"] and c.disposition == Disposition.BLOCK and c.proposed_mark == 10.0


def test_custom_rule_wins_over_builtin_for_same_event_type(build, cfg):
    spec = {**SPAC_RULE, "rule_id": "M-071", "event_type": EventType.TERM_SHEET.value, "formula": "prior_mark"}
    alt = with_policy(cfg, custom_rules=[spec])
    meta, _ = engine_run.build_registry(alt).handler_for(EventType.TERM_SHEET.value, MD)
    assert meta.rule_id == "M-071" and meta.source == "declarative"


def test_custom_rule_terminal_flag(build, cfg):
    spec = {**SPAC_RULE, "rule_id": "M-111", "formula": "0", "terminal": True}
    alt = with_policy(cfg, custom_rules=[spec])
    run, _ = build([position()], [event("SPAC Merger", value=400.0, proceeds=12.0)], cfg_=alt)
    c = only(run)
    assert c.proposed_mark == 0.0 and c.realized_quarter == 12.0 and c.fv_level is None
    assert c.disposition == Disposition.CLEAR and c.flags == ()


@pytest.mark.parametrize("formula,fragment", [
    ("ownership_after * market_cap", "market_cap"),                 # not on the whitelist
    ("__import__('os').system('true')", "allowed"),                 # no calls but min/max
    ("ownership_after ** 2", "not allowed"),                        # operator outside the list
    ("deal_value if deal_value else 0", "not allowed"),
    ("", "empty"),
    ("'text'", "not numeric"),
])
def test_bad_dsl_formula_rejected_at_registry_build(cfg, formula, fragment):
    alt = with_policy(cfg, custom_rules=[{**SPAC_RULE, "formula": formula}])
    with pytest.raises(DSLError, match=fragment):
        engine_run.build_registry(alt)


def test_dsl_parse_never_executes(cfg):
    """Names are looked up in a value table; there is no eval path for a formula to reach."""
    from hc_valuation.engine import dsl
    tree = dsl.parse("max(prior_mark, ownership_after * deal_value) - hc_investment / 2",
                     cfg.adjudication.allowed_fields, cfg.adjudication.allowed_operators)
    assert dsl.fields_used(tree) >= {"prior_mark", "ownership_after", "deal_value", "hc_investment"}
    assert dsl.evaluate(tree, {"prior_mark": 10.0, "ownership_after": 0.1, "deal_value": 400.0, "hc_investment": 2.0}) == pytest.approx(39.0)
    with pytest.raises(DSLError, match="division by zero"):
        dsl.evaluate(dsl.parse("prior_mark / proceeds", cfg.adjudication.allowed_fields, cfg.adjudication.allowed_operators),
                     {"prior_mark": 1.0, "proceeds": 0.0})


def test_custom_rule_with_min_max_must_not_crash(build, cfg):
    alt = with_policy(cfg, custom_rules=[{**SPAC_RULE, "formula": "max(prior_mark, ownership_after * deal_value * close_probability)"}])
    run, _ = build([position()], [event("SPAC Merger", value=400.0, ownership_after=0.08)], cfg_=alt)
    assert only(run).proposed_mark == pytest.approx(28.8)


def test_custom_rule_event_type_does_not_raise_x909(build, cfg):
    alt = with_policy(cfg, custom_rules=[SPAC_RULE])
    run, issues = build([position()], [event("SPAC Merger", value=400.0, ownership_after=0.08)], cfg_=alt)
    assert only(run).disposition == Disposition.REVIEW
    assert "X-909" not in {i.rule_id for i in issues}
    assert not run.blocked


# =================================================================== E-01 overrides

def _ledger(proposed: float, booked: float = 8.0) -> OverrideLedger:
    return OverrideLedger(records=(OverrideRecord(
        company="Alpha", quarter="Q3 2026", proposed=proposed, booked=booked, reason="Committee haircut for illiquidity",
        approver="Valuation Committee", created_at=date(2026, 9, 28), rule_ids_addressed=("X-201",)),))


def test_e01_override_changes_booked_not_proposed(build):
    run, _ = build([position()], [], overrides=_ledger(proposed=10.0))
    c = only(run)
    assert c.proposed_mark == pytest.approx(10.0) and c.booked_mark == pytest.approx(8.0)
    assert c.override is not None and c.override.approver == "Valuation Committee"
    assert rule_ids(c) == ["M-000", "E-01"]
    step = c.steps[-1]
    assert step.inputs["booked"] == 8.0 and step.inputs["proposed"] == 10.0 and step.inputs["rule_ids_addressed"] == ["X-201"]
    assert step.prior_value == step.new_value == pytest.approx(10.0), "the chain records the decision; it does not rewrite the proposal"
    # An overridden position is never below MONITOR: the committee decision stays in the queue for the record.
    assert "E-01" not in flag_ids(c) and c.disposition == Disposition.MONITOR
    assert run.totals.proposed_nav == pytest.approx(10.0) and run.totals.booked_nav == pytest.approx(8.0)
    assert c.moic_after == pytest.approx(8.0 / 5.0)


def test_e01_override_within_tolerance_is_quiet(build):
    run, _ = build([position()], [], overrides=_ledger(proposed=10.04))
    assert "E-01" not in flag_ids(only(run))


def test_e01_drifted_override_raises_review(build):
    run, _ = build([position()], [], overrides=_ledger(proposed=9.0))
    c = only(run)
    assert c.booked_mark == pytest.approx(8.0) and c.proposed_mark == pytest.approx(10.0), "the human decision stands"
    f = [f for f in c.flags if f.rule_id == "E-01"][0]
    assert f.severity == Severity.REVIEW and f.evidence == {"override_proposed": 9.0, "current_proposed": 10.0, "booked": 8.0}
    assert c.disposition == Disposition.REVIEW


def test_e01_override_for_another_quarter_is_ignored(build):
    ledger = OverrideLedger(records=(OverrideRecord(company="Alpha", quarter="Q2 2026", proposed=10.0, booked=8.0,
                                                    reason="old", approver="X", created_at=date(2026, 6, 28)),))
    run, _ = build([position()], [], overrides=ledger)
    c = only(run)
    assert c.booked_mark == 10.0 and c.override is None and rule_ids(c) == ["M-000"]


def test_e01_override_on_event_company_follows_the_chain(build):
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09)],
                   overrides=_ledger(proposed=18.0, booked=15.0))
    c = only(run)
    assert rule_ids(c) == ["M-010", "E-01"] and c.proposed_mark == pytest.approx(18.0) and c.booked_mark == pytest.approx(15.0)


# =================================================================== E-07 open items

def _prior(company: str, kind: OpenItemKind, age: int = 0, **kw) -> OpenItem:
    return OpenItem(company=company, kind=kind, opened=date(2026, 5, 1), opened_quarter="Q2 2026",
                    detail=f"{kind.value} from Q2", age_quarters=age, **kw)


def test_e07_pending_acquisition_ages_and_escalates(build, cfg):
    assert cfg.open_items.announced_deal_stale_quarters == 2
    run, _ = build([position()], [], prior_open_items=[_prior("Alpha", OpenItemKind.PENDING_ACQUISITION, age=1, amount_musd=300.0)])
    c = only(run)
    assert len(c.open_items) == 1
    item = c.open_items[0]
    assert item.age_quarters == 2 and item.escalated and item.opened_quarter == "Q2 2026" and item.amount_musd == 300.0
    f = [f for f in c.flags if f.rule_id == "E-07"][0]
    assert f.severity == Severity.REVIEW and f.evidence["age_quarters"] == 2 and f.evidence["kind"] == "pending_acquisition"
    assert c.disposition == Disposition.REVIEW
    assert run.open_items == c.open_items
    assert c.proposed_mark == 10.0, "an aged open item changes the queue, never the number"


def test_e07_fresh_item_ages_without_escalating(build):
    run, _ = build([position()], [], prior_open_items=[_prior("Alpha", OpenItemKind.PENDING_ACQUISITION, age=0)])
    c = only(run)
    assert c.open_items[0].age_quarters == 1 and not c.open_items[0].escalated and "E-07" not in flag_ids(c)


def test_e07_note_is_dropped_when_a_priced_round_resolves_it(build):
    run, _ = build([position(), position(company="Beta")],
                   [event(company="Beta", detail="Series B", value=200.0, ownership_after=0.09)],
                   prior_open_items=[_prior("Beta", OpenItemKind.CONVERTIBLE_NOTE, amount_musd=1.0),
                                     _prior("Alpha", OpenItemKind.CONVERTIBLE_NOTE, amount_musd=1.0)])
    beta, alpha = only(run, "Beta"), only(run)
    assert beta.open_items == (), "the note converted in the round"
    assert len(alpha.open_items) == 1 and alpha.open_items[0].kind == OpenItemKind.CONVERTIBLE_NOTE, "Alpha had no round; its note carries"
    assert alpha.open_items[0].age_quarters == 1
    assert {i.company for i in run.open_items} == {"Alpha"}


def test_e07_term_sheet_escalates_after_one_quarter(build, cfg):
    assert cfg.open_items.term_sheet_stale_quarters == 1
    run, _ = build([position()], [], prior_open_items=[_prior("Alpha", OpenItemKind.TERM_SHEET, amount_musd=50.0)])
    c = only(run)
    assert c.open_items[0].escalated and "E-07" in flag_ids(c)


def test_e07_items_resolve_with_a_terminal_event(build):
    run, _ = build([position()], [event(EventType.SHUTDOWN, detail="Ceased")],
                   prior_open_items=[_prior("Alpha", OpenItemKind.PENDING_ACQUISITION, age=1)])
    assert only(run).open_items == ()


def test_e07_expired_lockup_drops_quietly(build):
    prior = _prior("Alpha", OpenItemKind.IPO_LOCKUP, expected_resolution=date(2026, 8, 1))
    run, _ = build([position()], [], prior_open_items=[prior])
    assert only(run).open_items == ()
    live = _prior("Alpha", OpenItemKind.IPO_LOCKUP, expected_resolution=date(2027, 3, 19))
    run, _ = build([position()], [], prior_open_items=[live])
    c = only(run)
    assert len(c.open_items) == 1 and not c.open_items[0].escalated and c.open_items[0].age_quarters == 1


def test_e07_items_for_other_companies_are_ignored(build):
    run, _ = build([position()], [], prior_open_items=[_prior("Nobody", OpenItemKind.PENDING_ACQUISITION, age=5)])
    assert only(run).open_items == () and run.open_items == ()


# =================================================================== M-080 calibration

def _hist(now: float, then: float = 10.0, source: str = "live:edgar+yahoo@2026-09", then_key: str = "2024-06") -> MarketData:
    from hc_valuation.engine.models import SectorComp
    return MarketData(comp_history={"SaaS": {then_key: then, "2026-09": now}},
                      comps={"SaaS": SectorComp(sector="SaaS", ev_to_arr=now, as_of=MD, source=source)}, as_of=MD)


def test_m080_is_on_but_only_an_observed_comps_history_calibrates(build, cfg):
    """Policy 0.2 ships calibration on, gated to a live history: the fixture's trend never moves a mark."""
    assert cfg.marking.calibration.enabled is True and cfg.marking.calibration.require_live_history is True
    fixture = _hist(12.0, source="fixture:pitchbook@2026-09")
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], market=fixture)
    c = only(run)
    assert "calibrated_to_comps" not in c.alternative_marks and "M-080" not in rule_ids(c)
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], market=_hist(12.0))          # live: calibrates
    assert only(run).alternative_marks["calibrated_to_comps"] == pytest.approx(12.0)
    off = with_policy(cfg, **{"marking.calibration.enabled": False})
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], cfg_=off, market=_hist(12.0))
    assert "M-080" not in rule_ids(only(run))
    loose = with_policy(cfg, **{"marking.calibration.require_live_history": False})
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], cfg_=loose, market=fixture)   # fixture allowed
    assert only(run).alternative_marks["calibrated_to_comps"] == pytest.approx(12.0)


def test_m080_reads_the_nearest_month_within_tolerance_and_records_it(build, cfg):
    near = _hist(12.0, then_key="2024-08")                       # round month 2024-06 has no basket value; +2 does
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], market=near)
    step = only(run).steps[-1]
    assert step.rule_id == "M-080" and step.inputs["round_month"] == "2024-06" and step.inputs["comp_month_used"] == "2024-08"
    assert step.inputs["comps_source"].startswith("live:") and step.inputs["bound_hit"] is False
    far = _hist(12.0, then_key="2024-01")                        # five months away: outside ±3
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], market=far)
    assert "M-080" not in rule_ids(only(run))
    tol = with_policy(cfg, **{"marking.calibration.round_month_tolerance": 6})
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], cfg_=tol, market=far)
    assert only(run).steps[-1].inputs["comp_month_used"] == "2024-01"


def test_m080_calibration_writes_alternative_only(build, cfg):
    alt = with_policy(cfg, **{"marking.calibration.enabled": True})
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], cfg_=alt, market=_hist(12.0))
    c = only(run)
    assert c.alternative_marks["calibrated_to_comps"] == pytest.approx(12.0)
    assert c.proposed_mark == pytest.approx(10.0) and c.booked_mark == pytest.approx(10.0)
    assert rule_ids(c) == ["M-000", "M-080"]
    step = c.steps[-1]
    assert step.prior_value == step.new_value == pytest.approx(10.0)
    assert step.inputs["factor_bounded"] == pytest.approx(1.2) and step.inputs["age_months"] == 27.5
    assert step.inputs["factor_raw"] == pytest.approx(1.2) and step.inputs["bound_hit"] is False
    assert step.evidence is None, "calibration is not event-driven"
    assert run.totals.proposed_nav == pytest.approx(10.0)


def test_m080_factor_is_bounded(build, cfg):
    alt = with_policy(cfg, **{"marking.calibration.enabled": True, "marking.calibration.bound_pct": 0.35})
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], cfg_=alt, market=_hist(30.0))
    c = only(run)
    assert c.alternative_marks["calibrated_to_comps"] == pytest.approx(13.5)
    assert c.steps[-1].inputs["bound_hit"] is True and c.steps[-1].inputs["factor_raw"] == pytest.approx(3.0)
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], cfg_=alt, market=_hist(2.0))
    assert only(run).alternative_marks["calibrated_to_comps"] == pytest.approx(6.5)


def test_m080_skips_young_listed_terminal_and_unknown_sector(build, cfg):
    alt = with_policy(cfg, **{"marking.calibration.enabled": True})
    young, _ = build([position()], [], cfg_=alt, market=_hist(12.0))                      # 15 months < 24
    assert "M-080" not in rule_ids(only(young))
    other, _ = build([position(latest_round=date(2024, 6, 15), sector="Fintech")], [], cfg_=alt, market=_hist(12.0))
    assert "M-080" not in rule_ids(only(other))
    dead, _ = build([position(latest_round=date(2024, 6, 15))], [event(EventType.SHUTDOWN)], cfg_=alt, market=_hist(12.0))
    assert "M-080" not in rule_ids(only(dead))
    no_arr, _ = build([position(latest_round=date(2024, 6, 15), arr=None, arr_growth=None)], [], cfg_=alt, market=_hist(12.0))
    assert "M-080" not in rule_ids(only(no_arr))


def test_m080_on_real_workbook_never_moves_the_book(cfg):
    """Enabling calibration with a comp history changes alternatives only; NAV is identical.

    Regression: M-080 once recorded its no-op step as equity→equity, which broke the chain
    invariant (proposed = equity + note leg) for Duskfern and crashed the whole run."""
    from conftest import GENERATED_AT, WORKBOOK_PATH, run_workbook
    alt = with_policy(cfg, **{"marking.calibration.enabled": True})
    base, _ = run_workbook(WORKBOOK_PATH, cfg)
    sectors = {c.sector for c in base.companies}
    hist = {s: {f"{y}-{m:02d}": 10.0 * (1 + 0.01 * ((y - 2018) * 12 + m)) for y in range(2018, 2027) for m in range(1, 13)}
            for s in sectors}
    from hc_valuation.engine.models import SectorComp
    comps = {s: SectorComp(sector=s, ev_to_arr=hist[s]["2026-09"], as_of=MD, source="live:edgar+yahoo@2026-09") for s in sectors}
    calibrated, _ = run_workbook(WORKBOOK_PATH, alt, market=MarketData(comp_history=hist, comps=comps, as_of=MD))
    assert calibrated.totals.proposed_nav == pytest.approx(base.totals.proposed_nav, abs=1e-9)
    assert calibrated.totals.dispositions == base.totals.dispositions
    touched = [c for c in calibrated.companies if "calibrated_to_comps" in c.alternative_marks]
    assert touched, "some stale positions should receive an alternative"
    for c in touched:
        assert c.proposed_mark == base.by_company()[c.company].proposed_mark
        assert c.steps[-1].rule_id == "M-080"


def test_e01_override_resolves_the_block_it_addresses(build):
    """A committee override that names the BLOCK rule stops the position waiting; the flag stays visible."""
    pos = position(latest_post_money=100.0, ownership=0.1, prior_mark=10.0)
    ev = event(event_type="Priced Equity Round", detail="Series B (recap)", value=50.0, ownership_after=0.08)
    run, _ = build([pos], [ev])
    c = only(run)
    assert c.disposition == Disposition.BLOCK and "X-102" in flag_ids(c)
    ledger = OverrideLedger(records=(OverrideRecord(
        company="Alpha", quarter="Q3 2026", proposed=c.proposed_mark, booked=3.0, reason="Preference stack reviewed; junior equity worth ~75% of headline",
        approver="Tom Moore", created_at=date(2026, 9, 29), rule_ids_addressed=("X-102",)),))
    run2, _ = build([pos], [ev], overrides=ledger)
    c2 = only(run2)
    assert c2.booked_mark == pytest.approx(3.0) and c2.proposed_mark == pytest.approx(c.proposed_mark)
    assert "X-102" in flag_ids(c2), "the flag is still on the record"
    assert c2.disposition == Disposition.MONITOR, "but the position is no longer waiting on a decision"
    # an override that names a different rule does NOT clear the block
    ledger2 = OverrideLedger(records=(ledger.records[0].model_copy(update={"rule_ids_addressed": ("X-201",)}),))
    run3, _ = build([pos], [ev], overrides=ledger2)
    assert only(run3).disposition == Disposition.BLOCK
