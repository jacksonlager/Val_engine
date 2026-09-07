"""Stress tests: overlapping, conflicting and malformed activity.

The assessment says the quarter "deliberately includes activity that takes judgment, not just
mechanics" and that the engine must "make the exceptions impossible to miss". Every test here
builds one clean position (`conftest.position()`: 10% of a $100M round, prior mark $10M) and
feeds it two or more rows that overlap, contradict each other, or are malformed, and asserts:

* no exception is raised;
* which steps applied (rule ids in order) and the resulting proposed mark;
* which rows were refused (X-900, naming the row), skipped (superseded), suppressed (after a
  terminal event) or applied;
* the findings — rule id, severity, and that every REVIEW / BLOCK carries a non-empty action,
  points and suggestions;
* readiness and disposition;
* that a refused or unapplied row NEVER moves the mark silently.

Tests marked `xfail(strict=True, reason="DEFECT: ...")` assert the behaviour the assessment
asks for and document where the engine departs from it. The six defects this file originally
found (terminal contradictions, X-923 corrected readings, X-123 stake-up-without-cheque, blank
dates, provisional IPO prints, M-999 as a missing input) are FIXED; the tests that pinned the
old behaviour now assert the corrected one and say "fixed:" in their docstrings.
Debatable-but-defensible behaviour is asserted as observed and listed under POLICY QUESTIONS
in the report.

Row numbering: the activity sheet's header is row 1, so the first event row is 2.
"""
from __future__ import annotations

from datetime import date

import pytest

from conftest import event, flag_ids, only, position, rule_ids
from hc_valuation.engine.inputs import EventType, Status
from hc_valuation.engine.models import Disposition, Readiness, Severity, ValuationAction
from hc_valuation.engine.readiness import MISSING_INPUT_RULES

R = EventType.PRICED_ROUND
MD = date(2026, 9, 30)
PRIOR = 10.0   # conftest.position(): 0.10 × $100M


# ----------------------------------------------------------------------------- helpers

def _flag(c, rule_id: str, severity: Severity | None = None):
    hits = [f for f in c.flags if f.rule_id == rule_id and (severity is None or f.severity == severity)]
    assert hits, f"{rule_id} ({severity}) not raised; have {[(f.rule_id, f.severity.value) for f in c.flags]}"
    assert len(hits) == 1, f"{rule_id} raised {len(hits)} times"
    return hits[0]


def _assert_actionable(c) -> None:
    """Every REVIEW / BLOCK finding says what to do, why (1-3 points) and offers a resolution;
    every MONITOR finding carries none of that — the state.py contract, checked on the output."""
    for f in c.flags:
        if f.severity is Severity.MONITOR:
            assert not f.action and not f.points and not f.suggestions, f"{f.rule_id}: MONITOR must be context only"
        else:
            assert f.action.strip(), f"{f.rule_id}: {f.severity.value} without an action"
            assert 1 <= len(f.points) <= 3 and all(p.strip() for p in f.points), f"{f.rule_id}: bad points {f.points}"
            assert f.suggestions, f"{f.rule_id}: {f.severity.value} without a suggestion"
            for s in f.suggestions:
                assert s.label.strip() and len(s.reasons) == 2 and all(s.reasons), f"{f.rule_id}/{s.key}: bad suggestion"
                assert s.booked >= 0.0


def _refused(c) -> dict[int, list[str]]:
    """row_index -> validation ids, for every 'recorded but not applied' step that refused a row."""
    return {s.inputs["row_index"]: list(s.inputs["validation"]) for s in c.steps if "refused_event" in s.inputs}


def _skipped(c) -> list[int]:
    return [s.inputs["row_index"] for s in c.steps if "skipped_event" in s.inputs]


def _suppressed(c) -> list[int]:
    return [s.inputs["row_index"] for s in c.steps if "suppressed_event" in s.inputs]


def _applied_rows(c) -> list[int]:
    return [s.evidence.row_index for s in c.steps
            if s.evidence is not None and not ({"refused_event", "skipped_event", "suppressed_event"} & set(s.inputs))]


def _assert_refused_never_moves_mark(c, row: int, ids: list[str]) -> None:
    """A refused row: recorded as an M-000 step at prior == new, X-900 BLOCK naming the row and
    the validation ids, readiness Blocked, X-900 on the missing-input list."""
    assert _refused(c).get(row) == sorted(ids), f"row {row} not refused with {ids}: {_refused(c)}"
    step = next(s for s in c.steps if s.inputs.get("row_index") == row and "refused_event" in s.inputs)
    assert step.rule_id == "M-000" and step.prior_value == step.new_value
    assert step.evidence is not None and step.evidence.row_index == row
    assert "not applied" in step.rationale and "carried unchanged" in step.rationale
    x900 = [f for f in c.flags if f.rule_id == "X-900" and f.evidence.get("row_index") == row]
    assert len(x900) == 1, f"X-900 must name row {row} once; have {[f.evidence for f in c.flags if f.rule_id == 'X-900']}"
    f = x900[0]
    assert f.severity is Severity.BLOCK and f.family == "data" and f.evidence["sheet"] == "activity"
    assert f.evidence["validation"] == sorted(ids)
    assert f"row {row}" in f.action and all(i in f.action for i in ids)
    assert f"**{row}**" in f.points[0]
    assert [s.key for s in f.suggestions] == ["hold_prior"] and f.suggestions[0].booked == pytest.approx(c.prior_mark)
    assert "X-900" in MISSING_INPUT_RULES
    assert c.readiness is Readiness.BLOCKED and c.disposition is Disposition.BLOCK


def _assert_contradiction_never_moves_mark(c, row: int, why_fragment: str) -> None:
    """A row that cannot be true beside the position's own history (fixed: a financing dated after
    this quarter's exit): an M-000 'suppressed' step naming the contradiction, X-900 BLOCK naming
    the row, readiness Blocked. Nothing on the row is booked."""
    steps = [s for s in c.steps if "suppressed_event" in s.inputs and s.inputs.get("row_index") == row]
    assert len(steps) == 1, f"row {row} not suppressed once: {[s.inputs for s in c.steps]}"
    step = steps[0]
    assert step.rule_id == "M-000" and step.prior_value == step.new_value
    assert set(step.inputs) == {"suppressed_event", "row_index", "contradiction"}
    assert why_fragment in step.inputs["contradiction"] and why_fragment in step.rationale
    assert "not applied" in step.rationale and "carried unchanged" in step.rationale
    assert step.evidence is not None and step.evidence.row_index == row
    x900 = [f for f in c.flags if f.rule_id == "X-900" and f.evidence.get("row_index") == row]
    assert len(x900) == 1, f"X-900 must name row {row} once; have {[f.evidence for f in c.flags if f.rule_id == 'X-900']}"
    f = x900[0]
    assert f.severity is Severity.BLOCK and f.family == "data" and f.evidence["sheet"] == "activity"
    assert "validation" not in f.evidence, "a contradiction is the engine's own finding, not an ingest id"
    assert f"row {row}" in f.action and why_fragment in f.action and "contradicts" in f.message
    assert f"**{row}**" in f.points[0] and "contradicts the position" in f.points[0]
    assert [s.key for s in f.suggestions] == ["hold_prior"] and f.suggestions[0].booked == pytest.approx(c.prior_mark)
    assert c.readiness is Readiness.BLOCKED and c.disposition is Disposition.BLOCK


def _assert_x923(c, row: int, ids: list[str]) -> None:
    """fixed: a row applied on a reading ingest had to correct (X-916 unit reinterpretation, X-905
    inside the grace period) surfaces on the position as X-923 REVIEW naming the row and the ids."""
    f = _flag(c, "X-923", Severity.REVIEW)
    assert f.family == "data"
    assert f.evidence["sheet"] == "activity" and f.evidence["row_index"] == row and f.evidence["validation"] == sorted(ids)
    assert f"Row {row}" in f.message and "corrected reading" in f.message and all(i in f.message for i in ids)
    assert f"row {row}" in f.action and all(i in f.action for i in ids)
    assert f"**{row}**" in f.points[0] and "corrected reading" in f.points[0]
    assert [s.key for s in f.suggestions] == ["as_proposed", "hold_prior"]
    assert f.suggestions[0].booked == pytest.approx(c.proposed_mark) and f.suggestions[1].booked == pytest.approx(c.prior_mark)
    assert "X-923" not in MISSING_INPUT_RULES, "a reading to confirm is a judgment, not a missing input"


