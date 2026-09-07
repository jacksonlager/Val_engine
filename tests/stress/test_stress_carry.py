"""Stress tests: positions with NO quarterly activity — the majority of any book.

The assessment: "unchanged positions carry, and the judgment lives in the exceptions: stale
rounds and companies whose performance has moved away from their last mark." Two failure
directions, both tested here:

* a carry escalated for no reason (a baseless Needs Review / Blocked) wastes the committee's
  attention;
* a carry that should be escalated and is not (a MISSED exception) is the failure the product
  exists to prevent.

Part 1 builds synthetic single-position books from `conftest.position()` (clean on every
screen) and changes exactly one thing. Part 2 walks every no-activity company in the real Q3
2026 workbook and checks the same invariants on the book the committee will actually see.

Conventions established (see the report):

* A no-activity carry is exactly one `M-000` step with no `evidence`, `proposed_mark ==
  prior_mark`, `action == Carry`.
* Readiness and disposition are separate axes: two REVIEW *families* make the disposition
  BLOCK (policy `review_rules_to_block: 2`) but the readiness stays `Needs Review` — Blocked
  is reserved for missing-input rules and provisional marks.
* An unexplained prior-mark departure (X-904 on the Portfolio row) reaches the position as an
  **X-900** BLOCK flag whose `validation` evidence names X-904; the rule id X-904 itself never
  appears on `CompanyResult.flags`.

DEFECTS (xfail strict): none outstanding.
* D1 (fixed) — X-304 on zero cash used to print a negative runway ("About -1.0 months of cash
  left"); the aged runway is now floored at zero before it reaches the reviewer's sentence and
  the flag's evidence. `CompanyResult.runway_months_aged` still carries the raw aged figure.

POLICY QUESTIONS (asserted as actual behaviour):
* P1 — X-405 escalates any round older than 24 months that also trips a MONITOR screen, however
  marginal the screen: a 25-month round at 30.3× against an absolute bound of 30× is REVIEW.
* P2 — a term sheet opened in the last weeks of the prior quarter is E-07 REVIEW at the very
  next close (`term_sheet_stale_quarters: 1`, `age >= limit`).
* P3 — the X-900 action for an unexplained X-904 says "correct the cell"; when the departure is
  a legitimate prior-quarter override the fix is to explain it in the sidecar, which the flag
  does not mention.
* P4 — ARR exactly on the $0.5M floor is screened (strict `<`), so a $0.5M company with a normal
  post-money can be flagged X-401 where a $0.49M one is X-403.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from conftest import ROOT, flag_ids, only, position, rule_ids
from hc_valuation.engine.inputs import Status
from hc_valuation.engine.marking import months_between
from hc_valuation.engine.models import (
    Disposition, MarketData, MarketQuote, OpenItem, OpenItemKind, Readiness, SectorComp, Severity, ValuationAction,
)
from hc_valuation.rationale import rationale_by_id

MD = date(2026, 9, 30)

# Rule ids that can legitimately appear on a company with no activity this quarter.
CARRY_SIDE_RULES = frozenset({
    "X-201", "X-202", "X-301", "X-302", "X-303", "X-304",
    "X-401", "X-402", "X-403", "X-404", "X-405",
    "X-113", "X-904", "E-01", "E-07",
})
# ... plus the one wrapper the engine actually emits for a refused Portfolio row (X-904 inside).
CARRY_SIDE_RULES_AS_EMITTED = CARRY_SIDE_RULES | {"X-900"}


# ----------------------------------------------------------------------------- helpers

def _flag(c, rule_id: str):
    hits = [f for f in c.flags if f.rule_id == rule_id]
    assert hits, f"{rule_id} not raised; have {sorted(flag_ids(c))}"
    assert len(hits) == 1, f"{rule_id} raised {len(hits)} times"
    return hits[0]


def _assert_carried(c, *, action: ValuationAction = ValuationAction.CARRY):
    """The shape of a quiet quarter: one M-000 step, nothing event-driven, the mark unchanged."""
    assert rule_ids(c)[:1] == ["M-000"], rule_ids(c)
    assert all(s.rule_id in ("M-000", "M-080") for s in c.steps), rule_ids(c)
    assert all(s.evidence is None for s in c.steps), "a carry has no event evidence"
    assert c.proposed_mark == pytest.approx(c.prior_mark)
    assert c.booked_mark == pytest.approx(c.prior_mark)
    assert c.action == action
    assert c.realized_quarter == 0.0 and c.new_investment_quarter == 0.0


def _assert_clean(c):
    _assert_carried(c)
    assert c.flags == (), [(f.rule_id, f.severity.value) for f in c.flags]
    assert c.readiness == Readiness.READY
    assert c.disposition == Disposition.CLEAR
    assert c.monitor is False


def _assert_monitor_only(c, *ids: str):
    _assert_carried(c)
    assert flag_ids(c) == set(ids), sorted(flag_ids(c))
    assert all(f.severity == Severity.MONITOR for f in c.flags), [(f.rule_id, f.severity.value) for f in c.flags]
    assert all(f.action == "" for f in c.flags), "MONITOR flags carry no action by design"
    assert c.readiness == Readiness.READY
    assert c.disposition == Disposition.MONITOR
    assert c.monitor is True


def _assert_needs_review(c, review_id: str, *monitor_ids: str):
    _assert_carried(c)
    assert flag_ids(c) == {review_id, *monitor_ids}, sorted(flag_ids(c))
    f = _flag(c, review_id)
    assert f.severity == Severity.REVIEW
    assert f.action.strip() and 2 <= len(f.points) <= 3 and f.suggestions
    for m in monitor_ids:
        assert _flag(c, m).severity == Severity.MONITOR
    assert c.readiness == Readiness.NEEDS_REVIEW
    assert c.disposition == Disposition.REVIEW
    assert c.monitor is bool(monitor_ids)
    return f


def _live_comps(sector: str = "SaaS", *, round_month: str, then: float = 10.0, now: float = 12.0) -> MarketData:
    """A live comps history covering the round month, so M-080 can price the calibrate option."""
    return MarketData(comp_history={sector: {round_month: then, "2026-09": now}},
                      comps={sector: SectorComp(sector=sector, ev_to_arr=now, as_of=MD, source="live:test")}, as_of=MD)


def _no_activity(c) -> bool:
    return not any(s.evidence is not None for s in c.steps)


# ============================================================================ Part 1: synthetic

# ---- 1. a healthy position carries in silence

def test_healthy_position_carries_with_zero_findings(build):
    run, issues = build([position()], [])
    c = only(run)
    _assert_clean(c)
    assert rule_ids(c) == ["M-000"]
    assert c.steps[0].prior_value == c.steps[0].new_value == pytest.approx(10.0)
    assert "No activity" in c.steps[0].rationale
    assert not [i for i in issues if i.blocking], issues
    assert run.totals.readiness["Ready"] == 1 and run.totals.monitor_positions == 0


# ---- 2. staleness alone

def test_25_month_round_is_monitor_only_and_ready(build):
    run, _ = build([position(latest_round=date(2024, 8, 15))], [])       # 25.5 months at 30 Sep
    c = only(run)
    _assert_monitor_only(c, "X-201")
    assert _flag(c, "X-201").evidence["months"] == 25.5


def test_49_month_round_is_review_without_calibrate_when_no_live_comps(build):
    run, _ = build([position(latest_round=date(2022, 8, 15))], [])       # 49.5 months
    c = only(run)
    f = _assert_needs_review(c, "X-202")
    assert rule_ids(c) == ["M-000"], "no M-080 step without a live history"
    assert c.alternative_marks == {}
    keys = [s.key for s in f.suggestions]
    assert "calibrate" not in keys, "a calibrate option with no number behind it must not be offered"
    assert keys == ["as_proposed"]
    assert "49.5 months" in f.action


def test_49_month_round_offers_calibrate_when_live_comps_cover_the_round_month(build):
    market = _live_comps(round_month="2022-08", then=10.0, now=12.0)
    run, _ = build([position(latest_round=date(2022, 8, 15))], [], market=market)
    c = only(run)
    f = _assert_needs_review(c, "X-202")
    assert rule_ids(c) == ["M-000", "M-080"]
    assert c.alternative_marks["calibrated_to_comps"] == pytest.approx(12.0)
    cal = {s.key: s for s in f.suggestions}["calibrate"]
    assert cal.booked == pytest.approx(12.0), "the calibrate suggestion books the M-080 alternative"
    assert c.proposed_mark == pytest.approx(10.0), "the alternative never touches the proposal"


# ---- 3. terminal at the prior close: no carry-side screens, ever again

@pytest.mark.parametrize("status", ["Acquired", "Shut Down"])
def test_terminal_at_prior_close_is_never_rescreened(build, status):
    run, issues = build([position(status=status, prior_mark=0.0, realized=20.0,
                                  latest_round=date(2021, 1, 1),          # 69 months stale
                                  arr_growth=-0.60, cash=0.0, net_burn=1.0, arr=0.2)], [])
    c = only(run)
    assert c.status_before == c.status_after == Status(status)
    assert rule_ids(c) == ["M-000"] and c.steps[0].evidence is None
    assert c.prior_mark == c.proposed_mark == c.booked_mark == 0.0
    assert c.flags == (), [(f.rule_id, f.severity.value) for f in c.flags]
    assert c.readiness == Readiness.READY
    assert c.disposition == Disposition.CLEAR
    assert c.monitor is False
    assert c.action == ValuationAction.CARRY, "an exit in a prior quarter is not an exit again"
    assert c.realized_quarter == 0.0 and c.realized_cumulative == pytest.approx(20.0)
    assert run.totals.written_off == 0.0 and run.totals.exited_at_prior_mark == 0.0
    assert run.totals.active_after == 0
    assert not [i for i in issues if i.blocking], issues


# ---- 4. listed positions

def _public(**kw):
    return position(stage="Public", latest_post_money=500.0, ownership=0.05, arr=None, arr_growth=None, **kw)


def test_listed_no_quote_is_blocked_by_x113_and_names_what_is_missing(build):
    run, _ = build([_public()], [])
    c = only(run)
    assert c.listed and c.fv_level == 1
    assert rule_ids(c) == ["M-000"] and c.steps[0].inputs.get("quote") is None
    assert c.proposed_mark == pytest.approx(25.0) == c.prior_mark
    assert c.action == ValuationAction.CARRY
    f = _flag(c, "X-113")
    assert f.severity == Severity.BLOCK
    assert flag_ids(c) == {"X-113"}, "no staleness / MOIC screens on a listed name"
    assert c.readiness == Readiness.BLOCKED and c.disposition == Disposition.BLOCK
    # Blocked via the X-113 missing-input rule, NOT via the provisional path: the prior mark is
    # carried as a number, not stood in for by a listing-day cap.
    assert c.provisional is False and c.provisional_reason is None
    assert "30 Sep 2026" in f.action and "market cap" in f.action.lower()
    assert "re-run" in f.action.lower()
    assert [s.key for s in f.suggestions] == ["hold_prior"]
    assert f.suggestions[0].booked == pytest.approx(25.0)


def test_listed_with_quote_is_remarked_to_ownership_times_cap_and_ready(build):
    market = MarketData(quotes={"Alpha": MarketQuote(company="Alpha", market_cap_musd=600.0, as_of=MD, source="test:close")},
                        as_of=MD)
    run, _ = build([_public()], [], market=market)
    c = only(run)
    assert rule_ids(c) == ["M-041"] and c.steps[0].evidence is None
    assert c.prior_mark == pytest.approx(25.0) and c.proposed_mark == pytest.approx(30.0)
    assert c.latest_post_money == 600.0 and c.staleness_anchor == MD and c.fv_level == 1
    assert c.flags == () and c.readiness == Readiness.READY and c.disposition == Disposition.CLEAR
    assert c.action == ValuationAction.CARRY, "M-041 is a carry at the close, not a revaluation event"
    assert c.provisional is False
    assert c.valuation_change_quarter == pytest.approx(5.0)


# ---- 5. multiple screens: the floor, and a fresh price beats a screen

def test_arr_on_the_floor_is_screened_and_just_below_is_x403(build):
    # ARR exactly $0.5M with a $10M post: 20× — screened, inside bounds, nothing fires.
    run, _ = build([position(arr=0.5, latest_post_money=10.0, ownership=0.10)], [])
    c = only(run)
    _assert_clean(c)
    assert c.implied_multiple == pytest.approx(20.0)
    # P4: the same company at $0.5M with the default $100M post is 200× and X-401, not X-403.
    run, _ = build([position(arr=0.5)], [])
    _assert_monitor_only(only(run), "X-401")
    # Just below the floor: X-403 only, and no multiple is computed.
    run, _ = build([position(arr=0.49)], [])
    c = only(run)
    _assert_monitor_only(c, "X-403")
    assert c.implied_multiple is None


def test_high_multiple_on_a_fresh_round_is_monitor_only(build):
    run, _ = build([position(arr=2.0)], [])                                # 50× on a 15-month round
    c = only(run)
    _assert_monitor_only(c, "X-401")
    f = _flag(c, "X-401")
    assert f.evidence["basis"] == "absolute policy bound" and f.evidence["implied_multiple"] == 50.0


def test_same_multiple_on_a_25_month_round_is_x405_review(build):
    run, _ = build([position(arr=2.0, latest_round=date(2024, 8, 15))], [])
    c = only(run)
    f = _assert_needs_review(c, "X-405", "X-201", "X-401")
    assert f.evidence["screens"] == ["X-401"] and f.evidence["months"] == 25.5
    assert "50× revenue" in f.message
    keys = [s.key for s in f.suggestions]
    assert keys == ["as_proposed", "to_cost"], "calibrate is dropped when M-080 wrote no alternative"
    assert {s.key: s.booked for s in f.suggestions}["to_cost"] == pytest.approx(5.0)


def test_one_percent_contraction_on_a_25_month_round_is_x405_review(build):
    """P1: the X-405 composition has no margin — the mildest X-301 (−1%) on the youngest stale
    round (25 months) is a REVIEW. Asserted as actual behaviour; see the policy question."""
    run, _ = build([position(arr_growth=-0.01, latest_round=date(2024, 8, 15))], [])
    c = only(run)
    f = _assert_needs_review(c, "X-405", "X-201", "X-301")
    assert f.evidence["screens"] == ["X-301"]
    assert "revenue now shrinking" in f.message and "-1%" in f.message


def test_stale_round_with_tight_runway_stays_monitor(build):
    """P5: X-303 (6–12 months of cash) is not one of the screens X-405 composes with, so a
    30-month-old price on a company with 8 months of cash is Ready. Liquidity is not
    'performance moving away from the mark' in this policy."""
    run, _ = build([position(latest_round=date(2024, 3, 15), cash=4.5, net_burn=0.5)], [])   # 9 - 1 = 8 months
    c = only(run)
    _assert_monitor_only(c, "X-201", "X-303")
    assert c.runway_months_aged == pytest.approx(8.0)


# ---- 6. a prior mark that departs from ownership × post

def test_unexplained_prior_mark_departure_blocks_via_x900_wrapping_x904(build):
    run, issues = build([position(prior_mark=12.0)], [])                  # book says 10.0
    c = only(run)
    _assert_carried(c)
    assert c.proposed_mark == pytest.approx(12.0), "the book is never silently edited"
    assert [i.rule_id for i in issues if i.blocking] == ["X-904"]
    assert flag_ids(c) == {"X-900"}, "X-904 reaches the position wrapped in X-900"
    f = _flag(c, "X-900")
    assert f.severity == Severity.BLOCK and f.evidence["validation"] == ["X-904"]
    assert c.readiness == Readiness.BLOCKED and c.disposition == Disposition.BLOCK
    assert "X-904" in f.action and "Portfolio tab" in f.action
    assert "12.00" in f.message and "10.00" in f.message, "the message shows both numbers"
    # P3: the action says correct the cell; the alternative fix (explain the departure) is not offered.
    assert "explain" not in f.action.lower() and "sidecar" not in f.message.lower()


def test_explained_prior_mark_departure_carries_quietly(build):
    run, issues = build([position(prior_mark=12.0)], [], explained={"Alpha": "committee override, Q2 2026"})
    c = only(run)
    _assert_clean(c)
    assert c.proposed_mark == pytest.approx(12.0)
    x904 = [i for i in issues if i.rule_id == "X-904"]
    assert len(x904) == 1 and x904[0].severity == Severity.REVIEW and not x904[0].blocking
    assert "committee override" in x904[0].message


# ---- 7. blanks on a stale round

def test_all_metrics_blank_on_a_30_month_round_is_x201_only(build):
    run, _ = build([position(latest_round=date(2024, 3, 15), arr=None, arr_growth=None, cash=None, net_burn=None)], [])
    c = only(run)
    _assert_monitor_only(c, "X-201")
    # X-405 needs a screen hit (X-401/402/404/301) and every screen needs a metric — growth,
    # ARR, or a MOIC over 5× — so blank metrics on an old price stay MONITOR. That is the
    # policy's stance: staleness alone is not evidence of a move.
    assert c.implied_multiple is None and c.runway_months_aged is None and c.arr_growth is None
    assert c.moic_after == pytest.approx(2.0)


# ---- 8. MOIC outlier

def test_moic_6x_on_a_20_month_round_is_nothing(build):
    run, _ = build([position(invested=1.6, latest_round=date(2025, 1, 15))], [])   # 6.25×, 20.5 months
    c = only(run)
    _assert_clean(c)
    assert c.moic_after == pytest.approx(6.25)


def test_moic_6x_on_a_30_month_round_is_x404_and_x405(build):
    run, _ = build([position(invested=1.6, latest_round=date(2024, 3, 15))], [])   # 30.5 months
    c = only(run)
    f = _assert_needs_review(c, "X-405", "X-201", "X-404")
    assert _flag(c, "X-404").evidence["moic"] == pytest.approx(6.25)
    assert f.evidence["screens"] == ["X-404"]
    assert "outsized unrealised gain" in f.message


# ---- 9. runway

def test_cash_generative_company_has_no_runway_finding(build):
    run, _ = build([position(cash=0.1, net_burn=-0.5)], [])
    c = only(run)
    _assert_clean(c)
    assert c.runway_months_aged is None


def test_zero_cash_with_burn_is_x304_review(build):
    """fixed: zero cash is still X-304 REVIEW; the flag's aged runway is floored at 0."""
    run, _ = build([position(cash=0.0, net_burn=0.5)], [])
    c = only(run)
    f = _assert_needs_review(c, "X-304")
    assert c.runway_months_aged == pytest.approx(-1.0)
    assert f.evidence["runway_months_aged"] == pytest.approx(0.0)
    assert {s.key: s.booked for s in f.suggestions} == {"as_proposed": pytest.approx(10.0), "to_cost": pytest.approx(5.0)}


