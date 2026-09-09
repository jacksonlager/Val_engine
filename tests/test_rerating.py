"""How a sector's public comps re-rating is measured, and what a multiple regime is allowed to move.

The re-rating (engine/rerating.py) is the median of each name's own now ÷ then over the same
names — never one basket median divided by another, which with five-name baskets compares two
different companies and moves whenever a name enters the basket. M-080 and `comps_move` share
it. The exposure share (rollup.exposed_share) says how much of a mark rests on a round: all of a
round price, the break-branch weight of a probability-weighted deal mark, none of a deal price
or the buyer's shares. And X-405 offers the calibration only when it points the way the screen
does.
"""
from __future__ import annotations

from datetime import date

import pytest
from conftest import event, only, position, with_policy

from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import MarketData, OverrideLedger, OverrideRecord, SectorComp
from hc_valuation.engine.rerating import BASKET_RATIO, SAME_SET, sector_rerating
from hc_valuation.engine.rollup import exposed_amount
from hc_valuation.export.tables import _sensitivity_label

MD = date(2026, 9, 30)


def _market(names: dict[str, dict[str, float]] | None, hist: dict[str, float], sector: str = "SaaS",
            source: str = "live:edgar+yahoo@2026-09") -> MarketData:
    return MarketData(comp_history={sector: hist},
                      comp_counts={sector: {m: sum(1 for n in (names or {}).values() if m in n) for m in hist}} if names else {},
                      comp_constituents={sector: names} if names else {},
                      comps={sector: SectorComp(sector=sector, ev_to_arr=hist["2026-09"], as_of=MD, source=source)}, as_of=MD)


# ---------------------------------------------------------------- the statistic

def test_same_set_median_of_per_name_ratios_not_a_ratio_of_basket_medians():
    """Three names: A doubles, B halves, C flat. The basket medians are C both times (10 → 10),
    so the basket ratio says 1.0; the per-name moves are 2.0, 0.5 and 1.0, median 1.0 here — but
    make C move a little and the two statistics part company."""
    names = {"A": {"2024-06": 5.0, "2026-09": 10.0}, "B": {"2024-06": 20.0, "2026-09": 10.0}, "C": {"2024-06": 10.0, "2026-09": 12.0}}
    m = _market(names, {"2024-06": 10.0, "2026-09": 10.0})
    rr = sector_rerating(m, "SaaS", "2024-06", "2026-09", window=0, min_names=3)
    assert rr is not None and rr.method == SAME_SET and rr.n_names == 3
    assert [n.ratio for n in rr.names] == [2.0, 0.5, 1.2]             # each name's own move, in ticker order
    assert rr.factor == pytest.approx(1.2)                             # the median of those, not 10 ÷ 10 = 1.0
    assert "A 10.00÷5.00=2.00" in rr.formula() and "median of 3 = 1.200" in rr.formula()


def test_a_name_entering_the_basket_does_not_move_the_re_rating():
    """The composition trap: three names in the round month, five today. The basket median jumps
    from the third of three to the third of five — on Ostrella's Space & Defense history that read
    +15% where the three names present both times read −20%. The same-set statistic sees only
    the names priced at both ends."""
    names = {"IRDM": {"2021-08": 12.0, "2026-09": 7.4}, "KTOS": {"2021-08": 3.7, "2026-09": 5.2}, "AVAV": {"2021-08": 6.5, "2026-09": 3.8},
             "RKLB": {"2026-09": 47.0}, "PL": {"2026-09": 17.3}}     # the two IPOs of 2021-08+ have no round-month value
    m = _market(names, {"2021-08": 6.5, "2026-09": 7.4})           # basket medians: 6.5 (of 3) → 7.4 (of 5): +14%
    rr = sector_rerating(m, "Space & Defense" if False else "SaaS", "2021-08", "2026-09", window=0, min_names=3)
    assert rr.n_names == 3 and {n.ticker for n in rr.names} == {"IRDM", "KTOS", "AVAV"}
    assert rr.factor == pytest.approx(sorted([7.4 / 12.0, 5.2 / 3.7, 3.8 / 6.5])[1], abs=1e-4)   # 0.617, 1.405, 0.585 → 0.617
    assert rr.factor < 1 < 7.4 / 6.5, "the basket ratio has the wrong sign"