def _issue_ids(issues, row: int | None = None) -> list[str]:
    return sorted(i.rule_id for i in issues if row is None or i.row_index == row)


# =============================================================================== 1. two priced rounds

def _two_rounds(reverse: bool):
    rows = [event(R, date=date(2026, 7, 10), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=1.0),
            event(R, date=date(2026, 9, 10), detail="Series C", value=400.0, ownership_after=0.085, hc_investment=2.0)]
    return list(reversed(rows)) if reverse else rows


@pytest.mark.parametrize("reverse", [False, True], ids=["chronological", "reversed-on-sheet"])
def test_two_priced_rounds_last_dated_sets_the_mark_whatever_the_sheet_order(build, reverse):
    run, issues = build([position()], _two_rounds(reverse))
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-010", "M-010"]
    # applied in date order: the July round first, whichever row it sits on
    assert [s.evidence.date for s in c.steps] == [date(2026, 7, 10), date(2026, 9, 10)]
    assert _applied_rows(c) == ([3, 2] if reverse else [2, 3])
    assert c.steps[0].prior_value == PRIOR and c.steps[0].new_value == pytest.approx(18.0)
    assert c.steps[1].prior_value == pytest.approx(18.0) and c.steps[1].new_value == pytest.approx(34.0)
    assert c.steps[1].inputs["prior_post_money"] == 200.0, "the second round is compared against the first, not the book"
    assert c.proposed_mark == pytest.approx(0.085 * 400.0) == pytest.approx(34.0)
    assert c.ownership_after == 0.085 and c.invested_after == pytest.approx(8.0)
    assert c.latest_post_money == 400.0 and c.staleness_anchor == date(2026, 9, 10) and c.stage == "Series C"
    assert c.action is ValuationAction.REVALUE
    assert c.new_investment_quarter == pytest.approx(3.0)
    assert not _refused(c) and not _skipped(c) and not _suppressed(c)
    # 40× ARR on the new price: a watch item, not a gate
    assert flag_ids(c) == {"X-401"} and _flag(c, "X-401").severity is Severity.MONITOR
    assert c.readiness is Readiness.READY and c.disposition is Disposition.MONITOR
    _assert_actionable(c)


def test_two_priced_rounds_reversed_sheet_order_is_identical_to_chronological(build):
    a, _ = build([position()], _two_rounds(False))
    b, _ = build([position()], _two_rounds(True))
    ca, cb = only(a), only(b)
    same = ("proposed_mark", "booked_mark", "ownership_after", "invested_after", "latest_post_money", "staleness_anchor",
            "stage", "readiness", "disposition", "action", "fv_level", "alternative_marks", "open_items")
    for attr in same:
        assert getattr(ca, attr) == getattr(cb, attr), attr
    assert [(s.rule_id, s.prior_value, s.new_value, s.evidence.date) for s in ca.steps] == \
           [(s.rule_id, s.prior_value, s.new_value, s.evidence.date) for s in cb.steps]
    assert [(f.rule_id, f.severity) for f in ca.flags] == [(f.rule_id, f.severity) for f in cb.flags]
    assert a.totals.proposed_nav == b.totals.proposed_nav


# =============================================================================== 2. round + secondary / term sheet / announced

def _same_day(reverse: bool):
    rows = [event(EventType.SECONDARY, date=date(2026, 8, 15), detail="Sold block", value=200.0, ownership_after=0.07, proceeds=4.0),
            event(R, date=date(2026, 8, 15), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=1.0)]
    return list(reversed(rows)) if reverse else rows


@pytest.mark.parametrize("reverse", [False, True], ids=["secondary-first-on-sheet", "round-first-on-sheet"])
def test_priced_round_and_secondary_on_the_same_day(build, reverse):
    """POLICY QUESTION. Same-date ties are broken by tier (higher tier number first), so a secondary
    (tier 4) applies BEFORE a priced round (tier 3) dated the same day. The engine is deterministic —
    sheet order does not matter — but the round's `ownership_after` (9%) then overwrites the
    post-sale stake (7%), so HC ends the quarter owning 9% after realizing $4M for a 3% block, and
    X-119 reads HC's $1M cheque as buying 2% (7% → 9%) at an implied $50M post. Round-first would
    give 7% × $200M = $14M with no X-119. Both readings are surfaced (REVIEW), neither is silent."""
    run, issues = build([position()], _same_day(reverse))
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-030", "M-010"], "tie broken by tier, not by sheet order"
    sec_row, rnd_row = (3, 2) if reverse else (2, 3)
    assert _applied_rows(c) == [sec_row, rnd_row]
    assert c.steps[0].prior_value == PRIOR and c.steps[0].new_value == pytest.approx(7.0)      # 7% × $100M (old price)
    assert c.steps[0].inputs["implied_post_money"] == 200.0 and c.steps[0].inputs["last_round_post_money"] == 100.0
    assert c.steps[1].prior_value == pytest.approx(7.0) and c.steps[1].new_value == pytest.approx(18.0)
    assert c.steps[1].inputs["ownership_before"] == 0.07 and c.steps[1].inputs["implied_post_from_hc_cheque"] == pytest.approx(50.0)
    assert c.proposed_mark == pytest.approx(18.0) and c.ownership_after == 0.09
    assert c.realized_quarter == pytest.approx(4.0) and c.invested_after == pytest.approx(6.0)
    assert c.action is ValuationAction.PARTIAL_EXIT
    assert flag_ids(c) == {"X-104", "X-119"}
    x104 = _flag(c, "X-104", Severity.REVIEW)
    assert x104.evidence["spread"] == pytest.approx(1.0), "secondary priced against the pre-round $100M"
    x119 = _flag(c, "X-119", Severity.REVIEW)
    assert x119.evidence["implied_post_from_hc_cheque"] == pytest.approx(50.0) and x119.evidence["ownership_delta"] == pytest.approx(0.02)
    assert c.alternative_marks == {"at_secondary_price": pytest.approx(14.0)}
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.REVIEW
    _assert_actionable(c)


def test_priced_round_then_term_sheet_keeps_the_pending_item_open(build):
    """A term sheet signed after a real price: the round sets the mark, the term sheet is measured
    against the NEW price and disclosed as a pending item — it does not move the mark."""
    run, issues = build([position()], [
        event(R, date=date(2026, 7, 15), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=1.0),
        event(EventType.TERM_SHEET, date=date(2026, 9, 15), detail="Series C term sheet", value=300.0),
    ])
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-010", "M-070"] and _applied_rows(c) == [2, 3]
    assert c.steps[1].prior_value == c.steps[1].new_value == pytest.approx(18.0)
    assert c.steps[1].inputs["indicated_post_money"] == 300.0 and c.steps[1].inputs["indicated_mark"] == pytest.approx(27.0)
    assert c.proposed_mark == pytest.approx(18.0) and c.latest_post_money == 200.0
    assert c.staleness_anchor == date(2026, 7, 15), "the term sheet is not price discovery"
    assert flag_ids(c) == {"X-109"}
    x109 = _flag(c, "X-109", Severity.MONITOR)
    assert x109.evidence["ratio_to_last_round"] == pytest.approx(1.5), "compared with the round that just closed, not the book"
    assert [(i.kind.value, i.amount_musd) for i in c.open_items] == [("term_sheet", 300.0)]
    assert c.alternative_marks == {"term_sheet_indicated": pytest.approx(27.0)}
    assert c.readiness is Readiness.READY and c.disposition is Disposition.MONITOR and c.action is ValuationAction.REVALUE
    _assert_actionable(c)