def test_zero_cash_runway_is_not_described_as_negative_months(build):
    """fixed: the reviewer reads 'About 0.0 months of cash', never a negative number."""
    run, _ = build([position(cash=0.0, net_burn=0.5)], [])
    f = _flag(only(run), "X-304")
    assert "-1.0 months" not in f.message and "-1.0-month" not in f.action and "-1.0 months" not in f.action
    assert not any("-1.0" in p for p in f.points)
    assert "About 0.0 months of cash" in f.message
    assert f.action == "Confirm the mark reflects a company with 0.0 months of cash."
    assert f.severity is Severity.REVIEW


# ---- 10. a prior open item on a quiet position

def test_prior_term_sheet_ages_and_escalates_on_a_quiet_position(build):
    item = OpenItem(company="Alpha", kind=OpenItemKind.TERM_SHEET, opened=date(2026, 6, 20), opened_quarter="Q2 2026",
                    amount_musd=150.0, detail="Term sheet at $150M post from Outside Ventures")
    run, _ = build([position()], [], prior_open_items=[item])
    c = only(run)
    f = _assert_needs_review(c, "E-07")
    assert len(c.open_items) == 1
    aged = c.open_items[0]
    assert aged.age_quarters == 1 and aged.escalated is True, "P2: one quarter is the whole allowance"
    assert f.evidence == {"kind": "term_sheet", "age_quarters": 1, "opened": "2026-06-20"}
    assert "term sheet" in f.message and "2026-06-20" in f.message and "1 quarter(s)" in f.message
    assert "Outside Ventures" in f.message, "the item's own detail is quoted"
    assert f.action == "Chase the term sheet, or reflect the delay in the mark."
    assert not any("term_sheet" in p for p in f.points), "plain words, not the enum value"
    assert run.open_items == c.open_items


