"""The one contract that matters.

    run_valuation(portfolio, activity, market, overrides, config) -> ValuationRun

Pure. No file reads, no network, no clock — the measurement date comes from config and
`generated_at` is supplied by the caller. Market data arrives already fetched. That
purity is what makes the determinism test possible and lets a real connector replace a
stub without the engine noticing.

Refused rows. An activity row carrying a blocking validation issue (X-902 / X-903 / X-905
outside the grace period / X-914 / X-920 …) is *recorded* against its position — an M-000
"recorded but not applied" step and an X-900 BLOCK flag — and never dispatched to a marking
rule. Four consequences follow from "a refused row is not evidence of anything":

* it never supersedes another row: an announced acquisition followed by a closing (or
  termination) row that was refused stays announced — M-050 applies, the pending item stays
  open, the refused close is recorded and the position blocks until the row is corrected;
* it never closes a position: proceeds on a refused exit are not realized;
* a listed position (Stage = Public) whose only rows were refused is still worth its close —
  M-041 runs on the carry side, and the refusal blocks on top of it;
* the one exception is a row whose event type has no real handler (M-999): it is dispatched
  so M-999 blocks and the adjudication proposal is raised.

A *Portfolio* row carrying a blocking issue (X-903 ownership out of range, X-904 unreconciled
prior mark, X-906 duplicate, X-921 latest round after the measurement date, an uncoercible cell)
blocks its position the same way: the mark is rolled as usual — the book is never silently
edited — and an X-900 BLOCK says which cell to fix.
"""
from __future__ import annotations

import re

import hashlib
import json
from datetime import date, datetime, time
from typing import Any, Mapping

from ..config import RuleConfig
from . import declarative, marking, precedence
from .readiness import action_of, approval_of, readiness_of, valuation_change
from .notes import apply_readings
from .exceptions import assess_carry_side, disposition, screen_notes
from .inputs import ActivityFeed, Event, EventType, PortfolioSnapshot, Position, Status
from .models import (OpenItemKind,
    CompanyResult, MarketData, OpenItem, OverrideLedger, RunManifest, Severity, ValidationIssue, ValuationRun,
)
from .open_items import RESOLVES, carry_prior_items
from .overrides import apply_override
from .registry import BUILTIN, Registry
from .rollup import comps_move, fund_rollups, is_multiple_exposed, portfolio_totals, sensitivity
from .state import Suggest, Working

ENGINE_VERSION = "0.1.0"


def build_registry(config: RuleConfig) -> Registry:
    reg = BUILTIN.copy()
    declarative.register_custom_rules(reg, config)
    return reg


LISTED_STAGE = "public"


def is_listed(p: Position) -> bool:
    """A position the book already carries as a public security (M-041 applies on the carry side)."""
    return p.stage.strip().lower() == LISTED_STAGE


# Screens that only mean something for a going concern; dropped from a terminal position.
CARRY_SIDE_FAMILIES = frozenset({"staleness", "growth", "liquidity", "valuation"})


def _dispatch(w: Working, e: Event, registry: Registry, config: RuleConfig, market: MarketData, md: date) -> None:
    found = registry.handler_for(e.event_type, md)
    if found is None:  # pragma: no cover - M-999 is always registered
        raise RuntimeError(f"no handler and no fallback for event type {e.event_type!r}")
    _meta, fn = found
    before = list(w.open_items)
    fn(w, e, config, market)
    # An event resolves the open items its kind resolves (RESOLVES) whether they were carried in
    # from a prior quarter or opened by an earlier row this quarter: a term sheet signed in March
    # and closed as a round in March is not still pending in June. Items the event itself opened are
    # kept — a closing with no cash opens the unconfirmed-exit item it must not immediately resolve.
    # (Synthetic Q2 2027 chain, HARDENING_REPORT.md D-11.)
    settles = RESOLVES.get(e.event_type, set())
    if settles:
        w.open_items = [i for i in w.open_items if not (i.kind in settles and i in before)]