def test_term_sheet_then_announced_acquisition_both_items_stay_open(build):
    """POLICY QUESTION: a signed acquisition supersedes a financing term sheet in substance, but the
    engine keeps both open items (RESOLVES only covers prior-quarter items). The mark is the PWERM
    deal value and BLOCKS for ratification."""
    run, issues = build([position()], [
        event(EventType.TERM_SHEET, date=date(2026, 7, 15), detail="Series B term sheet", value=150.0),
        event(EventType.ACQ_ANNOUNCED, date=date(2026, 9, 1), detail="Definitive agreement", value=300.0,
              notes="Signed; regulatory approval pending"),
    ])
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-070", "M-050"] and _applied_rows(c) == [2, 3]
    assert c.steps[0].prior_value == c.steps[0].new_value == PRIOR
    assert c.steps[1].prior_value == PRIOR and c.steps[1].new_value == pytest.approx(0.9 * 30.0 + 0.1 * 10.0)
    assert c.proposed_mark == pytest.approx(28.0)
    assert flag_ids(c) == {"X-109", "X-101"}
    assert _flag(c, "X-109").severity is Severity.MONITOR
    x101 = _flag(c, "X-101", Severity.BLOCK)
    assert x101.evidence == {"deal_value": 300.0, "close_probability": 0.9, "treatment": "probability_weighted"}
    assert [s.key for s in x101.suggestions] == ["as_proposed", "full_value", "hold_prior"]
    assert [s.booked for s in x101.suggestions] == [pytest.approx(28.0), pytest.approx(30.0), pytest.approx(10.0)]
    assert [i.kind.value for i in c.open_items] == ["term_sheet", "pending_acquisition"]
    assert c.alternative_marks == {"term_sheet_indicated": pytest.approx(15.0), "at_full_deal_value": pytest.approx(30.0),
                                   "hold_prior": pytest.approx(10.0), "probability_weighted": pytest.approx(28.0)}
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.BLOCK
    assert "X-101" not in MISSING_INPUT_RULES, "a signed deal is a judgment, not a missing input"
    _assert_actionable(c)


# =============================================================================== 3. acquisitions

def test_announced_then_terminated_in_the_quarter_skips_the_announcement(build):
    run, issues = build([position()], [
        event(EventType.ACQ_ANNOUNCED, date=date(2026, 7, 15), detail="Definitive agreement", value=300.0),
        event(EventType.ACQ_TERMINATED, date=date(2026, 9, 1), detail="Buyer walked"),
    ])
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-000", "M-051"]
    assert _skipped(c) == [2] and _applied_rows(c) == [3] and not _refused(c)
    skipped = c.steps[0]
    assert skipped.prior_value == skipped.new_value == PRIOR and "superseded by its termination" in skipped.rationale
    assert c.steps[1].prior_value == c.steps[1].new_value == PRIOR, "nothing to revert: the announcement never applied"
    assert c.proposed_mark == PRIOR and c.open_items == () and c.action is ValuationAction.CARRY
    assert flag_ids(c) == {"X-114"}
    x114 = _flag(c, "X-114", Severity.REVIEW)
    assert x114.evidence["reverted_to"] == PRIOR and x114.evidence["from_mark"] == PRIOR
    # the 'hold the deal-based mark' suggestion books the same $10M and is deduplicated away
    assert [s.key for s in x114.suggestions] == ["as_proposed"]
    assert c.alternative_marks == {"hold_deal_based": PRIOR}
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.REVIEW
    _assert_actionable(c)


def test_termination_dated_before_the_announcement_is_not_a_supersession(build):
    """POLICY QUESTION. A termination dated BEFORE the announcement (dates swapped, or a prior deal
    breaking before a new one is signed) is applied as M-051 on a position with no pending deal —
    X-114 then reads 'the mark has gone back to the last round at $10.00M from $10.00M' — and the
    later announcement applies on top. Nothing is silent (BLOCK), but the X-114 finding is misleading."""
    run, issues = build([position()], [
        event(EventType.ACQ_TERMINATED, date=date(2026, 7, 15), detail="Buyer walked"),
        event(EventType.ACQ_ANNOUNCED, date=date(2026, 9, 1), detail="Definitive agreement", value=300.0),
    ])
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-051", "M-050"] and _applied_rows(c) == [2, 3] and not _skipped(c)
    assert c.steps[0].prior_value == c.steps[0].new_value == PRIOR
    assert c.proposed_mark == pytest.approx(28.0)
    assert flag_ids(c) == {"X-114", "X-101"}
    assert _flag(c, "X-114").severity is Severity.REVIEW and _flag(c, "X-101").severity is Severity.BLOCK
    assert [i.kind.value for i in c.open_items] == ["pending_acquisition"]
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.BLOCK
    _assert_actionable(c)


@pytest.mark.parametrize("proceeds", [None, 0.0], ids=["proceeds-blank", "proceeds-zero"])
def test_closed_acquisition_with_no_cash_blocks_but_still_writes_to_zero(build, proceeds):
    """POLICY QUESTION: blank proceeds (missing input) and zero proceeds (a stated wipe-out) are
    treated identically — mark to zero, status Acquired, X-101 BLOCK, readiness Needs Review
    (not Blocked: X-101 is not on the missing-input list)."""
    run, issues = build([position()], [event(EventType.ACQ_CLOSED, detail="All-cash", value=300.0, proceeds=proceeds)])
    c = only(run)
    assert issues == [], "a closed exit with no proceeds is legal at ingest (a wipe-out)"
    assert rule_ids(c) == ["M-020"] and _applied_rows(c) == [2]
    assert c.steps[0].prior_value == PRIOR and c.steps[0].new_value == 0.0
    assert c.steps[0].inputs["proceeds"] == 0.0 and c.steps[0].inputs["implied_from_deal_value"] == pytest.approx(30.0)
    assert c.proposed_mark == 0.0 and c.realized_quarter == 0.0 and c.status_after is Status.ACQUIRED
    assert c.action is ValuationAction.FULL_EXIT and c.fv_level is None
    assert flag_ids(c) == {"X-101"}
    x101 = _flag(c, "X-101", Severity.BLOCK)
    assert "no cash" in x101.message and "escrow" in x101.action
    assert [(s.key, s.booked) for s in x101.suggestions] == [("hold_prior", PRIOR), ("write_to_zero", 0.0)]
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.BLOCK
    assert c.valuation_change_quarter == pytest.approx(-10.0)
    _assert_actionable(c)


@pytest.mark.parametrize("proceeds,flagged", [
    (30.0, False), (30.5, False), (30.51, True), (29.49, True), (45.0, True), (100.0, True),
], ids=["exact", "gap=tolerance", "gap>tolerance", "short>tolerance", "far-above", "3x-above"])
def test_closed_acquisition_proceeds_vs_ownership_times_deal_value_tolerance(build, cfg, proceeds, flagged):
    """X-101 REVIEW when |ownership × deal value − proceeds| > 10 × prior_mark_reconciliation_musd
    ($0.5M absolute, not a percentage). Either direction; the cash is realized either way."""
    tol = cfg.tolerances.prior_mark_reconciliation_musd * 10
    assert tol == pytest.approx(0.5)
    run, issues = build([position()], [event(EventType.ACQ_CLOSED, detail="All-cash", value=300.0, proceeds=proceeds)])
    c = only(run)
    assert issues == [] and rule_ids(c) == ["M-020"]
    assert c.proposed_mark == 0.0 and c.realized_quarter == pytest.approx(proceeds) and c.status_after is Status.ACQUIRED
    assert (abs(30.0 - proceeds) > tol) == flagged
    if flagged:
        assert flag_ids(c) == {"X-101"}
        x101 = _flag(c, "X-101", Severity.REVIEW)
        assert x101.evidence == {"implied": pytest.approx(30.0), "proceeds": pytest.approx(proceeds)}
        assert f"{abs(30.0 - proceeds):.2f}M" in x101.action
        assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.REVIEW
        keys = [s.key for s in x101.suggestions]
        # 'carry the gap as an escrow receivable' only makes sense when cash fell SHORT of the deal value
        assert keys == (["as_proposed", "carry_gap"] if proceeds < 30.0 else ["as_proposed"])
    else:
        assert c.flags == () and c.readiness is Readiness.READY and c.disposition is Disposition.CLEAR
    _assert_actionable(c)


# =============================================================================== 4. IPO