def test_prior_open_item_for_another_company_is_ignored(build):
    item = OpenItem(company="Nobody", kind=OpenItemKind.TERM_SHEET, opened=date(2026, 5, 1), opened_quarter="Q2 2026")
    run, _ = build([position()], [], prior_open_items=[item])
    _assert_clean(only(run))


# ============================================================================ Part 2: the real run

@pytest.fixture(scope="module")
def quiet(run_real):
    """Every company the Q3 workbook carries with no activity row applied."""
    qs = [c for c in run_real.companies if _no_activity(c)]
    assert qs, "the real workbook has no quiet positions?"
    return qs


def _age(c, cfg) -> float:
    return months_between(c.staleness_anchor, cfg.quarter.measurement_date)


def test_real_quiet_positions_carry_one_m000_step(quiet):
    for c in quiet:
        assert rule_ids(c) == ["M-000"], (c.company, rule_ids(c))
        assert c.proposed_mark == pytest.approx(c.prior_mark), c.company
        assert c.action == ValuationAction.CARRY, (c.company, c.action)
        assert c.provisional is False, c.company
        assert c.realized_quarter == 0.0 and c.new_investment_quarter == 0.0, c.company


def test_real_quiet_unready_positions_carry_only_carry_side_rules_and_an_action(quiet):
    unready = [c for c in quiet if c.readiness != Readiness.READY]
    assert unready, "expected some quiet positions to need a reviewer"
    surprises = {}
    for c in unready:
        ids = flag_ids(c)
        extra = ids - CARRY_SIDE_RULES_AS_EMITTED
        if extra:
            surprises[c.company] = sorted(extra)
        gates = [f for f in c.flags if f.severity in (Severity.BLOCK, Severity.REVIEW)]
        assert gates, (c.company, "unready with no BLOCK/REVIEW flag?")
        for f in gates:
            assert f.action.strip(), (c.company, f.rule_id, "no action on a gating flag")
            assert 2 <= len(f.points) <= 3, (c.company, f.rule_id)
    assert surprises == {}, f"non-carry-side rules on quiet positions: {surprises}"