def _blocked_rows(validation: tuple[ValidationIssue, ...], sheet: str) -> dict[int, list[ValidationIssue]]:
    """Rows of `sheet` that ingest refused: a blocking issue anchored to a row. On the activity
    sheet such a row is *recorded* against its position but never dispatched — a rule handed a
    cell it could not trust (a missing post-money, 150% ownership, a euro figure) would either
    crash or, worse, book a number. On the Portfolio sheet the position it describes blocks."""
    out: dict[int, list[ValidationIssue]] = {}
    for v in validation:
        if v.blocking and v.severity == Severity.BLOCK and v.row_index is not None and v.sheet == sheet:
            out.setdefault(v.row_index, []).append(v)
    return out


# The ingest corrections that change a number a person has not confirmed. X-904 explained and
# X-918 are REVIEW too, but one is a departure the sidecar already vouches for and the other
# is raised on the position in its own words; neither is a reading to confirm.
_CORRECTED_READINGS = frozenset({"X-905", "X-916"})


def _review_rows(validation: tuple[ValidationIssue, ...], sheet: str) -> dict[int, list[ValidationIssue]]:
    """Rows of `sheet` that ingest applied on a corrected reading — a percentage read as points
    (X-916), a row dated before the window but inside the grace period (X-905). The number moved
    on a reading a person has not confirmed; the row is applied, and the position says so
    (X-923) rather than reading clean."""
    out: dict[int, list[ValidationIssue]] = {}
    for v in validation:
        if (not v.blocking and v.severity == Severity.REVIEW and v.rule_id in _CORRECTED_READINGS
                and v.row_index is not None and v.sheet == sheet):
            out.setdefault(v.row_index, []).append(v)
    return out


def _confirm_reading(w: Working, issues: list[ValidationIssue], *, sheet: str, row_index: int, what: str) -> None:
    """X-923: the row was applied, but on a reading ingest had to correct or accept."""
    ids = sorted({v.rule_id for v in issues})
    why = "; ".join(f"{v.rule_id}: {v.message}" for v in issues)
    w.flag("X-923", "data", Severity.REVIEW,
           f"Row {row_index} of the {sheet} tab ({what}) was applied on a corrected reading ({why}). The mark moved on "
           "that reading; confirm it is what the row meant before the number is booked.",
           points=(f"Row **{row_index}** ({what}) was applied on a **corrected reading**: {why}.",
                   "The **mark moved on that reading**, which nobody has confirmed.",
                   "Confirm the cell, or correct it and rerun."),
           suggestions=(
               Suggest("as_proposed", "Confirm the corrected reading and book the mark it produced.", ("Ingest read the cell the way a person would.", "Right when the correction matches what the row meant."), "proposed"),
               Suggest("hold_prior", "Hold the prior mark until the cell is corrected and rerun.", ("Nothing is booked from a reading nobody confirmed.", "Rerunning after the fix clears this without an override."), "prior"),
           ),
           action=f"Confirm the corrected reading on row {row_index} of the {sheet} tab ({', '.join(ids)}), or fix the cell and rerun.",
           sheet=sheet, row_index=row_index, validation=ids)


# Non-binding paperwork dated after an exit — a term sheet — is a stray row, not a contradiction:
# nothing about it could have moved the mark, so it is recorded and set aside without a person.
# A financing, a listing, a sale or a second exit after an exit is a different matter.
_QUIET_AFTER_TERMINAL = frozenset({EventType.TERM_SHEET.value})


def _suppress(w: Working, e: Event) -> None:
    w.step("M-000", marking.V, {"suppressed_event": e.event_type, "row_index": e.row_index},
           w.proposed_mark, w.proposed_mark,
           f"{e.event_type} on {e.date.isoformat()} recorded but not applied: the position closed earlier in the quarter.", e)


