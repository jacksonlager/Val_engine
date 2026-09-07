"""X-9xx ingestion integrity checks.

Runs on the file, before the engine. The failure mode of a refreshed workbook must be a
named issue, never a wrong number. The reader's `Correction` records become X-911..X-919
here (what was read as what), X-920 scans for a currency the engine cannot price, and
the structural checks (X-901..X-910) run as before.
"""
from __future__ import annotations

from datetime import timedelta

from ..config import RuleConfig
from ..engine import dsl
from ..engine.inputs import (
    KNOWN_EVENT_TYPES, ActivityFeed, Correction, Event, EventType, PortfolioSnapshot, Status,
)
from ..engine.models import Severity, ValidationIssue
from .normalize import currency_hit, infer_fund

# Correction kind -> (rule id, severity, blocking). SPEC §2.
_ISSUE_FOR: dict[str, tuple[str, Severity, bool]] = {
    "header": ("X-911", Severity.MONITOR, False),
    "event_type": ("X-912", Severity.MONITOR, False),
    "company": ("X-913", Severity.MONITOR, False),
    "ambiguous": ("X-914", Severity.BLOCK, True),
    "value": ("X-915", Severity.MONITOR, False),
    "unit": ("X-916", Severity.REVIEW, False),
    "structure": ("X-917", Severity.MONITOR, False),
    "sheet": ("X-919", Severity.MONITOR, False),
    "currency": ("X-920", Severity.BLOCK, True),
    "unparseable": ("X-902", Severity.BLOCK, True),
    "percent_block": ("X-903", Severity.BLOCK, True),
}

# Events whose Value column is a valuation or price: zero or negative cannot be meant.
# (A closed exit at zero proceeds is legal — a wipe-out — so it is not in this set.)
_VALUE_MUST_BE_POSITIVE: frozenset[EventType] = frozenset({
    EventType.PRICED_ROUND, EventType.IPO, EventType.DIRECT_LISTING, EventType.NEW_INVESTMENT,
    EventType.TERM_SHEET, EventType.SECONDARY, EventType.SECONDARY_PURCHASE,
})

# Cash events that are normal on a company the book already shows as exited (SPEC §2):
# an escrow release after an acquisition, a note redeemed out of a wind-down.
_ALLOWED_ON_TERMINAL: dict[Status, frozenset[str]] = {
    Status.ACQUIRED: frozenset({EventType.DISTRIBUTION.value}),
    Status.SHUT_DOWN: frozenset({EventType.DISTRIBUTION.value, EventType.NOTE_REPAID.value}),
}


def handled_event_types(config: RuleConfig) -> frozenset[str]:
    """Built-in event types plus any declarative (promoted) rule in force at the measurement date."""
    md = config.quarter.measurement_date
    return KNOWN_EVENT_TYPES | frozenset(r.event_type for r in config.custom_rules if r.effective_from <= md)


# DSL fields a declarative formula reads straight off the activity row, and the column each
# comes from. The others (ownership_before, prior_mark, close_probability, note_at_cost) always
# have a value; proceeds / hc_investment / ownership_after default when blank (engine/declarative.py).
_FORMULA_ROW_FIELDS: dict[str, str] = {
    "post_money": "Post-Money / Deal Value ($M)",
    "deal_value": "Post-Money / Deal Value ($M)",
}


def _custom_rule_fields(config: RuleConfig) -> dict[str, set[str]]:
    """event type -> the row-sourced fields its in-force declarative formula needs."""
    md = config.quarter.measurement_date
    adj = config.adjudication
    out: dict[str, set[str]] = {}
    for r in config.custom_rules:
        if r.effective_from > md:
            continue
        try:
            used = dsl.fields_used(dsl.parse(r.formula, adj.allowed_fields, adj.allowed_operators))
        except dsl.DSLError:
            continue   # the engine refuses the policy itself when it builds the registry
        out[r.event_type] = {f for f in used if f in _FORMULA_ROW_FIELDS}
    return out