def test_real_quiet_unready_positions_pinned(quiet):
    """The exact Needs Review set on the pinned workbook, so a change in the escalation set is
    a visible diff rather than a silent one (the golden test pins the same run)."""
    got = {c.company: sorted(flag_ids(c)) for c in quiet if c.readiness != Readiness.READY}
    assert all(c.readiness == Readiness.NEEDS_REVIEW for c in quiet if c.readiness != Readiness.READY), \
        "no quiet position should be Blocked on this workbook"
    assert got == {
        "Arcfoundry": ["X-201", "X-401", "X-405"],
        "Beltrix": ["X-201", "X-304"],
        "Birchhollow": ["X-202", "X-302"],
        "Brumewell": ["X-201", "X-302"],
        "Foxtrellis": ["X-201", "X-401", "X-404", "X-405"],
        "Jupelan": ["X-201", "X-304"],
        "Juttermill": ["X-202", "X-402"],
        "Knollward": ["X-202"],
        "Mardellan": ["X-202", "X-404"],
        "Mirthstone": ["X-201", "X-301", "X-405"],
        "Nettlebay": ["X-202"],
        "Orchardline": ["X-304"],
        "Ostrella": ["X-202"],
        "Petrelbay": ["X-302", "X-401"],
        "Pinwhistle": ["X-201", "X-401", "X-405"],
        "Quarrystone AI": ["X-302"],
        "Stonegather": ["X-201", "X-304"],
        "Umberly": ["X-201", "X-304"],
        "Uplandreach": ["X-202"],
        "Yarrowbank": ["X-201", "X-402", "X-405"],
    }