def _contradict(w: Working, e: Event, why: str) -> None:
    """A row that cannot be true alongside the position's own history — a priced round on a
    company the book already shows as acquired, a financing dated after this quarter's
    shutdown. Recorded, not applied, and the position blocks until the date or the event is
    corrected: two rows that contradict each other are a missing input, not a judgment."""
    w.step("M-000", marking.V, {"suppressed_event": e.event_type, "row_index": e.row_index, "contradiction": why},
           w.proposed_mark, w.proposed_mark,
           f"{e.event_type} on {e.date.isoformat()} recorded but not applied: {why}. The mark is carried unchanged.", e)
    w.flag("X-900", "data", Severity.BLOCK,
           f"Row {e.row_index} of the activity tab ({e.event_type} on {e.date.isoformat()}) contradicts the position: {why}. "
           "Either the date or the event is wrong, and the engine will not choose which; the prior mark is carried until "
           "the workbook is corrected.",
           points=(f"Activity row **{e.row_index}** ({e.event_type}, {e.date.isoformat()}) **contradicts the position**: {why}.",
                   "Either the **date or the event is wrong** — the engine will not choose which.",
                   "The **prior mark is carried** until the workbook is corrected."),
           suggestions=(
               Suggest("hold_prior", "Hold the prior mark; correct the row and rerun.", ("Two rows that cannot both be true are a data question, not a valuation one.", "Rerunning after the fix clears this without an override."), "prior"),
           ),
           action=f"Correct row {e.row_index} of the activity tab ({e.event_type} on {e.date.isoformat()}): {why}.",
           sheet="activity", row_index=e.row_index)


def _refused(e: Event, blocked: dict[int, list[ValidationIssue]], registry: Registry, md: date) -> list[ValidationIssue]:
    """The issues that stop this row from being applied, or [] when it may be dispatched.

    An unrecognised or ambiguous event type (X-909 / X-914 on the Event column) is *not* a
    reason to hold the row back: its handler is M-999, which blocks the position and raises
    the adjudication proposal (E-09). Refusing it here would hide the new event from the
    people who have to decide what it means."""
    issues = blocked.get(e.row_index, [])
    if not issues:
        return []
    found = registry.handler_for(e.event_type, md)
    if found is not None and found[0].rule_id == marking.UNKNOWN_RULE_ID:
        return []
    return issues


# What fixes a refused row, by the check that refused it. One sentence an analyst can act on; the
# check's own message (the cells, the rows) is in the finding's evidence and the data-checks footer.
_FIX = {
    "X-901": "Add the company to the Portfolio tab, or correct its name on the row, and rerun.",
    "X-902": "Fill in the missing figure on the row and rerun.",
    "X-903": "Correct the figure that is out of range and rerun.",
    "X-905": "Correct the row's date and rerun.",
    "X-906": "Delete one of the duplicate rows and rerun.",
    "X-907": "Remove the row, or correct the company's status on the Portfolio tab, and rerun.",
}


def _short(msg: str) -> str:
    """The check's message up to its first clause break: what is wrong, without the lecture."""
    head = re.sub(r"\s*\([^()]*\)\s*$", "", msg.split(";", 1)[0].strip())   # drop a trailing "(company, event, …)" list
    return head[0].upper() + head[1:] if head else msg


def _refuse(w: Working, e: Event, issues: list[ValidationIssue]) -> None:
    """Record a refused row on the position. Nothing about the mark changes; the position's one
    X-900 finding is raised by `_flag_refused` once every row has been seen."""
    ids = sorted({v.rule_id for v in issues})
    w.step("M-000", marking.V, {"refused_event": e.event_type, "row_index": e.row_index, "validation": ids},
           w.proposed_mark, w.proposed_mark,
           f"{e.event_type} on {e.date.isoformat()} recorded, not applied ({', '.join(ids)}): "
           f"{_short('; '.join(v.message for v in issues))}. Mark carried unchanged.", e)
    w.refused_rows.append((e, list(issues)))