def test_ipo_then_secondary_sale_of_part_of_the_stake(build):
    run, issues = build([position()], [
        event(EventType.IPO, date=date(2026, 7, 20), detail="Nasdaq IPO", value=1000.0, ownership_after=0.08),
        event(EventType.SECONDARY, date=date(2026, 9, 10), detail="Sold block post-IPO", value=1100.0, ownership_after=0.06, proceeds=22.0),
    ])
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-040", "M-030"] and _applied_rows(c) == [2, 3]
    assert c.steps[0].prior_value == PRIOR and c.steps[0].new_value == pytest.approx(80.0)
    assert c.steps[0].inputs["price_source"] == "ipo_print", "no measurement-date quote: the listing-day cap stands in"
    assert c.steps[1].prior_value == pytest.approx(80.0) and c.steps[1].new_value == pytest.approx(60.0)
    assert c.steps[1].inputs["last_round_post_money"] == 1000.0 and c.steps[1].inputs["implied_post_money"] == 1100.0
    assert c.proposed_mark == pytest.approx(0.06 * 1000.0) == pytest.approx(60.0)
    assert c.ownership_after == 0.06 and c.realized_quarter == pytest.approx(22.0)
    assert c.listed and c.fv_level == 1 and c.stage == "Public" and c.status_after is Status.ACTIVE
    assert c.action is ValuationAction.PARTIAL_EXIT
    assert flag_ids(c) == {"X-101", "X-104", "X-401"}
    x101 = _flag(c, "X-101", Severity.BLOCK)
    assert "none is on file" in x101.action and x101.evidence["price_source"] == "ipo_print"
    x104 = _flag(c, "X-104", Severity.REVIEW)
    assert x104.evidence["spread"] == pytest.approx(0.1)
    assert [i.kind.value for i in c.open_items] == ["ipo_lockup"]
    assert c.alternative_marks == {"at_ipo_print": pytest.approx(80.0), "at_secondary_price": pytest.approx(66.0)}
    assert c.provisional and c.readiness is Readiness.BLOCKED, "the stand-in print is a missing input, whatever the secondary says"
    assert c.disposition is Disposition.BLOCK
    _assert_actionable(c)


def test_ipo_with_no_measurement_date_quote_is_provisional_and_blocked(build):
    """fixed: M-040's own finding says the listing-day cap 'stands in for the close until the actual
    price is confirmed', and the real workbook's Drayvenn is Blocked+provisional for exactly this
    reason. With no quote at all (`price_source` 'ipo_print') the same missing input now yields the
    same answer: provisional, the reason in the reviewer's words, readiness Blocked on X-101."""
    run, _ = build([position()], [event(EventType.IPO, date=date(2026, 7, 20), detail="Nasdaq IPO", value=1000.0, ownership_after=0.08)])
    c = only(run)
    assert c.steps[0].inputs["price_source"] == "ipo_print"
    assert c.provisional and c.provisional_reason and "closing price" in c.provisional_reason
    assert "30 Sep 2026" in c.provisional_reason and "$1,000M" in c.provisional_reason
    assert c.proposed_mark == pytest.approx(80.0)
    assert _flag(c, "X-101").severity is Severity.BLOCK, "X-101 is the provisional rule"
    assert c.readiness is Readiness.BLOCKED and c.disposition is Disposition.BLOCK
    _assert_actionable(c)


def test_ipo_with_no_market_cap_is_refused_and_carried(build):
    run, issues = build([position()], [event(EventType.IPO, date=date(2026, 7, 20), detail="Nasdaq IPO", ownership_after=0.08)])
    c = only(run)
    assert _issue_ids(issues, 2) == ["X-902"] and issues[0].blocking
    assert rule_ids(c) == ["M-000", "M-000"] and _applied_rows(c) == []
    _assert_refused_never_moves_mark(c, 2, ["X-902"])
    assert "No activity could be applied" in c.steps[1].rationale
    assert c.proposed_mark == PRIOR and not c.listed and c.fv_level == 3 and c.stage == "Series A"
    assert c.open_items == () and c.alternative_marks == {}
    assert flag_ids(c) == {"X-900"} and c.action is ValuationAction.CARRY
    _assert_actionable(c)


# =============================================================================== 5. convertible notes

def test_convertible_note_then_priced_round_converts_the_note_leg(build):
    """The note leg does NOT survive: it converts into the round, the open item is dropped, and the
    mark is ownership_after × post with nothing added for the note (its cost sits in invested).
    The X-107 REVIEW raised at the note is settled by the conversion and replaced by X-124 (same
    severity): the reviewer confirms the conversion terms, not a bridge that no longer exists."""
    run, issues = build([position()], [
        event(EventType.CONVERTIBLE_NOTE, date=date(2026, 7, 10), detail="Bridge note, $150M cap", hc_investment=1.0),
        event(R, date=date(2026, 9, 10), detail="Series B", value=200.0, ownership_after=0.095, hc_investment=2.0),
    ])
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-060", "M-010"] and _applied_rows(c) == [2, 3]
    assert c.steps[0].prior_value == PRIOR and c.steps[0].new_value == pytest.approx(11.0)
    assert c.steps[0].inputs["valuation_cap"] == 150.0 and c.steps[0].inputs["cap_vs_last_round"] == pytest.approx(0.5)
    assert c.steps[1].prior_value == pytest.approx(11.0) and c.steps[1].new_value == pytest.approx(19.0)
    assert c.steps[1].inputs["note_converted"] == pytest.approx(1.0) and "note leg converts" in c.steps[1].rationale
    assert c.proposed_mark == pytest.approx(0.095 * 200.0) == pytest.approx(19.0)
    assert c.equity_mark == pytest.approx(19.0) and c.note_at_cost == 0.0
    assert c.invested_after == pytest.approx(8.0) and c.new_investment_quarter == pytest.approx(3.0)
    assert c.open_items == (), "the note item is resolved by the round"
    assert c.staleness_anchor == date(2026, 9, 10)
    assert flag_ids(c) == {"X-124"} and _flag(c, "X-124").severity is Severity.REVIEW
    assert _flag(c, "X-124").evidence["note_leg"] == pytest.approx(1.0)
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.REVIEW
    _assert_actionable(c)


def test_convertible_note_with_no_parsable_cap(build):
    run, issues = build([position()], [event(EventType.CONVERTIBLE_NOTE, detail="Bridge note", hc_investment=1.0)])
    c = only(run)
    assert issues == [] and rule_ids(c) == ["M-060"]
    assert c.steps[0].inputs["valuation_cap"] is None and c.steps[0].inputs["cap_vs_last_round"] is None
    assert c.proposed_mark == pytest.approx(11.0) and c.equity_mark == PRIOR and c.note_at_cost == pytest.approx(1.0)
    assert [(i.kind.value, i.amount_musd) for i in c.open_items] == [("convertible_note", 1.0)]
    assert flag_ids(c) == {"X-107", "X-101"}
    assert _flag(c, "X-107").severity is Severity.REVIEW
    x101 = _flag(c, "X-101", Severity.REVIEW)
    assert "by hand" in x101.action and x101.evidence == {"detail": "Bridge note"}
    # two REVIEWs in the same family stay REVIEW (escalation counts families)
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.REVIEW
    _assert_actionable(c)


def test_note_repaid_with_no_principal_and_no_proceeds(build):
    """POLICY QUESTION: a 'Note Repaid' row with nothing on it applies as a $0 repayment and still
    raises X-115 REVIEW ('confirm where the note sat') — the finding reads as if money moved."""
    run, issues = build([position()], [event(EventType.NOTE_REPAID, detail="Note repaid")])
    c = only(run)
    assert issues == [] and rule_ids(c) == ["M-061"]
    s = c.steps[0]
    assert s.prior_value == s.new_value == PRIOR
    assert s.inputs["proceeds"] == 0.0 and s.inputs["principal"] == 0.0 and s.inputs["principal_not_in_note_leg"] == 0.0
    assert c.proposed_mark == PRIOR and c.realized_quarter == 0.0 and c.note_at_cost == 0.0
    assert flag_ids(c) == {"X-115"}
    x115 = _flag(c, "X-115", Severity.REVIEW)
    assert [s.key for s in x115.suggestions] == ["as_proposed"]
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.REVIEW
    assert c.action is ValuationAction.REVALUE, "a $0 repayment is still counted as a revaluation"
    _assert_actionable(c)


def test_note_repaid_with_proceeds_but_no_note_leg_names_the_unmatched_principal(build):
    run, issues = build([position()], [event(EventType.NOTE_REPAID, detail="Note repaid", proceeds=1.0)])
    c = only(run)
    assert issues == [] and rule_ids(c) == ["M-061"]
    assert c.steps[0].inputs["principal"] == 1.0 and c.steps[0].inputs["principal_not_in_note_leg"] == 1.0
    assert c.proposed_mark == PRIOR and c.realized_quarter == pytest.approx(1.0)
    x115 = _flag(c, "X-115", Severity.REVIEW)
    assert [(s.key, s.booked) for s in x115.suggestions] == [("as_proposed", PRIOR), ("reduce_basis", pytest.approx(9.0))]
    assert c.readiness is Readiness.NEEDS_REVIEW
    _assert_actionable(c)