def test_each_end_is_a_names_median_over_the_window():
    """A one-month trough in a thin stock (7.70 between 13.38 and 14.34) must not set the number:
    with window 1 the round-month value is the median of the three months around it."""
    names = {n: {"2023-09": 13.38, "2023-10": 7.70, "2023-11": 14.34, "2026-08": 14.0, "2026-09": 14.0, "2026-10": 14.0} for n in "XYZ"}
    m = _market(names, {"2023-10": 7.70, "2026-09": 14.0})
    single = sector_rerating(m, "SaaS", "2023-10", "2026-09", window=0, min_names=3)
    windowed = sector_rerating(m, "SaaS", "2023-10", "2026-09", window=1, min_names=3)
    assert single.factor == pytest.approx(14.0 / 7.70, abs=1e-3)
    assert windowed.factor == pytest.approx(14.0 / 13.38, abs=1e-3) and windowed.window == 1
    assert windowed.names[0].then == pytest.approx(13.38)


def test_fewer_names_than_the_floor_falls_back_to_the_basket_ratio_and_says_so():
    names = {"A": {"2024-06": 5.0, "2026-09": 10.0}, "B": {"2024-06": 20.0, "2026-09": 10.0}}
    m = _market(names, {"2024-06": 10.0, "2026-09": 12.0})
    rr = sector_rerating(m, "SaaS", "2024-06", "2026-09", window=0, min_names=3)
    assert rr.method == BASKET_RATIO and rr.factor == pytest.approx(1.2) and rr.names == ()
    assert sector_rerating(_market(None, {"2026-09": 12.0}), "SaaS", "2024-06", "2026-09") is None


# ---------------------------------------------------------------- M-080 on the statistic

def test_m080_records_every_name_and_writes_the_arithmetic(build, cfg):
    names = {"A": {"2024-06": 5.0, "2026-09": 10.0}, "B": {"2024-06": 20.0, "2026-09": 10.0}, "C": {"2024-06": 10.0, "2026-09": 12.0}}
    m = _market(names, {"2024-06": 10.0, "2026-09": 10.0})
    run, _ = build([position(latest_round=date(2024, 6, 15))], [], market=m)          # equity 10.0, 27.5 months
    c = only(run)
    st = c.steps[-1]
    assert st.rule_id == "M-080" and st.inputs["method"] == SAME_SET and st.inputs["n_names"] == 3
    assert [n["ticker"] for n in st.inputs["names"]] == ["A", "B", "C"]
    assert st.inputs["factor_raw"] == pytest.approx(1.2) and st.inputs["bound_hit"] is False
    assert c.alternative_marks["calibrated_to_comps"] == pytest.approx(12.0)
    assert "median of 3 = 1.200" in st.formula and "$10.00M × 1.2000 = $12.00M" in st.formula
    assert "below invested cost" not in st.rationale and st.inputs["below_invested_cost"] is False


def test_m080_formula_reproduces_its_result_to_the_cent(build, cfg):
    """A 2-dp factor in the formula did not reproduce the figure ($6.60M × 1.03 ≠ $6.77M)."""
    names = {n: {"2024-06": 10.0, "2026-09": 10.265} for n in "ABC"}
    run, _ = build([position(latest_round=date(2024, 6, 15), prior_mark=6.6)], [], market=_market(names, {"2024-06": 10.0, "2026-09": 10.265}))
    st = only(run).steps[-1]
    assert "$6.60M × 1.0265 = $6.77M" in st.formula
    assert only(run).alternative_marks["calibrated_to_comps"] == pytest.approx(6.6 * 1.0265)