def test_real_quiet_ready_positions_have_no_missed_exception(quiet, cfg):
    """A Ready quiet position must be inside every REVIEW line: runway, growth, staleness."""
    x = cfg.exceptions
    missed = []
    for c in quiet:
        if c.readiness != Readiness.READY:
            continue
        if c.status_before != Status.ACTIVE:
            continue   # terminal at the prior close: no screens apply (tested in Part 1)
        if c.runway_months_aged is not None and c.runway_months_aged < x.runway.review_below_mo:
            missed.append((c.company, "runway", c.runway_months_aged))
        if c.arr_growth is not None and c.arr_growth < x.arr_growth.review_below:
            missed.append((c.company, "growth", c.arr_growth))
        if not c.listed and _age(c, cfg) > x.staleness.review_months:
            missed.append((c.company, "staleness", _age(c, cfg)))
    assert missed == [], f"MISSED exceptions on Ready quiet positions: {missed}"


def test_real_quiet_ready_positions_are_monitor_or_clear_only(quiet):
    for c in quiet:
        if c.readiness == Readiness.READY:
            assert all(f.severity == Severity.MONITOR for f in c.flags), (c.company, sorted(flag_ids(c)))
            assert c.disposition in (Disposition.CLEAR, Disposition.MONITOR), (c.company, c.disposition)
            assert c.monitor is bool(c.flags), c.company