# =============================================================================== 6. malformed priced rounds

@pytest.mark.parametrize("kw,ids,fragment", [
    (dict(ownership_after=0.09, hc_investment=1.0), ["X-902"], "missing post-money"),
    (dict(value=0.0, ownership_after=0.09, hc_investment=1.0), ["X-903"], "must be greater than zero"),
    (dict(value=200.0, hc_investment=1.0), ["X-902"], "missing HC ownership after"),
    (dict(value=200.0, ownership_after=150.0, hc_investment=1.0), ["X-903"], "above 100"),
    (dict(value=-200.0, ownership_after=0.09, hc_investment=1.0), ["X-903"], "must be greater than zero"),
    (dict(hc_investment=1.0), ["X-902", "X-902"], "missing"),
], ids=["blank-post", "post-zero", "blank-ownership-after", "ownership-150", "negative-post", "blank-post-and-ownership"])
def test_malformed_priced_round_is_refused_and_the_prior_mark_is_carried(build, kw, ids, fragment):
    run, issues = build([position()], [event(R, detail="Series B", **kw)])
    c = only(run)
    assert _issue_ids(issues, 2) == sorted(ids) and all(i.blocking and i.severity is Severity.BLOCK for i in issues)
    assert any(fragment in i.message for i in issues)
    assert rule_ids(c) == ["M-000", "M-000"] and _applied_rows(c) == []
    _assert_refused_never_moves_mark(c, 2, sorted(set(ids)))
    assert c.proposed_mark == PRIOR and c.ownership_after == 0.10 and c.invested_after == 5.0
    assert c.latest_post_money == 100.0 and c.staleness_anchor == date(2025, 6, 15), "nothing from the row leaked"
    assert flag_ids(c) == {"X-900"} and c.action is ValuationAction.CARRY
    assert run.blocked
    _assert_actionable(c)


def test_ownership_after_in_percentage_points_is_reinterpreted_with_x916(build):
    """5.5 on the ownership column is read as 5.5% (0.055) with a non-blocking X-916 REVIEW on the
    run. The mark books on the reinterpreted cell: 10% → 5.5% at $200M = $11M."""
    run, issues = build([position()], [event(R, detail="Series B", value=200.0, ownership_after=5.5, hc_investment=1.0)])
    c = only(run)
    assert [(i.rule_id, i.severity, i.blocking, i.company, i.row_index) for i in issues] == [("X-916", Severity.REVIEW, False, "Alpha", 2)]
    assert "5.5" in issues[0].message and "0.055" in issues[0].message
    assert rule_ids(c) == ["M-010"] and c.steps[0].inputs["ownership_after"] == pytest.approx(0.055)
    assert c.proposed_mark == pytest.approx(11.0) and c.ownership_after == pytest.approx(0.055)
    assert flag_ids(c) == {"X-923"}, "fixed: the reinterpreted cell is a reading to confirm, not a clean row"
    _assert_x923(c, 2, ["X-916"])
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.REVIEW
    assert not run.blocked
    _assert_actionable(c)


@pytest.mark.parametrize("kw,issue", [
    (dict(ownership_after=5.5), "X-916"),
    (dict(ownership_after=0.09, date=date(2026, 6, 20)), "X-905"),
], ids=["x916-points-to-fraction", "x905-inside-grace"])
def test_review_validation_issue_on_the_row_surfaces_on_the_position(build, kw, issue):
    """fixed: a REVIEW ingest correction on the row the mark rests on (X-916 unit reinterpretation,
    X-905 inside the grace period) surfaces on the position as X-923 'Row applied on a corrected
    reading' — the row is applied, the mark moves, and a person confirms the reading."""
    run, issues = build([position()], [event(R, detail="Series B", value=200.0, hc_investment=1.0, **kw)])
    c = only(run)
    assert [i.rule_id for i in issues] == [issue] and issues[0].severity is Severity.REVIEW and issues[0].company == "Alpha"
    assert not issues[0].blocking and rule_ids(c) == ["M-010"] and _applied_rows(c) == [2] and not _refused(c)
    assert c.proposed_mark != PRIOR, "the reinterpreted / late row moved the mark"
    assert flag_ids(c) == {"X-923"}
    _assert_x923(c, 2, [issue])
    assert issues[0].message in _flag(c, "X-923").message, "the finding repeats ingest's own words"
    assert c.readiness is Readiness.NEEDS_REVIEW, "a REVIEW-severity issue on the row the mark rests on is a review item"
    assert c.disposition is Disposition.REVIEW and not run.blocked
    _assert_actionable(c)


def test_ownership_up_with_no_hc_investment_is_not_silently_booked(build):
    """fixed: ownership rising 10% -> 15% in a priced round with no HC cheque books +$20M — on the
    stated stake, as the row says — but raises X-123 REVIEW so a person confirms the mechanism
    (anti-dilution, ratchet, warrant, or a wrong cell) before it is booked."""
    run, issues = build([position()], [event(R, detail="Series B", value=200.0, ownership_after=0.15)])
    c = only(run)
    assert issues == [] and rule_ids(c) == ["M-010"]
    assert c.proposed_mark == pytest.approx(30.0) and c.invested_after == 5.0
    assert c.readiness is not Readiness.READY and c.flags, "a stake that grows without money needs a person"
    assert any(f.severity is not Severity.MONITOR and "ownership" in f.message.lower() for f in c.flags)


def test_ownership_up_with_no_hc_investment_raises_x123(build, cfg):
    """fixed: the corrected behaviour behind the test above, pinned so a change is noticed. The
    mark is still ownership_after × post (the row is the fund's own record); X-123 REVIEW offers
    the prior stake against the new post-money as the alternative."""
    delta = cfg.exceptions.indications.cheque_check_min_ownership_delta
    assert delta == pytest.approx(0.01) and 0.15 - 0.10 >= delta
    run, issues = build([position()], [event(R, detail="Series B", value=200.0, ownership_after=0.15)])
    c = only(run)
    assert issues == [] and rule_ids(c) == ["M-010"]
    assert c.proposed_mark == pytest.approx(30.0) and c.ownership_after == 0.15 and c.invested_after == 5.0
    assert flag_ids(c) == {"X-123"}
    x123 = _flag(c, "X-123", Severity.REVIEW)
    assert x123.family == "treatment"
    assert x123.evidence == {"ownership_before": pytest.approx(0.10), "ownership_after": pytest.approx(0.15), "relative_change": pytest.approx(0.5)}
    assert "10.0%" in x123.message and "15.0%" in x123.message and "did not fund" in x123.message
    assert "10.0%" in x123.action and "15.0%" in x123.action and "without a cheque" in x123.action
    assert [(s.key, s.booked) for s in x123.suggestions] == [("as_proposed", pytest.approx(30.0)), ("prior_stake", pytest.approx(20.0))]
    assert "X-123" not in MISSING_INPUT_RULES
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.REVIEW and c.action is ValuationAction.REVALUE
    assert not run.blocked
    _assert_actionable(c)


@pytest.mark.parametrize("after,flagged", [(0.10, False), (0.105, False), (0.115, True), (0.12, True)],
                         ids=["unchanged", "half-pt-below-delta", "half-pt-above-delta", "2pt-above"])
def test_x123_fires_at_the_cheque_check_ownership_delta(build, cfg, after, flagged):
    """fixed: X-123 uses the same ≥ 1pt threshold as the X-119 cheque check; a smaller rise is
    rounding and stays silent. (The exact 1pt boundary is not tested: 0.11 − 0.10 is a hair under
    0.01 in binary floating point, so it would pin an artefact, not the policy.)"""
    assert cfg.exceptions.indications.cheque_check_min_ownership_delta == pytest.approx(0.01)
    run, issues = build([position()], [event(R, detail="Series B", value=200.0, ownership_after=after)])
    c = only(run)
    assert issues == [] and rule_ids(c) == ["M-010"] and c.proposed_mark == pytest.approx(after * 200.0)
    assert (after - 0.10 >= 0.01) == flagged
    assert ("X-123" in flag_ids(c)) == flagged
    if not flagged:
        assert c.flags == () and c.readiness is Readiness.READY and c.disposition is Disposition.CLEAR
    _assert_actionable(c)