def test_m080_skips_a_deal_priced_position(build, cfg):
    names = {n: {"2020-06": 10.0, "2026-09": 12.0} for n in "ABC"}
    run, _ = build([position(latest_round=date(2020, 6, 15))],
                   [event(EventType.ACQ_ANNOUNCED, date=date(2026, 8, 1), detail="Definitive agreement", value=300.0)],
                   market=_market(names, {"2020-06": 10.0, "2026-09": 12.0}))
    c = only(run)
    assert "M-080" not in [s.rule_id for s in c.steps] and "calibrated_to_comps" not in c.alternative_marks


# ---------------------------------------------------------------- what a multiple regime moves

def test_exposure_share_of_a_probability_weighted_deal_mark_is_the_break_branch(build, cfg):
    """Gryphonel's shape: 0.90 × deal + 0.10 × standalone. Only the standalone branch rests on
    the round, so the share is (1 − p) × standalone ÷ mark."""
    run, _ = build([position()], [event(EventType.ACQ_ANNOUNCED, date=date(2026, 8, 1), detail="Definitive agreement", value=300.0)])
    c = only(run)
    full, hold = 0.10 * 300.0, 10.0
    weighted = 0.9 * full + 0.1 * hold
    assert c.booked_mark == pytest.approx(weighted)
    assert c.multiple_exposed and c.multiple_exposed_share == pytest.approx(0.1 * hold / weighted, abs=1e-6)
    assert exposed_amount(c) == pytest.approx(0.1 * hold, abs=1e-4)          # the share is stored to 6 dp
    assert run.sensitivity["multiple_exposed_nav"] == pytest.approx(0.1 * hold, abs=1e-4)


def test_exposure_share_is_whole_for_a_non_binding_offer_and_zero_at_full_deal_value(build, cfg):
    run, _ = build([position()], [event(EventType.ACQ_ANNOUNCED, date=date(2026, 8, 1), detail="Non-binding letter of intent", value=300.0)])
    c = only(run)
    assert c.booked_mark == pytest.approx(10.0) and c.multiple_exposed_share == 1.0 and exposed_amount(c) == pytest.approx(10.0)
    full = with_policy(cfg, **{"marking.announced.treatment": "full_deal_value"})
    run, _ = build([position()], [event(EventType.ACQ_ANNOUNCED, date=date(2026, 8, 1), detail="Definitive agreement", value=300.0)], cfg_=full)
    c = only(run)
    assert c.booked_mark == pytest.approx(30.0) and not c.multiple_exposed and c.multiple_exposed_share == 0.0


def test_a_stake_rolled_into_the_buyer_is_not_shocked(build, cfg):
    run, _ = build([position()], [event(EventType.ACQ_CLOSED, date=date(2026, 9, 1), detail="Cash and stock", value=200.0,
                                        proceeds=16.0, ownership_after=0.02)])
    c = only(run)
    assert any(i.kind.value == "acquirer_shares" for i in c.open_items) and c.booked_mark == pytest.approx(4.0)
    assert not c.multiple_exposed and exposed_amount(c) == 0.0


def test_a_mark_booked_below_its_note_leg_contributes_nothing_never_a_negative(build, cfg):
    """Equity 10.0 + a $0.5M note at cost, overridden to $0.2M: the equity leg is gone, and the
    shock must not read a negative exposure (a rising multiple lowering NAV)."""
    ov = OverrideRecord(company="Alpha", quarter="Q3 2026", proposed=10.5, booked=0.2, reason="test", approver="t", created_at=MD)
    run, _ = build([position()], [event(EventType.CONVERTIBLE_NOTE, date=date(2026, 8, 1), detail="Bridge", value=0.5, hc_investment=0.5)],
                   overrides=OverrideLedger(records=(ov,)))
    c = only(run)
    assert c.booked_mark == pytest.approx(0.2) and c.note_at_cost == pytest.approx(0.5)
    assert exposed_amount(c) == 0.0 and run.sensitivity["multiple_exposed_nav"] == 0.0
    assert run.sensitivity["nav_if_multiples_+20pct"] == pytest.approx(0.2)