def _rows(rows: list[int], bold: bool = False) -> str:
    n = [f"**{r}**" if bold else str(r) for r in rows]
    return f"row {n[0]}" if len(n) == 1 else "rows " + ", ".join(n[:-1]) + f" and {n[-1]}"


def _refused_points(groups: dict[tuple[str, str], list[int]], fixes: list[str]) -> tuple[str, ...]:
    """At most three lines: the refused rows (one line per reason, the third and later reasons
    folded into the second line), the fix, and the carry — the carry shares the fix's line when
    there is more than one reason."""
    lines = [f"{_rows(sorted(r), bold=True).capitalize()} ({et}) could not be applied. {why}." for (et, why), r in groups.items()]
    if len(lines) > 2:
        rest = sorted(r for grp in list(groups.values())[1:] for r in grp)
        lines = [lines[0], f"{_rows(rest, bold=True).capitalize()} could not be applied either; the data checks list each reason."]
    if len(lines) == 1:
        return (lines[0], f"**{' '.join(fixes)}**", "The **prior mark is carried**; nothing from the row is booked.")
    return (*lines, f"**{' '.join(fixes)}** The **prior mark is carried** meanwhile; nothing from the rows is booked.")


def _flag_refused(w: Working) -> None:
    """One X-900 per position, however many rows were refused. Rows refused for the same reason
    (the two copies of a duplicate, say) are one line, not one finding each: the reviewer needs
    to know what to fix on the tab, once."""
    if not w.refused_rows:
        return
    groups: dict[tuple[str, str], list[int]] = {}
    for e, issues in w.refused_rows:
        why = (_short("; ".join(v.message for v in sorted(issues, key=lambda v: v.rule_id)))
               + f" ({', '.join(sorted({v.rule_id for v in issues}))})")
        groups.setdefault((e.event_type, why), []).append(e.row_index)
    ids = sorted({v.rule_id for _, issues in w.refused_rows for v in issues})
    rows = sorted({e.row_index for e, _ in w.refused_rows})
    fixes = list(dict.fromkeys(_FIX.get(i, "Correct the cell the check names and rerun.") for i in ids))
    if len(fixes) > 1:   # "Fill in the missing figure; correct the row's date, then rerun." — one sentence, one rerun
        cores = [re.sub(r",? and rerun\.$", "", f) for f in fixes]
        fixes = ["; ".join([cores[0]] + [c[0].lower() + c[1:] for c in cores[1:]]) + ", then rerun."]
    lines = [f"{_rows(sorted(r)).capitalize()} ({et}) could not be applied. {why}." for (et, why), r in groups.items()]
    w.flag("X-900", "data", Severity.BLOCK,
           " ".join(lines) + " Nothing from " + ("the row" if len(rows) == 1 else "these rows") + " is booked; the prior mark is carried "
           "until the activity tab is corrected and the quarter rerun. " + " ".join(fixes),
           points=_refused_points(groups, fixes),
           suggestions=(
               Suggest("hold_prior", "Hold the prior mark; fix the activity tab and rerun.", ("The engine will not book a number from a row it could not apply.", "Rerunning after the fix clears this without an override."), "prior"),
           ),
           action=f"{' '.join(fixes)[:-1]} ({_rows(rows)} of the activity tab, {', '.join(ids)}).",
           sheet="activity", row_index=rows[0], rows=rows, validation=ids,
           checks=[f"{v.rule_id}: {v.message}" for _, issues in w.refused_rows for v in issues])