# =============================================================================== 7. dates

def test_event_dated_after_the_measurement_date_is_refused(build):
    run, issues = build([position()], [event(R, date=date(2026, 10, 2), detail="Series B", value=200.0, ownership_after=0.09)])
    c = only(run)
    assert _issue_ids(issues, 2) == ["X-905"] and issues[0].blocking and "after the measurement date" in issues[0].message
    assert rule_ids(c) == ["M-000", "M-000"]
    _assert_refused_never_moves_mark(c, 2, ["X-905"])
    assert c.proposed_mark == PRIOR and c.latest_post_money == 100.0 and c.staleness_anchor == date(2025, 6, 15)
    assert run.blocked
    _assert_actionable(c)


@pytest.mark.parametrize("when", [date(2026, 6, 30), date(2026, 6, 20), date(2026, 4, 1)],
                         ids=["day-before-window", "10-days-before", "exactly-grace-days-before"])
def test_event_before_the_window_inside_the_grace_period_is_applied_with_x905_review(build, cfg, when):
    assert cfg.tolerances.late_event_grace_days == 91 and (date(2026, 7, 1) - when).days <= 91
    run, issues = build([position()], [event(R, date=when, detail="Series B", value=200.0, ownership_after=0.09)])
    c = only(run)
    assert [(i.rule_id, i.severity, i.blocking) for i in issues] == [("X-905", Severity.REVIEW, False)]
    assert "missed at the last close" in issues[0].message
    assert rule_ids(c) == ["M-010"] and _applied_rows(c) == [2] and not _refused(c)
    assert c.proposed_mark == pytest.approx(18.0) and c.latest_post_money == 200.0
    assert c.staleness_anchor == when, "the clock runs from the round's own date, not the quarter"
    # fixed: the late row is applied, but on a reading a person has not confirmed — X-923, not CLEAR
    assert flag_ids(c) == {"X-923"}
    _assert_x923(c, 2, ["X-905"])
    assert c.readiness is Readiness.NEEDS_REVIEW and c.disposition is Disposition.REVIEW
    assert not run.blocked
    _assert_actionable(c)


@pytest.mark.parametrize("when", [date(2026, 3, 31), date(2026, 3, 20), date(2025, 12, 31)],
                         ids=["grace+1-day", "grace+12-days", "prior-year"])
def test_event_before_the_window_outside_the_grace_period_is_refused(build, when):
    assert (date(2026, 7, 1) - when).days > 91
    run, issues = build([position()], [event(R, date=when, detail="Series B", value=200.0, ownership_after=0.09)])
    c = only(run)
    assert _issue_ids(issues, 2) == ["X-905"] and issues[0].blocking and "more than 91 days" in issues[0].message
    assert rule_ids(c) == ["M-000", "M-000"]
    _assert_refused_never_moves_mark(c, 2, ["X-905"])
    assert c.proposed_mark == PRIOR and c.staleness_anchor == date(2025, 6, 15)
    _assert_actionable(c)


@pytest.mark.parametrize("bad_date,fragment", [(None, "Date is blank"), ("next Tuesday", "'next Tuesday'")],
                         ids=["blank", "unreadable-text"])
def test_event_with_a_blank_date_refuses_the_row_not_the_book(build, bad_date, fragment):
    """fixed: a blank or unreadable Date on one activity row no longer aborts ingest. The row gets a
    stand-in date (the measurement date), validate raises X-902 BLOCK on it, the engine refuses it
    with X-900, and the other company's clean row still rolls."""
    run, issues = build([position(), position(company="Beta")], [
        event(R, date=bad_date, detail="Series B", value=200.0, ownership_after=0.09),
        event(R, company="Beta", detail="Series B", value=300.0, ownership_after=0.09),
    ])
    c, beta = only(run), only(run, "Beta")
    assert [(i.rule_id, i.severity, i.blocking, i.company, i.row_index) for i in issues] == [("X-902", Severity.BLOCK, True, "Alpha", 2)]
    assert fragment in issues[0].message
    assert rule_ids(c) == ["M-000", "M-000"] and _applied_rows(c) == []
    _assert_refused_never_moves_mark(c, 2, ["X-902"])
    assert "2026-09-30" in c.steps[0].rationale, "the stand-in date is the measurement date, and it is only used to place the record"
    assert "No activity could be applied" in c.steps[1].rationale
    assert c.proposed_mark == PRIOR and c.latest_post_money == 100.0 and c.staleness_anchor == date(2025, 6, 15)
    assert flag_ids(c) == {"X-900"} and c.action is ValuationAction.CARRY
    assert beta.proposed_mark == pytest.approx(27.0) and rule_ids(beta) == ["M-010"], "the other company's clean row still rolls"
    assert "X-900" not in flag_ids(beta)
    assert run.blocked
    _assert_actionable(c)


# =============================================================================== 8. companies not on the book / duplicated

def test_event_for_a_company_not_on_the_portfolio_tab_is_x901_and_a_blocked_placeholder(build):
    """A name the book does not have is a question for a person: the row is refused (X-901) and a
    zero placeholder position carries the refusal as a Blocked card, so it is in the queue and not
    only in the data-checks drawer. Nothing is applied to it; the real book is untouched."""
    run, issues = build([position()], [event(R, company="Ghost", detail="Series B", value=200.0, ownership_after=0.09)])
    assert [(i.rule_id, i.severity, i.blocking, i.company, i.row_index) for i in issues] == [("X-901", Severity.BLOCK, True, "Ghost", 2)]
    assert [c.company for c in run.companies] == ["Alpha", "Ghost"]
    c = run.by_company()["Alpha"]
    assert rule_ids(c) == ["M-000"] and c.proposed_mark == PRIOR and c.flags == ()
    assert c.readiness is Readiness.READY and c.disposition is Disposition.CLEAR
    ghost = run.by_company()["Ghost"]
    assert ghost.readiness is Readiness.BLOCKED and flag_ids(ghost) == {"X-900"} and ghost.proposed_mark == 0.0 and ghost.invested_after == 0.0
    assert run.blocked, "the run blocks on the orphan row even though every real position is clean"
    assert run.totals.proposed_nav == pytest.approx(PRIOR)


def test_new_investment_for_a_company_not_on_the_portfolio_tab_is_x918_and_synthesised(build):
    run, issues = build([position()], [event(EventType.NEW_INVESTMENT, company="Ghost", detail="Seed, Fund II, SaaS",
                                             value=20.0, ownership_after=0.10, hc_investment=2.0)])
    assert [(i.rule_id, i.severity, i.blocking, i.company) for i in issues] == [("X-918", Severity.REVIEW, False, "Ghost")]
    assert "Fund II" in issues[0].message
    assert [c.company for c in run.companies] == ["Alpha", "Ghost"]
    g = only(run, "Ghost")
    assert rule_ids(g) == ["M-014"] and g.steps[0].inputs["position_created"] is True
    assert g.prior_mark == 0.0 and g.proposed_mark == pytest.approx(2.0) and g.invested_after == pytest.approx(2.0)
    assert g.fund == "Fund II" and g.sector == "SaaS" and g.stage == "Seed"
    assert g.action is ValuationAction.NEW_INVESTMENT and g.new_investment_quarter == pytest.approx(2.0)
    assert flag_ids(g) == {"X-120", "X-918"}
    assert _flag(g, "X-120").severity is Severity.MONITOR
    x918 = _flag(g, "X-918", Severity.REVIEW)
    assert x918.evidence["row_index"] == 2 and "Portfolio tab" in x918.action
    assert "X-918" in MISSING_INPUT_RULES
    assert g.readiness is Readiness.BLOCKED and g.disposition is Disposition.REVIEW, "a missing Portfolio row blocks booking; the finding itself is REVIEW"
    assert not run.blocked, "X-918 is non-blocking at the run level"
    assert only(run).proposed_mark == PRIOR
    _assert_actionable(g)