def _money_domain_issues(e: Event, label: str, feed: ActivityFeed, refused: set[tuple[int | None, str | None]],
                         positive_value: bool) -> list[ValidationIssue]:
    """X-903: money or a percentage outside its domain is a data error, never an input. A
    post-money of zero would book the position at nothing, negative proceeds would
    'un-realize' cash, 150% ownership is neither a fraction nor points. Every one blocks."""
    out: list[ValidationIssue] = []

    def issue(msg: str) -> None:
        out.append(ValidationIssue(rule_id="X-903", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                   row_index=e.row_index, company=e.company, message=msg))

    if (e.ownership_after is not None and not (0.0 <= e.ownership_after <= 1.0)
            and (e.row_index, "HC Ownership After (FD %)") not in refused):
        issue(f"ownership after {e.ownership_after} outside [0, 1]")
    if positive_value and e.value is not None and e.value <= 0.0:
        issue(f"{label} value {e.value} must be greater than zero")
    elif e.value is not None and e.value < 0.0:
        issue(f"{label} value {e.value} is negative")
    for name, amount in (("proceeds", e.proceeds), ("HC investment", e.hc_investment)):
        if amount is not None and amount < 0.0:
            issue(f"{label} {name} {amount} is negative")
    return out


def _message(c: Correction) -> str:
    """One line a reviewer can act on: the cell, what it said, what was read."""
    where = c.column or ("sheet" if c.method == "sheet" else c.kind)
    if c.kind == "ambiguous":
        return f"ambiguous {where}: {c.original!r} — {c.detail}; not guessed, fix the cell"
    if c.kind == "currency":
        return f"{where}: non-USD currency {c.detail!r} in {c.original!r}; the engine is USD-only"
    if c.kind == "unparseable":
        return f"{where}: not a number: {c.original!r}"
    if c.kind == "percent_block":
        return f"{where}: {c.detail}"
    if c.kind == "structure":
        return c.detail
    if c.kind == "sheet":
        return f"sheet {c.resolved!r} matched by {c.method} rule (policy expected {c.original!r})"
    return f"{where}: {c.original!r} → {c.resolved!r} [{c.method}]" + (f"; {c.detail}" if c.detail else "")


def _issue_from(c: Correction) -> ValidationIssue:
    rule_id, severity, blocking = _ISSUE_FOR[c.kind]
    return ValidationIssue(rule_id=rule_id, severity=severity, blocking=blocking, sheet=c.sheet,
                           row_index=c.row_index, company=c.company, message=_message(c))


def _percent_blocked(corrections: tuple[Correction, ...]) -> set[tuple[int | None, str | None]]:
    """Cells the reader already refused as out-of-range percents, so the generic X-903 does
    not report the same cell twice."""
    return {(c.row_index, c.column) for c in corrections if c.kind == "percent_block"}


def _currency_in_text(e, feed: ActivityFeed) -> ValidationIssue | None:
    for field in ("detail", "notes"):
        hit = currency_hit(getattr(e, field))
        if hit is not None:
            return ValidationIssue(rule_id="X-920", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                   row_index=e.row_index, company=e.company,
                                   message=f"{field.capitalize()} mentions {hit!r}: a non-USD currency; the engine is USD-only")
    return None