def test_real_quiet_terminal_at_prior_close_carry_clear(quiet):
    dead = [c for c in quiet if c.status_before != Status.ACTIVE]
    assert len(dead) == 4, [c.company for c in dead]
    for c in dead:
        assert c.flags == () and c.readiness == Readiness.READY and c.disposition == Disposition.CLEAR, c.company
        assert c.prior_mark == c.proposed_mark == 0.0 and c.action == ValuationAction.CARRY, c.company


def test_real_x405_only_escalations(quiet):
    """Quiet positions Needs Review solely because X-405 composed a stale price with a MONITOR
    screen. Each one is listed with the screen; see P1 in the module docstring."""
    solely = {}
    for c in quiet:
        reviews = {f.rule_id for f in c.flags if f.severity == Severity.REVIEW}
        if reviews == {"X-405"}:
            f = _flag(c, "X-405")
            solely[c.company] = (tuple(f.evidence["screens"]), f.evidence["months"], c.implied_multiple, c.arr_growth)
    assert solely == {
        "Arcfoundry": (("X-401",), 34.7, 30.29, 2.7),
        "Foxtrellis": (("X-401", "X-404"), 35.5, 32.56, 1.03),
        "Mirthstone": (("X-301",), 34.7, 4.71, -0.05),
        "Pinwhistle": (("X-401",), 33.4, 31.32, 0.51),
        "Yarrowbank": (("X-402",), 32.9, 1.03, 0.85),
    }
    for c in quiet:
        if c.company in solely:
            assert c.readiness == Readiness.NEEDS_REVIEW and c.disposition == Disposition.REVIEW
            assert _flag(c, "X-405").action.startswith("Affirm or reprice")