def test_same_company_twice_on_the_portfolio_tab_blocks_both_rows(build):
    """POLICY QUESTION: the priced round is applied to BOTH duplicate rows (each marks $18M) and both
    count in NAV ($36M); each is Blocked with an X-900 naming its own Portfolio row."""
    run, issues = build([position(), position()], [event(R, detail="Series B", value=200.0, ownership_after=0.09)])
    assert [(i.rule_id, i.sheet, i.row_index, i.blocking) for i in issues] == [("X-906", "Portfolio", 2, True), ("X-906", "Portfolio", 3, True)]
    assert [c.company for c in run.companies] == ["Alpha", "Alpha"]
    for c, book_row in zip(run.companies, (2, 3)):
        assert rule_ids(c) == ["M-010"] and c.proposed_mark == pytest.approx(18.0), "the book is rolled as it stands"
        x900 = _flag(c, "X-900", Severity.BLOCK)
        assert x900.evidence == {"sheet": "portfolio", "row_index": book_row, "validation": ["X-906"]}
        assert f"row {book_row} of the Portfolio tab" in x900.action and "X-906" in x900.action
        assert [s.key for s in x900.suggestions] == ["hold_prior"] and x900.suggestions[0].booked == PRIOR
        assert c.readiness is Readiness.BLOCKED and c.disposition is Disposition.BLOCK
        _assert_actionable(c)
    assert run.totals.proposed_nav == pytest.approx(36.0) and run.blocked


# =============================================================================== 9. already-terminal positions

TERMINAL = dict(prior_mark=0.0, ownership=0.0, invested=5.0, realized=20.0, arr=None, arr_growth=None, net_burn=None, cash=None)


def test_acquired_company_distribution_applies_and_priced_round_does_not(build):
    """fixed: the distribution still applies (cash after the exit moves realized and nothing else);
    the priced round is recorded against the position as a refused row — M-000 'not applied' naming
    row 2 and X-907, X-900 BLOCK, readiness Blocked — instead of vanishing from the chain."""
    run, issues = build([position(status="Acquired", **TERMINAL)], [
        event(R, date=date(2026, 7, 10), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=1.0),
        event(EventType.DISTRIBUTION, date=date(2026, 8, 10), detail="Escrow release", proceeds=2.0),
    ])
    c = only(run)
    assert [(i.rule_id, i.row_index, i.blocking) for i in issues] == [("X-907", 2, True)]
    assert rule_ids(c) == ["M-000", "M-000", "M-022"] and _applied_rows(c) == [3]
    assert "Already Acquired" in c.steps[0].rationale and c.steps[0].prior_value == c.steps[0].new_value == 0.0
    _assert_refused_never_moves_mark(c, 2, ["X-907"])
    assert c.steps[2].prior_value == c.steps[2].new_value == 0.0 and "after the exit" in c.steps[2].rationale
    assert c.proposed_mark == 0.0 and c.ownership_after == 0.0 and c.invested_after == 5.0, "nothing from the round leaked"
    assert c.realized_quarter == pytest.approx(2.0) and c.realized_cumulative == pytest.approx(22.0)
    assert c.status_after is Status.ACQUIRED and c.action is ValuationAction.CARRY
    assert flag_ids(c) == {"X-900", "X-111"} and _flag(c, "X-111").severity is Severity.MONITOR
    assert c.disposition is Disposition.BLOCK and c.readiness is Readiness.BLOCKED
    assert run.blocked, "the refused round blocks the run"
    _assert_actionable(c)


def test_priced_round_on_an_acquired_company_is_recorded_against_the_position(build):
    """fixed: a priced round on an already-Acquired company (X-907) is no longer dropped from the
    position's chain. It reaches the position as a refused row (the X-907 ingest issue is blocking,
    so it is refused before the terminal-contradiction check would catch it): an M-000 'not applied'
    step and an X-900 naming the row, and the card is Blocked."""
    run, issues = build([position(status="Acquired", **TERMINAL)], [
        event(R, date=date(2026, 7, 10), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=1.0),
        event(EventType.DISTRIBUTION, date=date(2026, 8, 10), detail="Escrow release", proceeds=2.0),
    ])
    c = only(run)
    assert _issue_ids(issues, 2) == ["X-907"]
    assert c.proposed_mark == 0.0 and c.invested_after == 5.0
    _assert_refused_never_moves_mark(c, 2, ["X-907"])
    assert not _suppressed(c), "a blocking ingest issue is refused (X-907), not suppressed as a contradiction"
    assert "already Acquired" in _flag(c, "X-900").message


def test_shut_down_company_note_repaid_applies_and_priced_round_does_not(build):
    """fixed: the note repayment applies on the terminal position; the priced round is refused
    against it (M-000 + X-900 naming row 3 and X-907) and the position is Blocked, not CLEAR."""
    run, issues = build([position(status="Shut Down", **{**TERMINAL, "realized": 1.0})], [
        event(EventType.NOTE_REPAID, date=date(2026, 8, 10), detail="Note repaid out of wind-down", proceeds=0.5),
        event(R, date=date(2026, 7, 10), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=1.0),
    ])
    c = only(run)
    assert [(i.rule_id, i.row_index, i.blocking) for i in issues] == [("X-907", 3, True)]
    assert rule_ids(c) == ["M-000", "M-000", "M-061"] and _applied_rows(c) == [2]
    assert "Already Shut Down" in c.steps[0].rationale
    _assert_refused_never_moves_mark(c, 3, ["X-907"])
    assert c.proposed_mark == 0.0 and c.invested_after == 5.0 and c.ownership_after == 0.0
    assert c.realized_quarter == pytest.approx(0.5) and c.realized_cumulative == pytest.approx(1.5)
    assert c.status_after is Status.SHUT_DOWN and c.action is ValuationAction.CARRY
    assert flag_ids(c) == {"X-900"}, "X-115 is not raised on a terminal position: cash in, nothing to decide"
    assert c.disposition is Disposition.BLOCK and c.readiness is Readiness.BLOCKED
    assert run.blocked
    _assert_actionable(c)


# =============================================================================== 10. shutdown vs priced round

@pytest.mark.parametrize("reverse", [False, True], ids=["shutdown-first-on-sheet", "round-first-on-sheet"])
def test_shutdown_then_priced_round_dated_after_it_is_suppressed(build, reverse):
    rows = [event(EventType.SHUTDOWN, date=date(2026, 7, 10), detail="Ceased operations"),
            event(R, date=date(2026, 9, 10), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=3.0)]
    if reverse:
        rows.reverse()
    run, issues = build([position()], rows)
    c = only(run)
    shut_row, rnd_row = (3, 2) if reverse else (2, 3)
    assert issues == []
    assert rule_ids(c) == ["M-021", "M-000"] and _applied_rows(c) == [shut_row] and _suppressed(c) == [rnd_row]
    assert c.steps[0].prior_value == PRIOR and c.steps[0].new_value == 0.0
    sup = c.steps[1]
    assert sup.prior_value == sup.new_value == 0.0 and "closed earlier in the quarter" in sup.rationale
    assert sup.evidence.row_index == rnd_row and sup.evidence.date == date(2026, 9, 10)
    assert c.proposed_mark == 0.0 and c.invested_after == 5.0 and c.ownership_after == 0.10, "the suppressed round's cash and stake are not counted"
    assert c.latest_post_money == 100.0 and c.staleness_anchor == date(2025, 6, 15)
    assert c.status_after is Status.SHUT_DOWN and c.action is ValuationAction.WRITE_OFF
    # fixed: a financing dated after the shutdown is a contradiction in the feed, not a quiet write-off
    assert flag_ids(c) == {"X-900"}
    _assert_contradiction_never_moves_mark(c, rnd_row, "closed earlier in the quarter")
    assert "2026-09-10" in _flag(c, "X-900").action
    assert c.disposition is Disposition.BLOCK and c.readiness is Readiness.BLOCKED
    assert run.blocked
    _assert_actionable(c)