def _refuse_book_row(w: Working, p: Position, issues: list[ValidationIssue]) -> None:
    """The position's own Portfolio row failed a blocking check. The roll proceeds on what the
    book says — nothing is edited or guessed — but the number cannot be booked until the row is
    fixed, so the position blocks and the flag names the cell."""
    ids = sorted({v.rule_id for v in issues})
    why = "; ".join(f"{v.rule_id}: {v.message}" for v in issues)
    w.flag("X-900", "data", Severity.BLOCK,
           f"Row {p.row_index} of the Portfolio tab ({p.company}) failed validation: {why}. The position is rolled on the "
           "figures the book carries, but a mark that starts from a row the engine could not reconcile cannot be booked "
           "until the book is corrected.",
           points=(f"Portfolio row **{p.row_index}** ({p.company}) **failed validation**: {why}.",
                   "The position is rolled on the figures the book carries.",
                   "A mark starting from an **unreconciled row cannot be booked**."),
           suggestions=(
               Suggest("hold_prior", "Hold the prior mark; correct the cell and rerun.", ("A mark starting from an unreconciled row cannot be booked.", "Rerunning after the fix clears this without an override."), "prior"),
           ),
           action=f"Correct the cell(s) named in {', '.join(ids)} on row {p.row_index} of the Portfolio tab and rerun.",
           sheet="portfolio", row_index=p.row_index, validation=ids)


def _positions_to_roll(portfolio: PortfolioSnapshot, activity: ActivityFeed) -> list[Position]:
    """The book, plus one synthesised zero position per company the activity tab names that the
    book does not have. For a `New Investment` that position is HC's first holding (M-014, X-918).
    For any other event it is a placeholder that carries nothing: its row was refused at ingest
    (X-901), the refusal blocks it (X-900), and the reviewer sees a card in the queue — a name the
    book does not know is a question for a person, never a line that only the data-checks drawer
    shows. Appended after the book in activity order, so the run is a pure function of the inputs."""
    positions = list(portfolio.positions)
    book = portfolio.by_company()
    known_sectors = {p.sector for p in portfolio.positions}
    seen: set[str] = set()
    for e in activity.events:
        if e.company not in book and e.company not in seen:
            positions.append(marking.synthesise_position(e, known_sectors))
            seen.add(e.company)
    return positions


def _provisional(w, measurement_date) -> tuple[str | None, str | None]:
    """A mark is provisional when a rule had to stand something in for an input that is not on
    file. Today that is one case — a listed holding with no measurement-date quote, where the
    engine uses the listing-day market cap — and it is stated in the reviewer's words, not the
    rule's, because it is the first thing the card has to say."""
    for step in w.steps:
        src = str(step.inputs.get("price_source") or "")
        # `ipo_print`: M-040 with no measurement-date quote uses the listing-day cap itself; `stub:` /
        # `seeded`: a fixture quote. One definition, shared with M-041 (marking.is_standin_price).
        if marking.is_standin_price(src):
            cap = step.inputs.get("measurement_date_market_cap")
            rule = next((f.rule_id for f in w.flags if f.family == "treatment"), step.rule_id)
            return rule, (f"Missing the {measurement_date.strftime('%d %b %Y')} closing price. The mark "
                          f"stands in the listing-day market cap"
                          + (f" (${float(cap):,.0f}M)" if cap else "")
                          + " until the close is obtained.")
    return None, None


