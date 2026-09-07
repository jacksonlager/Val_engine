"""Stress tests: base-rule conformance, threshold boundaries, X-405 composition, missing
metrics, and the shape of every REVIEW / MONITOR finding.

The assessment says priced rounds reset the mark (ownership after × new post-money), exits
move to realized or zero, and no activity carries the prior mark; exceptions must cover stale
rounds, shrinking ARR, short runway and a mark that no longer squares with performance, and be
impossible to miss. Every test here builds one synthetic position from `conftest.position()`
(deliberately clean on every screen) and changes exactly the one thing under test.

Boundary conventions the tests establish (see the module-level POLICY NOTES in the report):

* Staleness age is `months_between` = round(days / 30.4375, 1). It is rounded to one decimal
  BEFORE the comparison, so the reachable neighbours of 24.0 are 23.9 and 24.1 — "23.99" and
  "24.01" do not exist. Every threshold is compared strictly (`>`), so 24.0 does not fire.
* ARR growth, runway and multiple screens are all strict (`<` / `>`): a value exactly on the
  policy line does not fire the higher severity.
* The multiple screen falls back to the absolute bounds when there are no live comps, which is
  what the default `MarketData` gives.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import event, flag_ids, only, position, rule_ids
from hc_valuation.engine.inputs import EventType, Status
from hc_valuation.engine.marking import months_between
from hc_valuation.engine.models import Disposition, Readiness, Severity, ValuationAction


# ----------------------------------------------------------------------------- helpers

def _flag(c, rule_id: str):
    hits = [f for f in c.flags if f.rule_id == rule_id]
    assert hits, f"{rule_id} not raised; have {sorted(flag_ids(c))}"
    assert len(hits) == 1, f"{rule_id} raised {len(hits)} times"
    return hits[0]


def _assert_review_shape(c, rule_id: str, *, severity: Severity = Severity.REVIEW):
    """Requirement 5: a finding a reviewer must act on is complete and puts the position in
    Needs Review (Blocked is only for missing-input rules / provisional marks)."""
    f = _flag(c, rule_id)
    assert f.severity == severity
    assert f.action.strip(), f"{rule_id}: REVIEW/BLOCK flag has no action"
    assert 2 <= len(f.points) <= 3, f"{rule_id}: expected 2-3 points, got {len(f.points)}: {f.points}"
    assert all(p.strip() for p in f.points)
    assert f.suggestions, f"{rule_id}: no suggestions on a {severity.value} flag"
    for sg in f.suggestions:
        assert sg.label.strip() and len(sg.reasons) == 2
    assert c.readiness == Readiness.NEEDS_REVIEW, (c.readiness, sorted(flag_ids(c)))
    return f


def _assert_monitor_only(c):
    """Requirement 5: MONITOR-only positions are Ready and tagged monitor."""
    assert c.flags, "expected at least one MONITOR flag"
    assert all(f.severity == Severity.MONITOR for f in c.flags), [(f.rule_id, f.severity.value) for f in c.flags]
    for f in c.flags:
        assert f.action == "" and f.points == () and f.suggestions == (), f"{f.rule_id}: MONITOR carries reviewer content"
    assert c.readiness == Readiness.READY
    assert c.monitor is True
    assert c.disposition == Disposition.MONITOR


def _assert_clean(c):
    assert c.flags == (), [(f.rule_id, f.severity.value) for f in c.flags]
    assert c.readiness == Readiness.READY and c.monitor is False and c.disposition == Disposition.CLEAR


def _md(cfg) -> date:
    return cfg.quarter.measurement_date


def _round_dated_days_ago(cfg, days: int) -> date:
    return _md(cfg) - timedelta(days=days)


def _round_aged(cfg, target: float, *, prefer: str = "oldest") -> date:
    """A Latest Round date whose `months_between` age reads exactly `target` (one decimal).
    Several day counts round to the same tenth; `prefer` picks the oldest or youngest of them
    so a test can name the harshest case on either side of the line."""
    md = _md(cfg)
    centre = int(round(target * 30.4375))
    hits = [d for d in range(centre - 4, centre + 5) if months_between(md - timedelta(days=d), md) == target]
    assert hits, f"no day count reads as {target} months"
    return md - timedelta(days=(max(hits) if prefer == "oldest" else min(hits)))


# ============================================================================= 1. base rules

def test_priced_round_resets_mark_to_ownership_after_times_post_money(build):
    """Assessment: 'priced rounds reset the mark (ownership after times new post-money)'."""
    run, issues = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.09)])
    c = only(run)
    assert issues == []
    assert c.proposed_mark == pytest.approx(0.09 * 200.0, abs=1e-6)
    assert c.equity_mark == pytest.approx(18.0, abs=1e-6) and c.note_at_cost == 0.0
    steps = [s for s in c.steps if s.rule_id == "M-010"]
    assert len(steps) == 1 and rule_ids(c) == ["M-010"]
    ev = steps[0].evidence
    assert ev is not None and ev.event_type == EventType.PRICED_ROUND.value and ev.row_index == 2 and ev.date == date(2026, 8, 15)
    assert steps[0].inputs["post_money"] == 200.0 and steps[0].inputs["ownership_after"] == 0.09
    assert steps[0].prior_value == 10.0 and steps[0].new_value == pytest.approx(18.0)
    assert c.latest_post_money == 200.0 and c.ownership_after == 0.09 and c.staleness_anchor == date(2026, 8, 15)
    assert c.action == ValuationAction.REVALUE and c.status_after == Status.ACTIVE
    _assert_clean(c)


def test_priced_round_with_hc_participation_uses_same_formula(build):
    """Ownership up with HC money in: the mark is still ownership_after × post; invested grows
    by the cheque. The cheque is chosen to reconcile to the stated post (4.0 / 2.0% = $200M)
    so X-119 has nothing to say."""
    run, _ = build([position()], [event(detail="Series B", value=200.0, ownership_after=0.12, hc_investment=4.0)])
    c = only(run)
    assert c.proposed_mark == pytest.approx(0.12 * 200.0, abs=1e-6)
    assert c.invested_after == pytest.approx(9.0) and c.new_investment_quarter == pytest.approx(4.0)
    assert c.ownership_after == 0.12 and rule_ids(c) == ["M-010"]
    assert c.steps[-1].inputs["hc_investment"] == 4.0
    assert c.steps[-1].inputs["implied_post_from_hc_cheque"] == pytest.approx(200.0)
    assert c.action == ValuationAction.REVALUE
    _assert_clean(c)


def test_closed_acquisition_marks_zero_and_realizes_proceeds(build):
    """Assessment: 'exits move to realized or zero'. Proceeds equal ownership × deal so the
    reconciliation is silent; the position is terminal and CLEAR."""
    run, _ = build([position(realized=1.0)], [event(EventType.ACQ_CLOSED, detail="Acquired by BigCo", value=150.0, proceeds=15.0)])
    c = only(run)
    assert c.proposed_mark == 0.0 and c.equity_mark == 0.0
    assert c.realized_quarter == pytest.approx(15.0) and c.realized_cumulative == pytest.approx(16.0)
    assert c.status_after == Status.ACQUIRED and c.fv_level is None
    assert rule_ids(c) == ["M-020"] and c.steps[-1].evidence.row_index == 2
    assert c.action == ValuationAction.FULL_EXIT
    assert c.valuation_change_quarter == pytest.approx(15.0 - 10.0)
    _assert_clean(c)


def test_shutdown_marks_zero(build):
    run, _ = build([position()], [event(EventType.SHUTDOWN, detail="Ceased operations", proceeds=None)])
    c = only(run)
    assert c.proposed_mark == 0.0 and c.realized_quarter == 0.0
    assert c.status_after == Status.SHUT_DOWN and rule_ids(c) == ["M-021"]
    assert c.action == ValuationAction.WRITE_OFF and c.valuation_change_quarter == pytest.approx(-10.0)
    _assert_clean(c)


def test_no_activity_carries_prior_mark_with_m000_step(build):
    """Assessment: 'no activity carries the prior mark'."""
    run, issues = build([position()], [])
    c = only(run)
    assert issues == []
    assert c.proposed_mark == c.prior_mark == 10.0
    assert rule_ids(c) == ["M-000"] and len(c.steps) == 1
    assert c.steps[0].evidence is None and c.steps[0].prior_value == c.steps[0].new_value == 10.0
    assert c.steps[0].inputs["prior_mark"] == 10.0
    assert c.action == ValuationAction.CARRY and c.staleness_anchor == date(2025, 6, 15)
    _assert_clean(c)


def test_priced_round_resets_the_staleness_clock_on_a_very_stale_position(build, cfg):
    """A 51-month-old round repriced this quarter: the new round is the anchor, so neither
    X-201 nor X-202 fires and the mark is the new ownership × post."""
    run, _ = build([position(latest_round=date(2022, 6, 15))], [event(detail="Series B", value=200.0, ownership_after=0.09)])
    c = only(run)
    assert c.staleness_anchor == date(2026, 8, 15) and months_between(c.staleness_anchor, _md(cfg)) == 1.5
    assert c.proposed_mark == pytest.approx(18.0)
    _assert_clean(c)


@pytest.mark.parametrize("bad, issue", [
    (dict(value=None, ownership_after=0.09), "X-902"),
    (dict(value=200.0, ownership_after=None), "X-902"),
    (dict(value=0.0, ownership_after=0.09), "X-903"),
])
def test_priced_round_with_a_blank_or_zero_cell_is_refused_and_blocked(build, bad, issue):
    """A priced round missing its post-money or ownership cannot reset a mark. The row is
    refused at validation, the prior mark is carried, and the position is Blocked (X-900 is a
    MISSING_INPUT rule — the one case Blocked rather than Needs Review is right)."""
    run, issues = build([position()], [event(detail="Series B", **bad)])
    c = only(run)
    assert [i.rule_id for i in issues] == [issue]
    assert c.proposed_mark == 10.0 and "M-010" not in rule_ids(c) and set(rule_ids(c)) == {"M-000"}
    f = _flag(c, "X-900")
    assert f.severity == Severity.BLOCK and f.action.strip() and 2 <= len(f.points) <= 3 and f.suggestions
    assert c.readiness == Readiness.BLOCKED and c.disposition == Disposition.BLOCK
    assert f.evidence["row_index"] == 2 and issue in f.evidence["validation"]


def test_exit_drops_carry_side_screens(build):
    """A stale, shrinking, cash-poor company that was sold this quarter: staleness, growth and
    runway no longer mean anything, so the terminal position is CLEAR and Ready."""
    run, _ = build([position(latest_round=date(2022, 6, 15), arr_growth=-0.5, net_burn=1.0, cash=2.0)],
                   [event(EventType.ACQ_CLOSED, value=150.0, proceeds=15.0)])
    c = only(run)
    assert c.proposed_mark == 0.0 and c.realized_quarter == pytest.approx(15.0)
    _assert_clean(c)


# ============================================================================= 2. thresholds

# ---- staleness --------------------------------------------------------------------------

def test_staleness_thresholds_are_read_from_policy(cfg):
    assert cfg.exceptions.staleness.monitor_months == 24
    assert cfg.exceptions.staleness.review_months == 48
    assert months_between(_round_aged(cfg, 24.0), _md(cfg)) == 24.0
    assert months_between(_round_aged(cfg, 48.0), _md(cfg)) == 48.0


def test_staleness_exactly_24_months_does_not_fire(build, cfg):
    """`age > monitor_months` is strict: 24.0 is not older than 24."""
    run, _ = build([position(latest_round=_round_aged(cfg, 24.0, prefer="youngest"))], [])
    c = only(run)
    assert months_between(c.staleness_anchor, _md(cfg)) == float(cfg.exceptions.staleness.monitor_months)
    _assert_clean(c)


def test_staleness_23_9_months_does_not_fire(build, cfg):
    run, _ = build([position(latest_round=_round_aged(cfg, 23.9))], [])
    _assert_clean(only(run))


def test_staleness_24_1_months_is_x201_monitor(build, cfg):
    run, _ = build([position(latest_round=_round_aged(cfg, 24.1, prefer="youngest"))], [])
    c = only(run)
    f = _flag(c, "X-201")
    assert f.evidence["months"] == 24.1 and "X-202" not in flag_ids(c)
    _assert_monitor_only(c)


def test_staleness_rounding_hides_a_round_that_is_24_05_months_old(build, cfg):
    """POLICY QUESTION, not a defect: `months_between` rounds to one decimal *before* the
    comparison. A round 732 days old is 24.05 months by the policy's own 30.4375-day month,
    strictly older than 24, but reads as 24.0 and does not fire. The docstring on
    months_between says this is deliberate ("to one decimal"); the test pins the behaviour."""
    anchor = _round_dated_days_ago(cfg, 732)
    assert 732 / 30.4375 > 24.0 and months_between(anchor, _md(cfg)) == 24.0
    run, _ = build([position(latest_round=anchor)], [])
    _assert_clean(only(run))


def test_staleness_exactly_48_months_is_x201_not_x202(build, cfg):
    """1461 days = 48.0 months exactly (48 × 30.4375). Strict `>` keeps it at MONITOR."""
    anchor = _round_dated_days_ago(cfg, 1461)
    assert months_between(anchor, _md(cfg)) == 48.0
    run, _ = build([position(latest_round=anchor)], [])
    c = only(run)
    assert "X-202" not in flag_ids(c)
    assert _flag(c, "X-201").evidence["months"] == 48.0
    _assert_monitor_only(c)


def test_staleness_47_9_months_is_x201(build, cfg):
    run, _ = build([position(latest_round=_round_aged(cfg, 47.9))], [])
    c = only(run)
    assert "X-202" not in flag_ids(c) and _flag(c, "X-201").evidence["months"] == 47.9
    _assert_monitor_only(c)


def test_staleness_48_1_months_is_x202_review(build, cfg):
    run, _ = build([position(latest_round=_round_aged(cfg, 48.1, prefer="youngest"))], [])
    c = only(run)
    f = _assert_review_shape(c, "X-202")
    assert f.evidence["months"] == 48.1 and "X-201" not in flag_ids(c)
    assert c.disposition == Disposition.REVIEW and c.proposed_mark == 10.0, "staleness never changes a mark"
    # the round-age is in the reviewer-facing text, so the finding cannot be missed
    assert "48.1" in f.message and any("48.1" in p for p in f.points)


# ---- ARR growth -------------------------------------------------------------------------

def test_arr_growth_thresholds_are_read_from_policy(cfg):
    assert cfg.exceptions.arr_growth.monitor_below == 0.0
    assert cfg.exceptions.arr_growth.review_below == -0.15


def test_arr_growth_zero_does_not_fire(build, cfg):
    """`g < monitor_below` is strict: flat revenue is not 'down'."""
    run, _ = build([position(arr_growth=cfg.exceptions.arr_growth.monitor_below)], [])
    _assert_clean(only(run))


def test_arr_growth_just_below_zero_is_x301_monitor(build):
    run, _ = build([position(arr_growth=-0.0001)], [])
    c = only(run)
    assert _flag(c, "X-301").evidence["arr_growth"] == -0.0001
    _assert_monitor_only(c)


def test_arr_growth_exactly_minus_15pct_is_x301_not_x302(build, cfg):
    """STRICT comparison: -0.15 is not `< -0.15`, so a company shrinking exactly 15% is MONITOR.
    Consistent with the policy key name `review_below`; recorded as a POLICY QUESTION."""
    run, _ = build([position(arr_growth=cfg.exceptions.arr_growth.review_below)], [])
    c = only(run)
    assert "X-302" not in flag_ids(c)
    assert _flag(c, "X-301").evidence["arr_growth"] == -0.15
    _assert_monitor_only(c)


def test_arr_growth_minus_14_99pct_is_x301(build):
    run, _ = build([position(arr_growth=-0.1499)], [])
    c = only(run)
    assert "X-302" not in flag_ids(c) and "X-301" in flag_ids(c)
    _assert_monitor_only(c)


def test_arr_growth_minus_15_01pct_is_x302_review(build):
    run, _ = build([position(arr_growth=-0.1501)], [])
    c = only(run)
    f = _assert_review_shape(c, "X-302")
    assert "X-301" not in flag_ids(c)
    assert f.evidence["arr_growth"] == -0.1501 and c.disposition == Disposition.REVIEW
    assert "shrinking" in f.message.lower()
    # the to_cost suggestion books min(invested, proposed) = 5.0, the proposed one 10.0
    booked = {s.key: s.booked for s in f.suggestions}
    assert booked["as_proposed"] == pytest.approx(10.0) and booked["to_cost"] == pytest.approx(5.0)


# ---- runway -----------------------------------------------------------------------------

def test_runway_thresholds_are_read_from_policy(cfg):
    assert cfg.exceptions.runway.review_below_mo == 6
    assert cfg.exceptions.runway.monitor_below_mo == 12
    assert cfg.metrics.reporting_lag_months == 1


def _runway_position(cfg, aged: float, **kw):
    """cash / burn so that (cash / burn) - reporting_lag == aged, with burn = 1.0 so the
    arithmetic is exact in floating point."""
    return position(net_burn=1.0, cash=aged + cfg.metrics.reporting_lag_months, **kw)


def test_runway_aged_exactly_6_is_x303_not_x304(build, cfg):
    """STRICT: aged 6.0 is not `< review_below_mo`. Falls to the 12-month MONITOR band."""
    run, _ = build([_runway_position(cfg, float(cfg.exceptions.runway.review_below_mo))], [])
    c = only(run)
    assert c.runway_months_aged == pytest.approx(6.0)
    assert "X-304" not in flag_ids(c)
    assert _flag(c, "X-303").evidence["runway_months_aged"] == pytest.approx(6.0)
    _assert_monitor_only(c)


def test_runway_aged_5_99_is_x304_review(build, cfg):
    run, _ = build([_runway_position(cfg, 5.99)], [])
    c = only(run)
    f = _assert_review_shape(c, "X-304")
    assert "X-303" not in flag_ids(c)
    assert f.evidence["runway_months_aged"] == pytest.approx(5.99) and f.evidence["financings_in_quarter"] == []
    assert c.disposition == Disposition.REVIEW and c.proposed_mark == 10.0
    assert "6.0 months of cash" in f.message  # {aged:.1f} — the number the reviewer sees


def test_runway_aged_6_01_is_x303(build, cfg):
    run, _ = build([_runway_position(cfg, 6.01)], [])
    c = only(run)
    assert "X-304" not in flag_ids(c) and "X-303" in flag_ids(c)
    _assert_monitor_only(c)


def test_runway_aged_exactly_12_does_not_fire(build, cfg):
    run, _ = build([_runway_position(cfg, float(cfg.exceptions.runway.monitor_below_mo))], [])
    c = only(run)
    assert c.runway_months_aged == pytest.approx(12.0)
    _assert_clean(c)


def test_runway_aged_11_99_is_x303(build, cfg):
    run, _ = build([_runway_position(cfg, 11.99)], [])
    c = only(run)
    assert "X-303" in flag_ids(c)
    _assert_monitor_only(c)


def test_runway_is_aged_by_reporting_lag_not_sheet_value(build, cfg):
    """A sheet runway of 6.5 months reads as 5.5 aged, so it is REVIEW even though the raw
    cash / burn is above the 6-month line."""
    run, _ = build([position(net_burn=1.0, cash=6.5)], [])
    c = only(run)
    assert c.runway_months_aged == pytest.approx(5.5)
    _assert_review_shape(c, "X-304")


# ---- implied multiple (absolute mode: MarketData default has no live comps) ----------------

def test_multiple_thresholds_are_read_from_policy(cfg):
    assert cfg.exceptions.multiple.absolute_high == 30
    assert cfg.exceptions.multiple.absolute_low == 3
    assert cfg.exceptions.multiple.min_arr == 0.5
    assert cfg.exceptions.multiple.mode == "relative_to_comps" and cfg.exceptions.multiple.require_live_comps


def _multiple_position(post: float, arr: float = 10.0, **kw):
    """latest_post / arr is the implied multiple. invested is scaled so MOIC stays at 2.0 and
    X-404 is never in play."""
    return position(latest_post_money=post, arr=arr, invested=0.10 * post / 2.0, **kw)


def test_multiple_exactly_30x_does_not_fire(build, cfg):
    run, _ = build([_multiple_position(post=30.0 * 10.0)], [])
    c = only(run)
    assert c.implied_multiple == pytest.approx(float(cfg.exceptions.multiple.absolute_high))
    _assert_clean(c)


def test_multiple_30_1x_is_x401_monitor_on_absolute_bound(build, cfg):
    run, _ = build([_multiple_position(post=301.0)], [])
    c = only(run)
    f = _flag(c, "X-401")
    assert f.evidence["implied_multiple"] == pytest.approx(30.1)
    assert f.evidence["threshold"] == cfg.exceptions.multiple.absolute_high
    assert f.evidence["basis"] == "absolute policy bound", "no live comps → absolute mode"
    _assert_monitor_only(c)


def test_multiple_29_9x_does_not_fire(build):
    run, _ = build([_multiple_position(post=299.0)], [])
    _assert_clean(only(run))


def test_multiple_exactly_3x_does_not_fire(build, cfg):
    run, _ = build([_multiple_position(post=3.0 * 10.0)], [])
    c = only(run)
    assert c.implied_multiple == pytest.approx(float(cfg.exceptions.multiple.absolute_low))
    _assert_clean(c)


def test_multiple_2_9x_is_x402_monitor(build, cfg):
    run, _ = build([_multiple_position(post=29.0)], [])
    c = only(run)
    f = _flag(c, "X-402")
    assert f.evidence["implied_multiple"] == pytest.approx(2.9)
    assert f.evidence["threshold"] == cfg.exceptions.multiple.absolute_low and f.evidence["basis"] == "absolute policy bound"
    _assert_monitor_only(c)


def test_multiple_3_1x_does_not_fire(build):
    run, _ = build([_multiple_position(post=31.0)], [])
    _assert_clean(only(run))


def test_arr_below_min_arr_is_x403_only(build, cfg):
    """$0.4M ARR on a $100M post would be 250×; the screen is skipped, not reported."""
    run, _ = build([position(arr=cfg.exceptions.multiple.min_arr - 0.1)], [])
    c = only(run)
    assert flag_ids(c) == {"X-403"}
    assert c.implied_multiple is None and c.multiple_exposed is False
    _assert_monitor_only(c)


def test_arr_exactly_min_arr_runs_the_screen(build, cfg):
    """`arr < min_arr` is strict, so $0.5M ARR is screened: $100M / $0.5M = 200× → X-401."""
    run, _ = build([position(arr=cfg.exceptions.multiple.min_arr)], [])
    c = only(run)
    assert flag_ids(c) == {"X-401"} and c.implied_multiple == pytest.approx(200.0)
    _assert_monitor_only(c)


# ---- MOIC on a stale round ------------------------------------------------------------------

def test_moic_threshold_is_read_from_policy(cfg):
    assert cfg.exceptions.moic.monitor_above == 5.0


def test_moic_exactly_5x_on_stale_round_does_not_fire_x404(build, cfg):
    """mark 10 / invested 2 = 5.0, round 27.5 months old: strict `>` keeps X-404 silent, and
    without a screen X-405 has nothing to combine with staleness."""
    run, _ = build([position(invested=10.0 / cfg.exceptions.moic.monitor_above, latest_round=date(2024, 6, 15))], [])
    c = only(run)
    assert c.moic_after == pytest.approx(5.0)
    assert flag_ids(c) == {"X-201"}
    _assert_monitor_only(c)


def test_moic_just_above_5x_on_stale_round_is_x404_and_x405(build):
    run, _ = build([position(invested=1.99, latest_round=date(2024, 6, 15))], [])
    c = only(run)
    f = _flag(c, "X-404")
    assert f.severity == Severity.MONITOR and f.evidence["moic"] == pytest.approx(round(10.0 / 1.99, 2))
    assert f.evidence["months"] == 27.5
    _assert_review_shape(c, "X-405")


def test_moic_above_5x_on_fresh_round_does_not_fire_x404(build):
    """X-404 is a *stale-round* screen: a 10× MOIC on a 15-month-old round is not flagged."""
    run, _ = build([position(invested=1.0)], [])
    _assert_clean(only(run))


# ============================================================================= 3. X-405

STALE = date(2024, 6, 15)   # 27.5 months before 2026-09-30: past monitor (24), short of review (48)


def test_x405_precondition_stale_alone_is_only_x201(build, cfg):
    run, _ = build([position(latest_round=STALE)], [])
    c = only(run)
    assert months_between(STALE, _md(cfg)) == 27.5
    assert flag_ids(c) == {"X-201"}
    _assert_monitor_only(c)


@pytest.mark.parametrize("screen, overrides, phrase", [
    ("X-401", dict(arr=2.0), "carried above the multiple screen"),          # 100 / 2 = 50×
    ("X-402", dict(arr=50.0), "carried below the multiple screen"),         # 100 / 50 = 2×
    ("X-404", dict(invested=1.0), "an outsized unrealised gain"),           # 10 / 1 = 10×
    ("X-301", dict(arr_growth=-0.05), "revenue now shrinking"),
])
def test_x405_fires_for_stale_round_plus_each_screen(build, screen, overrides, phrase):
    """'A mark that no longer squares with performance': stale (>24 months) plus any one of
    the four MONITOR screens is one REVIEW finding, X-405, naming the screen that fired."""
    run, _ = build([position(latest_round=STALE, **overrides)], [])
    c = only(run)
    assert _flag(c, screen).severity == Severity.MONITOR
    assert _flag(c, "X-201").severity == Severity.MONITOR
    f = _assert_review_shape(c, "X-405")
    assert f.evidence["screens"] == [screen] and f.evidence["months"] == 27.5
    assert phrase in f.message and any(phrase in p for p in f.points)
    assert c.disposition == Disposition.REVIEW and c.proposed_mark == 10.0
    assert {s.key for s in f.suggestions} >= {"as_proposed", "to_cost"}
    assert "calibrate" not in {s.key for s in f.suggestions}, "no M-080 alternative without live comps → dropped"


def test_x405_lists_every_screen_that_fired(build):
    run, _ = build([position(latest_round=STALE, arr=2.0, arr_growth=-0.05, invested=1.0)], [])
    c = only(run)
    f = _assert_review_shape(c, "X-405")
    assert f.evidence["screens"] == ["X-401", "X-404", "X-301"]


def test_x405_does_not_fire_when_x302_already_reviews(build):
    """Exclusion 1 (exceptions.py `ids & {"X-302", "X-202"}`): a REVIEW on growth already
    stops the position; X-405 would double-count it."""
    run, _ = build([position(latest_round=STALE, arr=2.0, arr_growth=-0.30)], [])
    c = only(run)
    assert "X-405" not in flag_ids(c)
    assert {"X-201", "X-401", "X-302"} <= flag_ids(c)
    _assert_review_shape(c, "X-302")
    assert c.disposition == Disposition.REVIEW


def test_x405_does_not_fire_when_x202_already_reviews(build, cfg):
    """Exclusion 2: past 48 months X-202 is the REVIEW; X-405 stands down."""
    very_stale = date(2022, 6, 15)
    assert months_between(very_stale, _md(cfg)) > cfg.exceptions.staleness.review_months
    run, _ = build([position(latest_round=very_stale, arr=2.0)], [])
    c = only(run)
    assert "X-405" not in flag_ids(c) and "X-201" not in flag_ids(c)
    assert {"X-202", "X-401"} <= flag_ids(c)
    _assert_review_shape(c, "X-202")
    assert c.disposition == Disposition.REVIEW


def test_x405_does_not_fire_on_a_fresh_round(build):
    """The same screens on a 15-month-old round are MONITOR only: nothing to argue with yet."""
    run, _ = build([position(arr=2.0, arr_growth=-0.05)], [])
    c = only(run)
    assert flag_ids(c) == {"X-401", "X-301"}
    _assert_monitor_only(c)


def test_x405_with_x304_escalates_to_block_disposition_but_readiness_is_review(build, cfg):
    """Two REVIEW families (valuation + liquidity) hit `review_rules_to_block`: the disposition
    escalates to BLOCK. Readiness stays Needs Review — nothing is *missing*, the reviewer just
    has two things to decide."""
    assert cfg.exceptions.escalation.review_rules_to_block == 2
    run, _ = build([position(latest_round=STALE, arr=2.0, net_burn=1.0, cash=4.0)], [])
    c = only(run)
    _assert_review_shape(c, "X-405")
    _assert_review_shape(c, "X-304")
    assert c.disposition == Disposition.BLOCK and c.readiness == Readiness.NEEDS_REVIEW


# ============================================================================= 4. missing metrics

def test_missing_arr_is_silent(build):
    """arr=None on a no-activity company: the multiple screens (X-401/402/403) are skipped,
    implied_multiple is None, multiple_exposed False. No crash, nothing fires, Ready. Sensible
    for the screens, but note that a blank ARR also means the 'mark vs performance' test can
    never run for this company (POLICY QUESTION: should a missing metric be a MONITOR?)."""
    run, issues = build([position(arr=None)], [])
    c = only(run)
    assert issues == [] and c.arr is None and c.implied_multiple is None and c.multiple_exposed is False
    assert c.proposed_mark == 10.0 and rule_ids(c) == ["M-000"]
    _assert_clean(c)


def test_missing_arr_growth_does_not_read_as_shrinking(build):
    """arr_growth=None: X-301/X-302 are skipped (`if g is not None`). A blank cell is not a
    decline. The multiple screen still runs and omits the growth clause from its text."""
    run, issues = build([position(arr_growth=None)], [])
    c = only(run)
    assert issues == [] and c.arr_growth is None
    assert "X-301" not in flag_ids(c) and "X-302" not in flag_ids(c)
    _assert_clean(c)


def test_missing_arr_growth_with_stale_round_and_high_multiple_still_reaches_x405(build):
    """X-405 must not depend on growth being present: stale + X-401 with growth blank fires
    and the message simply omits the growth clause."""
    run, _ = build([position(latest_round=STALE, arr=2.0, arr_growth=None)], [])
    c = only(run)
    f = _assert_review_shape(c, "X-405")
    assert "growing" not in f.message and f.evidence["screens"] == ["X-401"]


def test_zero_burn_does_not_read_as_short_runway(build):
    """net_burn=0: `Position.runway_months` is None (breakeven), so X-303/X-304 are skipped
    and runway_months_aged is None. Zero burn is not zero runway."""
    run, issues = build([position(net_burn=0.0)], [])
    c = only(run)
    assert issues == [] and c.runway_months_aged is None
    assert "X-303" not in flag_ids(c) and "X-304" not in flag_ids(c)
    _assert_clean(c)


def test_missing_cash_is_silent(build):
    """cash=None: runway cannot be computed; nothing fires. (The cached sheet runway cell is
    '-' and X-908 does not compare against a blank.)"""
    run, issues = build([position(cash=None)], [])
    c = only(run)
    assert issues == [] and c.runway_months_aged is None
    assert "X-303" not in flag_ids(c) and "X-304" not in flag_ids(c)
    _assert_clean(c)


def test_negative_burn_is_cash_generative_not_short_runway(build):
    """net_burn=-0.5 (the company makes money): runway_months is None because burn <= 0, so no
    liquidity flag and no negative-runway arithmetic. Sensible: a cash-generative company has
    no runway problem."""
    run, issues = build([position(net_burn=-0.5)], [])
    c = only(run)
    assert issues == [] and c.runway_months_aged is None
    assert "X-303" not in flag_ids(c) and "X-304" not in flag_ids(c)
    _assert_clean(c)


def test_all_metrics_blank_still_screens_staleness(build):
    """Every operating metric blank on a stale round: staleness is a date test and still fires;
    nothing else does and nothing crashes."""
    run, issues = build([position(arr=None, arr_growth=None, gross_margin=None, net_burn=None, cash=None, headcount=None,
                                  latest_round=STALE)], [])
    c = only(run)
    assert issues == [] and flag_ids(c) == {"X-201"}
    _assert_monitor_only(c)


def test_all_metrics_blank_on_a_very_stale_round_is_still_x202_review(build):
    """'Impossible to miss': the 48-month REVIEW does not need a single metric to be present."""
    run, _ = build([position(arr=None, arr_growth=None, net_burn=None, cash=None, latest_round=date(2022, 6, 15))], [])
    c = only(run)
    f = _assert_review_shape(c, "X-202")
    assert flag_ids(c) == {"X-202"} and f.evidence["months"] == 51.5


# ============================================================================= 5. finding shape (cross-cutting)

@pytest.mark.parametrize("overrides, rule_id", [
    (dict(latest_round=date(2022, 6, 15)), "X-202"),
    (dict(arr_growth=-0.30), "X-302"),
    (dict(net_burn=1.0, cash=4.0), "X-304"),
    (dict(latest_round=STALE, arr=2.0), "X-405"),
])
def test_every_carry_side_review_is_complete_and_priced(build, overrides, rule_id):
    """Each REVIEW the assessment names (stale, shrinking, short runway, mark vs performance)
    carries an action, 2-3 points, and suggestions whose booked values are numbers the
    reviewer can accept as-is."""
    run, _ = build([position(**overrides)], [])
    c = only(run)
    f = _assert_review_shape(c, rule_id)
    assert all(isinstance(s.booked, float) and s.booked >= 0 for s in f.suggestions)
    assert any(s.key == "as_proposed" and s.booked == pytest.approx(c.proposed_mark) for s in f.suggestions)
    assert f.suggestions[0].key == "as_proposed", "the first suggestion is the proposal itself"


@pytest.mark.parametrize("overrides, rule_id", [
    (dict(latest_round=STALE), "X-201"),
    (dict(arr_growth=-0.05), "X-301"),
    (dict(net_burn=1.0, cash=10.0), "X-303"),
    (dict(latest_post_money=400.0, invested=20.0), "X-401"),
    (dict(latest_post_money=20.0, invested=1.0), "X-402"),
    (dict(arr=0.2), "X-403"),
    (dict(invested=1.0, latest_round=STALE), "X-404"),
])
def test_every_monitor_is_ready_and_tagged(build, overrides, rule_id):
    run, _ = build([position(**overrides)], [])
    c = only(run)
    assert rule_id in flag_ids(c)
    # X-404 on a stale round necessarily brings X-405 along; that case is covered above
    if rule_id != "X-404":
        _assert_monitor_only(c)
    else:
        assert _flag(c, "X-404").severity == Severity.MONITOR and c.monitor is True