# ---------------------------------------------------------------- X-405 and the calibrate option

def _stale_high_multiple(arr: float = 2.0):
    # 25.5 months old, $100M post ÷ $2M ARR = 50× — above the absolute 30× bound, so X-401 fires
    return position(arr=arr, latest_round=date(2024, 8, 15))


def test_x405_offers_the_calibration_only_when_it_points_the_way_the_screen_does(build, cfg):
    up = {n: {"2024-08": 10.0, "2026-09": 12.0} for n in "ABC"}
    run, _ = build([_stale_high_multiple()], [], market=_market(up, {"2024-08": 10.0, "2026-09": 12.0}))
    f = next(x for x in only(run).flags if x.rule_id == "X-405")
    assert f.evidence["screen_direction"] == "above" and f.evidence["calibration_factor"] == pytest.approx(1.2)
    assert f.evidence["calibration_offered"] is False and "calibrate" not in {s.key for s in f.suggestions}
    assert "would move the mark up" in f.message and "not offered" in f.message

    down = {n: {"2024-08": 10.0, "2026-09": 8.0} for n in "ABC"}
    run, _ = build([_stale_high_multiple()], [], market=_market(down, {"2024-08": 10.0, "2026-09": 8.0}))
    f = next(x for x in only(run).flags if x.rule_id == "X-405")
    cal = {s.key: s for s in f.suggestions}["calibrate"]
    assert f.evidence["calibration_offered"] is True and cal.booked == pytest.approx(8.0)
    assert cal.label == "Calibrate the mark to public comps: $10.00M × 0.8000 = $8.00M (-20.0% since the round)."


def test_the_calibrate_label_says_when_policy_capped_the_number(build, cfg):
    crash = {n: {"2024-08": 10.0, "2026-09": 4.0} for n in "ABC"}                # ×0.40, capped at 0.65
    run, _ = build([_stale_high_multiple()], [], market=_market(crash, {"2024-08": 10.0, "2026-09": 4.0}))
    f = next(x for x in only(run).flags if x.rule_id == "X-405")
    cal = {s.key: s for s in f.suggestions}["calibrate"]
    assert cal.booked == pytest.approx(6.5)
    assert cal.label == "Calibrate the mark to public comps: $10.00M × 0.6500 = $6.50M — comps moved ×0.400 (-60%), capped by policy at -35%."
    st = only(run).steps[-1]
    assert st.inputs["bound_hit"] is True and "CAPPED at -35%" in st.rationale and "$10.00M × 0.400 = $4.00M" in st.formula


def test_x401_states_what_is_compared_to_what(build, cfg):
    live = {n: {"2026-09": 10.0} for n in "ABCDE"}
    run, _ = build([position(arr=2.0)], [], market=_market(live, {"2026-09": 10.0}))
    f = next(x for x in only(run).flags if x.rule_id == "X-401")
    assert "post-money ÷ $2.0M ARR = 50.0×" in f.message and "EV ÷ trailing-revenue median" in f.message
    assert "post-money is not enterprise value and ARR is not trailing revenue" in f.message
    assert f.evidence["sector_median"] == 10.0 and f.evidence["median_names"] == 5 and f.evidence["bound_multiplier"] == 2.0
    assert f.evidence["formula"] == "100.0 ÷ 2.0 = 50.00× vs 2 × 10.00× = 20.00×"


# ---------------------------------------------------------------- the export says which scope

def test_export_labels_name_the_scope_of_each_sensitivity_figure():
    assert _sensitivity_label("nav_if_multiples_+20pct") == "Sensitivity: NAV if all sector multiples move +20%"
    assert _sensitivity_label("nav_if_software_multiples_-20pct") == "Sensitivity: NAV if software multiples move −20%"
    assert _sensitivity_label("software_exposed_nav").endswith("software sectors only")
    assert "all sectors" in _sensitivity_label("multiple_exposed_nav")