def test_priced_round_after_a_shutdown_is_a_contradiction_that_needs_a_person(build):
    """fixed: a $3M priced round dated AFTER a shutdown is no longer suppressed into a CLEAR/Ready
    write-off. It is recorded as a contradiction (wrong date or wrong event — the engine does not
    choose which) with an X-900 BLOCK naming the row; the position is Blocked and the mark carried."""
    run, issues = build([position()], [
        event(EventType.SHUTDOWN, date=date(2026, 7, 10), detail="Ceased operations"),
        event(R, date=date(2026, 9, 10), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=3.0),
    ])
    c = only(run)
    assert issues == [], "ingest cannot see the contradiction: both rows are well-formed on their own"
    assert c.proposed_mark == 0.0 and _suppressed(c) == [3] and not _refused(c)
    assert c.readiness is not Readiness.READY
    assert any(f.severity is not Severity.MONITOR and f.evidence.get("row_index") == 3 for f in c.flags)
    _assert_contradiction_never_moves_mark(c, 3, "a financing cannot follow an exit")
    assert "X-900" in MISSING_INPUT_RULES, "two rows that cannot both be true are a missing input, not a judgment"


def test_priced_round_then_shutdown_writes_off_the_fresh_price(build):
    run, issues = build([position()], [
        event(R, date=date(2026, 7, 10), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=3.0),
        event(EventType.SHUTDOWN, date=date(2026, 9, 10), detail="Ceased operations"),
    ])
    c = only(run)
    assert issues == []
    assert rule_ids(c) == ["M-010", "M-021"] and _applied_rows(c) == [2, 3]
    assert c.steps[0].new_value == pytest.approx(18.0)
    assert c.steps[1].prior_value == pytest.approx(18.0) and c.steps[1].new_value == 0.0
    assert c.steps[1].inputs["prior_mark"] == pytest.approx(18.0) and "$18.0M written off" in c.steps[1].rationale
    assert c.proposed_mark == 0.0 and c.invested_after == pytest.approx(8.0) and c.ownership_after == 0.09
    assert c.latest_post_money == 200.0 and c.staleness_anchor == date(2026, 7, 10)
    assert c.status_after is Status.SHUT_DOWN and c.action is ValuationAction.WRITE_OFF and c.fv_level is None
    assert c.valuation_change_quarter == pytest.approx(-13.0), "0 − 10 − 3 new money + 0 realized"
    assert c.moic_after == 0.0
    assert c.flags == () and c.disposition is Disposition.CLEAR and c.readiness is Readiness.READY


# =============================================================================== 11. unknown event type

def test_tender_offer_is_m999_block_and_blocked(build):
    """'Tender Offer' is an ambiguous X-914 at ingest (prefix-matches Secondary Purchase / Secondary
    Sale) and is NOT refused: it is dispatched to M-999, which blocks the position and raises the
    adjudication proposal. fixed: readiness is Blocked, not Needs Review — M-999 is now on the
    missing-input list (the treatment is the missing input, and E-09 exists to draft it), which
    agrees with the row's own X-914: 'not guessed, fix the cell'. Disposition BLOCK is unchanged."""
    run, issues = build([position()], [event("Tender Offer", detail="Tender at $250M", value=250.0, ownership_after=0.08, proceeds=3.0)])
    c = only(run)
    assert [(i.rule_id, i.severity, i.blocking, i.row_index) for i in issues] == [("X-914", Severity.BLOCK, True, 2)]
    assert "Tender Offer" in issues[0].message and "Secondary" in issues[0].message
    assert rule_ids(c) == ["M-999"] and _applied_rows(c) == [2] and not _refused(c)
    s = c.steps[0]
    assert s.prior_value == s.new_value == PRIOR and s.inputs["event_type"] == "Tender Offer" and s.evidence.row_index == 2
    assert c.proposed_mark == PRIOR and c.realized_quarter == 0.0 and c.ownership_after == 0.10, "nothing on the row is booked"
    assert flag_ids(c) == {"M-999"}
    m999 = _flag(c, "M-999", Severity.BLOCK)
    assert "'Tender Offer'" in m999.action and m999.evidence["event_type"] == "Tender Offer"
    assert m999.evidence["signature"] == "tender offer|proceeds"
    assert [(s.key, s.booked) for s in m999.suggestions] == [("hold_prior", PRIOR)]
    assert "M-999" in MISSING_INPUT_RULES, "fixed: an unrecognised event is a missing treatment"
    assert c.disposition is Disposition.BLOCK and c.readiness is Readiness.BLOCKED
    assert c.action is ValuationAction.REVALUE, "M-999 is not on the action map, so an unchanged mark reads as 'Revalue'"
    assert run.blocked
    _assert_actionable(c)


def test_tender_offer_then_priced_round_still_blocks_on_m999(build):
    """The unknown row does not stop a later clean row from applying; M-999 still blocks (fixed:
    readiness Blocked). Its message ('the mark is unchanged') describes its own step, not the
    quarter: the round moved it."""
    run, issues = build([position()], [
        event("Tender Offer", date=date(2026, 7, 5), detail="Tender at $250M", value=250.0, ownership_after=0.08, proceeds=3.0),
        event(R, date=date(2026, 9, 10), detail="Series B", value=200.0, ownership_after=0.09, hc_investment=1.0),
    ])
    c = only(run)
    assert _issue_ids(issues) == ["X-914"]
    assert rule_ids(c) == ["M-999", "M-010"] and _applied_rows(c) == [2, 3]
    assert c.steps[0].prior_value == c.steps[0].new_value == PRIOR
    assert c.steps[1].prior_value == PRIOR and c.steps[1].new_value == pytest.approx(18.0)
    assert c.proposed_mark == pytest.approx(18.0) and c.realized_quarter == 0.0
    assert flag_ids(c) == {"M-999"} and _flag(c, "M-999").severity is Severity.BLOCK
    assert c.disposition is Disposition.BLOCK and c.readiness is Readiness.BLOCKED
    _assert_actionable(c)


# =============================================================================== refused rows beside applied ones

def test_refused_round_beside_a_clean_secondary_only_the_secondary_moves_the_mark(build):
    """The refused row is not evidence: the secondary prices against the book's $100M, not the
    round's missing post-money, and the position blocks on the refused row."""
    run, issues = build([position()], [
        event(R, date=date(2026, 7, 10), detail="Series B", ownership_after=0.09, hc_investment=1.0),
        event(EventType.SECONDARY, date=date(2026, 9, 10), detail="Sold block", value=100.0, ownership_after=0.08, proceeds=2.0),
    ])
    c = only(run)
    assert _issue_ids(issues) == ["X-902"] and issues[0].row_index == 2
    assert rule_ids(c) == ["M-000", "M-030"] and _applied_rows(c) == [3]
    _assert_refused_never_moves_mark(c, 2, ["X-902"])
    assert c.steps[1].prior_value == PRIOR and c.steps[1].new_value == pytest.approx(8.0)
    assert c.steps[1].inputs["last_round_post_money"] == 100.0 and c.steps[1].inputs["ownership_before"] == 0.10
    assert c.proposed_mark == pytest.approx(8.0) and c.ownership_after == 0.08 and c.realized_quarter == pytest.approx(2.0)
    assert c.invested_after == 5.0, "the refused round's $1M is not counted"
    assert c.latest_post_money == 100.0 and c.staleness_anchor == date(2025, 6, 15)
    assert flag_ids(c) == {"X-900"} and c.action is ValuationAction.PARTIAL_EXIT
    _assert_actionable(c)


def test_announced_then_refused_closing_row_stays_announced(build):
    run, issues = build([position()], [
        event(EventType.ACQ_ANNOUNCED, date=date(2026, 7, 15), detail="Definitive agreement", value=300.0),
        event(EventType.ACQ_CLOSED, date=date(2026, 9, 1), detail="Closed", proceeds=30.0),
    ])
    c = only(run)
    assert _issue_ids(issues) == ["X-902"] and issues[0].row_index == 3
    assert rule_ids(c) == ["M-050", "M-000"] and _applied_rows(c) == [2] and not _skipped(c)
    _assert_refused_never_moves_mark(c, 3, ["X-902"])
    assert c.steps[1].prior_value == c.steps[1].new_value == pytest.approx(28.0)
    assert c.proposed_mark == pytest.approx(28.0) and c.realized_quarter == 0.0, "proceeds on a refused exit are not realized"
    assert c.status_after is Status.ACTIVE and c.action is ValuationAction.CARRY
    assert [i.kind.value for i in c.open_items] == ["pending_acquisition"]
    assert flag_ids(c) == {"X-101", "X-900"}
    assert _flag(c, "X-101").severity is Severity.BLOCK
    assert c.readiness is Readiness.BLOCKED and c.disposition is Disposition.BLOCK
    _assert_actionable(c)