def validate(snapshot: PortfolioSnapshot, feed: ActivityFeed, config: RuleConfig,
             explained_departures: dict[str, str] | None = None) -> list[ValidationIssue]:
    """`explained_departures` maps company -> reason for a prior mark that deliberately departs from
    ownership × last-round post-money (a note leg at cost, a probability-weighted pending deal, a
    committee override). The emitted next-quarter workbook carries these in its sidecar; with an
    explanation X-904 is a non-blocking REVIEW instead of a BLOCK."""
    issues: list[ValidationIssue] = []
    book = snapshot.by_company()
    tol = config.tolerances.prior_mark_reconciliation_musd
    q = config.quarter
    explained = explained_departures or {}
    handled = handled_event_types(config)
    formula_fields = _custom_rule_fields(config)
    grace = timedelta(days=config.tolerances.late_event_grace_days)
    entering = {e.company for e in feed.events if e.event_type == EventType.NEW_INVESTMENT.value}

    # --- X-922: the activity tab names a quarter; the policy names a quarter; they must agree.
    # A Q4 book run under the Q3 policy would carry Q4 events through Q3's window checks (and
    # its measurement date), which is a wrong run, not a data error — so it stops here.
    if feed.quarter_label and feed.quarter_label.strip().upper() != q.label.strip().upper():
        issues.append(ValidationIssue(
            rule_id="X-922", severity=Severity.BLOCK, blocking=True, sheet=feed.sheet_name,
            message=f"The activity tab is {feed.quarter_label!r} but the policy is for {q.label!r} "
                    f"(measurement date {q.measurement_date.isoformat()}). Run with the matching policy — "
                    f"`hc-valuation next-policy` writes it — or point --input at the right workbook."))

    # --- Portfolio tab: what the reader read as what, then the row checks
    issues.extend(_issue_from(c) for c in snapshot.corrections)
    refused = _percent_blocked(snapshot.corrections)
    # Every row of a duplicated name blocks, not just the later one: the engine cannot know which
    # row is the position, and an event for that company would otherwise roll into both.
    names = [p.company for p in snapshot.positions]
    for p in snapshot.positions:
        if names.count(p.company) > 1:
            issues.append(ValidationIssue(rule_id="X-906", severity=Severity.BLOCK, sheet=snapshot.sheet_name,
                                          row_index=p.row_index, company=p.company,
                                          message=f"duplicate company row: {p.company} appears {names.count(p.company)} times"))

        placeholder = p.company in entering and p.status == Status.ACTIVE and not (p.ownership or p.latest_post_money or p.prior_mark)
        if placeholder:
            pass   # an all-zero row for a company whose first check is in the feed: M-014 fills it in
        elif not (0.0 < p.ownership <= 1.0) and p.status == Status.ACTIVE and (p.row_index, "Ownership (FD %)") not in refused:
            issues.append(ValidationIssue(rule_id="X-903", severity=Severity.BLOCK, sheet=snapshot.sheet_name,
                                          row_index=p.row_index, company=p.company,
                                          message=f"ownership {p.ownership:.4f} outside (0, 1]"))

        # X-921: a round dated after the measurement date has not happened yet; the mark that rests on it
        # is not a fair value at this close. (Fix the date, or the round belongs in a later activity tab.)
        if p.latest_round > q.measurement_date:
            issues.append(ValidationIssue(rule_id="X-921", severity=Severity.BLOCK, sheet=snapshot.sheet_name,
                                          row_index=p.row_index, company=p.company,
                                          message=(f"Latest Round {p.latest_round.isoformat()} is after the measurement date "
                                                   f"{q.measurement_date.isoformat()}: the book carries a round that has not "
                                                   "happened — fix the date, or move the round to the activity tab of its quarter")))

        # X-904 prior-mark reconciliation: ownership × post-money must tie to the carrying value
        if p.status == Status.ACTIVE:
            expected = p.ownership * p.latest_post_money
            if abs(expected - p.prior_mark) > tol:
                if p.company in explained:
                    issues.append(ValidationIssue(rule_id="X-904", severity=Severity.REVIEW, blocking=False,
                                                  sheet=snapshot.sheet_name, row_index=p.row_index, company=p.company,
                                                  message=(f"prior mark {p.prior_mark:.2f} departs from ownership × last-round "
                                                           f"post-money = {expected:.2f}; explained by prior-quarter treatment: "
                                                           f"{explained[p.company]}")))
                else:
                    issues.append(ValidationIssue(rule_id="X-904", severity=Severity.BLOCK, sheet=snapshot.sheet_name,
                                                  row_index=p.row_index, company=p.company,
                                                  message=(f"prior mark {p.prior_mark:.2f} does not reconcile to "
                                                           f"ownership × post-money = {expected:.2f} (tol {tol})")))
        else:
            if p.prior_mark != 0:
                issues.append(ValidationIssue(rule_id="X-904", severity=Severity.BLOCK, sheet=snapshot.sheet_name,
                                              row_index=p.row_index, company=p.company,
                                              message=f"{p.status.value} company carries non-zero prior mark {p.prior_mark}"))

        # X-908 cached-formula drift (informational): the sheet's MOIC/runway vs recomputed
        if p.sheet_moic is not None and p.moic is not None and abs(p.sheet_moic - p.moic) > 1e-6:
            issues.append(ValidationIssue(rule_id="X-908", severity=Severity.MONITOR, blocking=False,
                                          sheet=snapshot.sheet_name, row_index=p.row_index, company=p.company,
                                          message=f"sheet MOIC {p.sheet_moic:.4f} != recomputed {p.moic:.4f}"))
        if p.sheet_runway is not None and p.runway_months is not None and abs(p.sheet_runway - p.runway_months) > 1e-6:
            issues.append(ValidationIssue(rule_id="X-908", severity=Severity.MONITOR, blocking=False,
                                          sheet=snapshot.sheet_name, row_index=p.row_index, company=p.company,
                                          message=f"sheet runway {p.sheet_runway:.2f} != recomputed {p.runway_months:.2f}"))

    if snapshot.unknown_columns:
        issues.append(ValidationIssue(rule_id="X-910", severity=Severity.MONITOR, blocking=False, sheet=snapshot.sheet_name,
                                      message=f"unknown column(s) recorded, not used: {list(snapshot.unknown_columns)}"))

    # --- Activity tab
    issues.extend(_issue_from(c) for c in feed.corrections)
    refused = _percent_blocked(feed.corrections)
    # An ambiguous event type is already a blocking X-914 that names the candidates; the
    # generic "no handler" X-909 on the same row would only repeat it.
    ambiguous_rows = {c.row_index for c in feed.corrections if c.kind == "ambiguous" and c.column == "Event"}
    seen_events: set[tuple] = set()
    for e in feed.events:
        currency = _currency_in_text(e, feed)
        if currency is not None:
            issues.append(currency)

        if e.company not in book:
            if e.event_type == EventType.NEW_INVESTMENT.value:
                fund = infer_fund(e.notes, e.detail)
                issues.append(ValidationIssue(rule_id="X-918", severity=Severity.REVIEW, blocking=False, sheet=feed.sheet_name,
                                              row_index=e.row_index, company=e.company,
                                              message=(f"new investment in {e.company}, not in the Portfolio tab: the engine "
                                                       f"creates the position (M-014) in fund {fund!r}")))
                # The position will be created from this row, so the row's numbers are the whole position:
                # they get the same domain checks as a book company's.
                issues.extend(_money_domain_issues(e, EventType.NEW_INVESTMENT.value, feed, refused, positive_value=True))
            else:
                issues.append(ValidationIssue(rule_id="X-901", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                              row_index=e.row_index, company=e.company,
                                              message=f"activity references a company not in the book: {e.company}"))
            continue
        pos = book[e.company]

        if e.extra.get("date_missing") or e.extra.get("date_unreadable"):
            why = (f"Date {e.extra['date_unreadable']!r} is not a date" if e.extra.get("date_unreadable")
                   else "Date is blank; an event needs a date to be placed in the quarter")
            issues.append(ValidationIssue(rule_id="X-902", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                          row_index=e.row_index, company=e.company, message=why))
        elif e.date > q.window_end:
            # A transaction dated after the measurement date is not evidence at the measurement date.
            issues.append(ValidationIssue(rule_id="X-905", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                          row_index=e.row_index, company=e.company,
                                          message=(f"event dated {e.date} is after the measurement date {q.window_end}; "
                                                   "it cannot be applied to this quarter")))
        elif e.date < q.window_start - grace:
            issues.append(ValidationIssue(rule_id="X-905", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                          row_index=e.row_index, company=e.company,
                                          message=(f"event dated {e.date} is more than {grace.days} days before the quarter "
                                                   f"window {q.window_start}..{q.window_end}; it belongs to a closed quarter "
                                                   "or the date is wrong")))
        elif e.date < q.window_start:
            issues.append(ValidationIssue(rule_id="X-905", severity=Severity.REVIEW, blocking=False, sheet=feed.sheet_name,
                                          row_index=e.row_index, company=e.company,
                                          message=(f"event dated {e.date} is outside the quarter window {q.window_start}..{q.window_end}; "
                                                   "applied as a transaction missed at the last close")))

        key = (e.company, e.event_type, e.date, e.value)
        if key in seen_events:
            issues.append(ValidationIssue(rule_id="X-906", severity=Severity.REVIEW, blocking=False, sheet=feed.sheet_name,
                                          row_index=e.row_index, company=e.company,
                                          message="duplicate event (same company, type, date, value)"))
        seen_events.add(key)

        if pos.status != Status.ACTIVE and e.event_type not in _ALLOWED_ON_TERMINAL.get(pos.status, frozenset()):
            issues.append(ValidationIssue(rule_id="X-907", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                          row_index=e.row_index, company=e.company,
                                          message=f"activity on a company already {pos.status.value}"))

        if e.event_type not in handled:
            if e.row_index in ambiguous_rows:
                continue
            issues.append(ValidationIssue(rule_id="X-909", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                          row_index=e.row_index, company=e.company,
                                          message=f"unrecognised event type {e.event_type!r}; no registered handler (see M-999)"))
            continue
        if e.event_type not in KNOWN_EVENT_TYPES:
            # Handled by a declarative rule: its formula decides what it needs, and a row that lacks a
            # field the formula reads is refused here rather than failing inside the rule.
            needed = sorted(formula_fields.get(e.event_type, ()))
            if needed and e.value is None:
                issues.append(ValidationIssue(rule_id="X-902", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                              row_index=e.row_index, company=e.company,
                                              message=(f"{e.event_type} is missing {_FORMULA_ROW_FIELDS[needed[0]]!r}, which its "
                                                       f"rule's formula reads as {' / '.join(needed)}")))
            issues.extend(_money_domain_issues(e, e.event_type, feed, refused, positive_value=False))
            continue

        et = EventType(e.event_type)
        if et == EventType.PRICED_ROUND:
            if e.value is None:
                issues.append(ValidationIssue(rule_id="X-902", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                              row_index=e.row_index, company=e.company,
                                              message="priced round is missing post-money"))
            if e.ownership_after is None:
                issues.append(ValidationIssue(rule_id="X-902", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                              row_index=e.row_index, company=e.company,
                                              message="priced round is missing HC ownership after"))
        if et in (EventType.IPO, EventType.SECONDARY) and e.ownership_after is None:
            issues.append(ValidationIssue(rule_id="X-902", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                          row_index=e.row_index, company=e.company,
                                          message=f"{et.value} is missing HC ownership after"))
        if et in (EventType.ACQ_CLOSED, EventType.ACQ_ANNOUNCED, EventType.IPO) and e.value is None:
            issues.append(ValidationIssue(rule_id="X-902", severity=Severity.BLOCK, sheet=feed.sheet_name,
                                          row_index=e.row_index, company=e.company,
                                          message=f"{et.value} is missing a deal value / market cap"))
        issues.extend(_money_domain_issues(e, et.value, feed, refused, positive_value=et in _VALUE_MUST_BE_POSITIVE))

    if feed.unknown_columns:
        issues.append(ValidationIssue(rule_id="X-910", severity=Severity.MONITOR, blocking=False, sheet=feed.sheet_name,
                                      message=f"unknown column(s) recorded, not used: {list(feed.unknown_columns)}"))
    return issues