def run_valuation(
    portfolio: PortfolioSnapshot,
    activity: ActivityFeed,
    market: MarketData,
    overrides: OverrideLedger,
    config: RuleConfig,
    *,
    validation: tuple[ValidationIssue, ...] = (),
    prior_open_items: tuple[OpenItem, ...] = (),
    prior_staleness_anchors: Mapping[str, date] | None = None,
    prior_note_legs: Mapping[str, float] | None = None,
    note_readings: Mapping[int, Any] | None = None,     # notes/schema.py RowReading by activity row, read outside the engine
    note_reader: str = "off",
    note_reader_report: Mapping[str, Any] | None = None,
    input_sha256: str = "",
    input_file: str = "",
    generated_at: datetime | None = None,
    market_data_source: str = "none",
) -> ValuationRun:
    md = config.quarter.measurement_date
    quarter = config.quarter.label
    registry = build_registry(config)
    events_by = activity.by_company()
    blocked = _blocked_rows(validation, activity.sheet_name)
    blocked_book = _blocked_rows(validation, portfolio.sheet_name) if portfolio.sheet_name != activity.sheet_name else {}
    review_rows = _review_rows(validation, activity.sheet_name)
    review_book = _review_rows(validation, portfolio.sheet_name) if portfolio.sheet_name != activity.sheet_name else {}
    results: list[CompanyResult] = []

    for p in _positions_to_roll(portfolio, activity):
        w = Working.from_position(p, quarter, activity.sheet_name)
        # A same-terms extension last quarter repriced ownership but was not price discovery: the
        # emitted book carries the extension as `Latest Round` (its own definition) and the older
        # anchor in the sidecar, so the clock the engine kept running keeps running here.
        carried = (prior_staleness_anchors or {}).get(p.company)
        if carried is not None and carried < w.staleness_anchor:
            w.staleness_anchor = carried
            w.carried_anchor = carried
        # A note HC funded last quarter sits inside `Prior Mark` at cost (M-060 keeps it on its own
        # leg, the Portfolio tab has one column). The sidecar says how much; the leg is restored so
        # the mark still splits into equity and note, and a repayment this quarter clears the leg
        # rather than counting the principal twice. Bounded by the prior mark: a leg the book
        # cannot hold is ignored and the X-904 reconciliation says the prior mark is unexplained.
        leg = float((prior_note_legs or {}).get(p.company) or 0.0)
        if p.status == Status.ACTIVE and 0 < leg <= p.prior_mark:
            w.note_at_cost = round(leg, 6)
            w.equity_mark = round(p.prior_mark - leg, 6)
            w.carried_note_leg = leg
        listed = is_listed(p) and p.status == Status.ACTIVE
        if listed:
            w.listed, w.fv_level = True, 1
        evs = precedence.ordered(events_by.get(p.company, []))
        # A refused row is not evidence: it neither supersedes nor is superseded by anything.
        live = [e for e in evs if not _refused(e, blocked, registry, md)]
        resolved: set = set()
        if not p.extra.get("synthesised") and p.row_index in blocked_book:
            _refuse_book_row(w, p, blocked_book[p.row_index])
        elif not p.extra.get("synthesised") and p.row_index in review_book:
            _confirm_reading(w, review_book[p.row_index], sheet="Portfolio", row_index=p.row_index, what=p.company)

        if p.status != Status.ACTIVE:
            w.step("M-000", marking.V, {"status": p.status.value, "realized": p.realized}, 0.0, 0.0,
                   f"Already {p.status.value} at the prior close; carried at zero with ${p.realized:.1f}M cumulative realized.")
            # Activity on a terminal company is an X-907 validation issue and is not applied — except cash
            # arriving after the exit (a distribution, a note repaid), which moves realized and nothing else.
            applied = []
            for e in evs:
                if refused := _refused(e, blocked, registry, md):
                    _refuse(w, e, refused)
                    continue
                if e.event_type not in precedence.ALLOWED_AFTER_TERMINAL:
                    if e.event_type in _QUIET_AFTER_TERMINAL:
                        _suppress(w, e)
                    else:
                        _contradict(w, e, f"the position was already {p.status.value} at the prior close")
                    continue
                _dispatch(w, e, registry, config, market, md)
                applied.append(e)
                if rv := review_rows.get(e.row_index):
                    _confirm_reading(w, rv, sheet="activity", row_index=e.row_index, what=e.event_type)
            _flag_refused(w)
            if applied:
                screen_notes(w, applied, config)
                apply_readings(w, applied, note_readings or {}, config)
        elif evs:
            applied = []
            for e in evs:
                if w.terminal and e.event_type not in precedence.ALLOWED_AFTER_TERMINAL:
                    if e.event_type in _QUIET_AFTER_TERMINAL:
                        _suppress(w, e)
                    else:
                        _contradict(w, e, "the position closed earlier in the quarter, and a financing cannot follow an exit")
                    continue
                if refused := _refused(e, blocked, registry, md):
                    _refuse(w, e, refused)
                    continue
                why = precedence.superseded(e, live)
                if why:
                    w.step("M-000", marking.V, {"skipped_event": e.event_type, "row_index": e.row_index},
                           w.proposed_mark, w.proposed_mark, f"{e.event_type} skipped: {why}.", e)
                    continue
                _dispatch(w, e, registry, config, market, md)
                applied.append(e)
                resolved |= RESOLVES.get(e.event_type, set())
                if rv := review_rows.get(e.row_index):
                    _confirm_reading(w, rv, sheet="activity", row_index=e.row_index, what=e.event_type)
            if listed and not w.terminal and "M-040" not in w.applied_rules:
                # A public security is worth its close whatever else happened this quarter: a dividend, a
                # secondary or a refused row does not turn last quarter's number into a fair value.
                marking.listed_carry(w, config, market)
            elif not applied:   # every row refused or skipped: the position is carried as if the quarter were quiet
                marking.apply_carry(w, reason="No activity could be applied this quarter")
            _flag_refused(w)
            # note language is screened on rows that were skipped as superseded, not on refused rows: a
            # refused row is fixed and rerun, and its note is read then
            screen_notes(w, live, config)
            apply_readings(w, live, note_readings or {}, config)
        elif listed:
            marking.listed_carry(w, config, market)   # M-041: a public security is worth its close, not its history
        else:
            marking.apply_carry(w)

        carry_prior_items(w, list(prior_open_items), config, resolved)
        assess_carry_side(w, config, market)
        marking.calibrate_stale(w, config, market)

        booked, override = apply_override(w, overrides, quarter, config.tolerances.prior_mark_reconciliation_musd)
        realized_cum = p.realized + w.realized_quarter
        invested_after = w.invested
        # Suggestions get their numbers only now, when the proposal is final. A terminal position
        # then drops its carry-side screens (staleness, growth, runway, multiples mean nothing for a
        # company that no longer exists) but keeps every BLOCK and every event-driven REVIEW: an
        # exit with no proceeds must surface, and so must an exit whose cash is short of the deal
        # value — an escrow receivable is a number a reviewer could change.
        new_investment = round(invested_after - p.invested, 6)
        # A mark standing in for an input that is not on file is provisional, whatever else is
        # true about it: it cannot be the final number, and the missing input is the next action.
        provisional_rule, provisional_reason = _provisional(w, md)
        final_flags = w.resolved_flags(w.proposed_mark, p.prior_mark, invested_after)
        if w.terminal:
            flags = tuple(f for f in final_flags if f.severity == Severity.BLOCK or f.family not in CARRY_SIDE_FAMILIES)
        else:
            flags = tuple(final_flags)
        disp = disposition(flags, w.terminal, config,
                           addressed=set(override.rule_ids_addressed) if override else None,
                           overridden=override is not None)
        rule_ids = tuple(dict.fromkeys(s_.rule_id for s_ in w.steps))
        ready = readiness_of(flags, override, provisional_rule=provisional_rule)
        act = action_of(rule_ids, terminal=w.terminal, realized_quarter=w.realized_quarter,
                        new_investment=new_investment, already_terminal=p.status != Status.ACTIVE)
        change = valuation_change(p.prior_mark, booked, new_investment=new_investment,
                                  realized_quarter=w.realized_quarter)
        aged_runway = (p.runway_months - config.metrics.reporting_lag_months) if p.runway_months is not None else None
        implied_mult = (w.latest_post / p.arr) if (p.arr and p.arr >= config.exceptions.multiple.min_arr and w.latest_post and not w.terminal) else None

        results.append(CompanyResult(
            company=p.company, fund=p.fund, sector=p.sector, stage=w.stage,
            status_before=p.status, status_after=w.status, listed=w.listed,
            prior_mark=p.prior_mark, equity_mark=round(w.equity_mark, 6), note_at_cost=round(w.note_at_cost, 6),
            proposed_mark=round(w.proposed_mark, 6), booked_mark=round(booked, 6), override=override,
            ownership_before=p.ownership, ownership_after=w.ownership,
            invested_before=p.invested, invested_after=round(invested_after, 6),
            realized_quarter=round(w.realized_quarter, 6), realized_cumulative=round(realized_cum, 6),
            latest_post_money=w.latest_post, staleness_anchor=w.staleness_anchor, fv_level=w.fv_level,
            multiple_exposed=is_multiple_exposed(w.fv_level, p.arr, config,
                                                 deal_priced=any(i.kind == OpenItemKind.PENDING_ACQUISITION for i in w.open_items)),
            arr=p.arr, arr_growth=p.arr_growth,
            runway_months_aged=(round(aged_runway, 2) if aged_runway is not None else None),
            implied_multiple=(round(implied_mult, 2) if implied_mult else None),
            moic_after=(round((booked + realized_cum) / invested_after, 4) if invested_after else None),
            new_investment_quarter=new_investment, valuation_change_quarter=change,
            provisional=provisional_reason is not None, provisional_reason=provisional_reason,
            steps=tuple(w.steps), flags=flags, disposition=disp,
            readiness=ready, action=act, approval=approval_of(override),
            monitor=any(f.severity == Severity.MONITOR for f in flags),
            open_items=tuple(w.open_items), alternative_marks={k: round(v, 6) for k, v in w.alternative_marks.items()},
        ))

    rollups = fund_rollups(results)
    totals = portfolio_totals(results)
    sens = sensitivity(results, config)
    sens_meta = {"shock_pct": list(config.sensitivity.multiple_shock_pct), "min_arr": config.exceptions.multiple.min_arr,
                 "software_sectors": list(config.sensitivity.software_sectors)}
    moved = comps_move(results, config, market)
    all_open = tuple(item for c in results for item in c.open_items)

    gen = generated_at or datetime.combine(md, time.min)
    # The run's identity is every input that can change a number: the workbook, the policy, the
    # engine — and the decisions (the override ledger, the carried open items and anchors). A
    # committee override after a publish therefore changes the run_id, so the review tool's
    # "changes since" indicator can tell that executives are looking at an older book.
    decisions = hashlib.sha256((overrides.model_dump_json() + "|" + json.dumps(
        [o.model_dump(mode="json") for o in prior_open_items] + [{k: v.isoformat() for k, v in sorted((prior_staleness_anchors or {}).items())}]
        + ([{k: float(v) for k, v in sorted(prior_note_legs.items())}] if prior_note_legs else []),   # absent -> the id a run without legs always had
        sort_keys=True)).encode()).hexdigest()[:12]
    # The policy is hashed by content, not by its version string: an edited threshold under an
    # unbumped policy_version still yields a different run. The market-data source is part of the
    # identity too — the same book marked against the fixture and against the live cache are
    # different runs, and the archive must say which one was published.
    policy_sha = hashlib.sha256(config.model_dump_json().encode()).hexdigest()[:12]
    run_id = hashlib.sha256(f"{input_sha256}|{config.policy_version}|{policy_sha}|{ENGINE_VERSION}|{decisions}|{market_data_source}"
                            .encode()).hexdigest()[:12]
    manifest = RunManifest(
        run_id=run_id, input_sha256=input_sha256, input_file=input_file,
        policy_version=config.policy_version, engine_version=ENGINE_VERSION,
        quarter_label=quarter, measurement_date=md, prior_close=config.quarter.prior_close,
        generated_at=gen, adjudication_enabled=config.adjudication.enabled, market_data_source=market_data_source,
        note_reader=note_reader, note_reader_report=dict(note_reader_report or {}),
    )
    return ValuationRun(manifest=manifest, companies=tuple(results), rollups=tuple(rollups),
                        validation=tuple(validation), totals=totals, open_items=all_open, sensitivity=sens,
                        sensitivity_meta=sens_meta, comps_move=moved)