def test_real_quiet_readiness_split_and_top_review_rules(quiet):
    split = Counter(c.readiness.value for c in quiet)
    assert split == {"Ready": 62, "Needs Review": 20}
    assert split.get("Blocked", 0) == 0
    behind = Counter(f.rule_id for c in quiet if c.readiness == Readiness.NEEDS_REVIEW
                     for f in c.flags if f.severity == Severity.REVIEW)
    assert behind == {"X-202": 7, "X-304": 5, "X-405": 5, "X-302": 4}
    assert [r for r, _ in behind.most_common(3)] == ["X-202", "X-304", "X-405"]


def test_real_two_review_families_block_the_disposition_but_not_the_readiness(quiet, cfg):
    """Birchhollow: X-202 (staleness) + X-302 (growth) = two REVIEW families → disposition BLOCK,
    readiness Needs Review. The two axes disagree by design; the queue must read readiness."""
    assert cfg.exceptions.escalation.review_rules_to_block == 2
    b = next(c for c in quiet if c.company == "Birchhollow")
    assert flag_ids(b) == {"X-202", "X-302"}
    assert b.disposition == Disposition.BLOCK and b.readiness == Readiness.NEEDS_REVIEW
    assert not any(f.severity == Severity.BLOCK for f in b.flags)


def test_every_rule_on_a_quiet_position_has_a_plain_name(quiet):
    names = rationale_by_id(ROOT)
    seen = {f.rule_id for c in quiet for f in c.flags}
    for rid in sorted(seen):
        assert rid in names, f"{rid} has no rationale entry"
        assert names[rid].get("name") and names[rid].get("why_flag") and names[rid].get("why_severity"), rid
