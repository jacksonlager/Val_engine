"""Three questions a reviewer keeps separate, and the engine should too.

* **Readiness** — can this be booked? `Blocked` / `Needs Review` / `Ready`, one per position.
* **Action** — what happened to it? `Carry` / `Revalue` / `New investment` / `Partial exit` /
  `Full exit` / `Write-off`.
* **Approval** — has a person signed it? Nothing is "booked" before the quarter is published.

They were previously one field. `Disposition` counts *findings* (a position with four flags
still has one readiness), and the review tool was reading a BLOCK on a missing input and a
BLOCK on a judgment call as the same state, which they are not: one cannot be booked at any
price, the other has a defensible number that a committee must ratify.

`monitor` is a tag, not a bucket. A position can be Ready and still be worth watching.
"""
from __future__ import annotations

from .models import Approval, CompanyResult, Flag, OverrideRecord, Readiness, Severity, ValuationAction

# A finding that says "the engine did not have what it needed". No price for a listed holding,
# a row the reader refused, consideration in an acquirer's stock whose terms are not in the feed,
# a reorganisation whose recovery nobody has estimated: in each the missing input is the reason,
# and no amount of committee judgment produces a *supported* mark until it arrives.
MISSING_INPUT_RULES = frozenset({
    "X-900",   # a row the ingest layer refused; the position carries its prior mark
    "X-112",   # acquisition settled in acquirer stock — listing, share count and lock-up unknown
    "X-113",   # listed position with no measurement-date price
    "X-116",   # Chapter 11: the recovery estimate is not in the workbook
    "X-918",   # a company created from activity with no Portfolio row behind it
    "M-999",   # an event type no rule recognises: the treatment is missing, and E-09 exists to draft it
})

# One marking rule per shape of quarter. Anything not named here re-priced the position.
_ACTION_BY_RULE = {
    "M-000": ValuationAction.CARRY,
    "M-041": ValuationAction.CARRY,          # a listed holding carried at its close
    "M-014": ValuationAction.NEW_INVESTMENT,
    "M-030": ValuationAction.PARTIAL_EXIT,   # secondary sale of part of the stake
    "M-020": ValuationAction.FULL_EXIT,
    "M-024": ValuationAction.FULL_EXIT,      # acquisition settled in shares: the position is realised
    "M-021": ValuationAction.WRITE_OFF,
    "M-025": ValuationAction.WRITE_OFF,      # Chapter 11 wind-down
}
_TERMINAL_ACTIONS = (ValuationAction.FULL_EXIT, ValuationAction.WRITE_OFF)


def unresolved(flags: tuple[Flag, ...], override: OverrideRecord | None) -> list[Flag]:
    """Flags a recorded decision has not addressed. An override naming no rule ids resolves the
    BLOCK-severity findings only — it never silently clears a REVIEW nobody mentioned — and
    never a missing-input finding either: a number written against a position whose price or
    row is not on file does not make the price or the row appear. Only a decision that names
    that rule, by a person who has seen what is missing, moves it on."""
    addressed = set(override.rule_ids_addressed) if override else set()
    if override and not addressed:
        return [f for f in flags if f.severity == Severity.REVIEW or f.rule_id in MISSING_INPUT_RULES]
    return [f for f in flags if f.rule_id not in addressed and f.severity != Severity.MONITOR]


def readiness_of(flags: tuple[Flag, ...], override: OverrideRecord | None, *,
                 provisional_rule: str | None = None) -> Readiness:
    """Blocked when an input is missing; Needs Review when a judgment is; else Ready.

    `provisional_rule` is the rule whose mark stands in for an input that is not on file. It
    blocks — a stand-in is never a final mark, and the engine will not propose booking one — but
    a committee that names that rule in a decision has knowingly accepted the stand-in, and the
    position moves on. Blocking a book forever on a price nobody can fetch would be a worse
    failure than the one this prevents; the decision is on the ledger either way."""
    addressed = set(override.rule_ids_addressed) if override else set()
    open_flags = unresolved(flags, override)
    if provisional_rule is not None and provisional_rule not in addressed:
        return Readiness.BLOCKED
    if any(f.rule_id in MISSING_INPUT_RULES for f in open_flags):
        return Readiness.BLOCKED
    return Readiness.NEEDS_REVIEW if open_flags else Readiness.READY


def action_of(rule_ids: tuple[str, ...], *, terminal: bool, realized_quarter: float,
              new_investment: float, already_terminal: bool = False) -> ValuationAction:
    """The shape of the quarter, from the rules that actually ran on the position.

    A company that was already acquired or shut down at the *prior* close did not exit again:
    it carries at zero, and cash arriving afterwards is a distribution against a position that
    left the book in an earlier quarter."""
    for rid in reversed(rule_ids):                     # the last rule to touch the mark decides
        action = _ACTION_BY_RULE.get(rid)
        if action is not None and not already_terminal:
            if action in _TERMINAL_ACTIONS or not terminal:
                return action
    if already_terminal:
        return ValuationAction.CARRY
    if terminal:
        return ValuationAction.FULL_EXIT if realized_quarter > 0 else ValuationAction.WRITE_OFF
    if new_investment > 0:
        return ValuationAction.REVALUE
    return ValuationAction.CARRY if rule_ids in ((), ("M-000",)) else ValuationAction.REVALUE


def approval_of(override: OverrideRecord | None, *, published: bool = False) -> Approval:
    """A decision on file is not an approval, and an approval is not a booking. Only a published
    quarter makes a mark booked, which is why the review tool says "proposed" until then."""
    if published:
        return Approval.PUBLISHED
    return Approval.DECIDED if override is not None else Approval.NONE


def valuation_change(prior_mark: float, closing_mark: float, *, new_investment: float,
                     realized_quarter: float) -> float:
    """The performance half of the quarter's move, on one convention used everywhere:

        closing = opening + new investment + valuation gain/loss − realized proceeds

    so gain/loss is what is left once money in and cash out are taken off. Cindral opened at
    $18.2M, returned $28.2M and closes at zero: 18.2 + 0 + 10.0 − 28.2 = 0, a $10M **gain**.
    Reading the −$18.2M change in carrying value as a loss, which the bridge used to imply, is
    the mistake this exists to prevent."""
    return round(closing_mark - prior_mark - new_investment + realized_quarter, 6)


def summarise(c: CompanyResult) -> str:
    """One plain sentence for a queue row: what happened, and what it needs."""
    if c.readiness is Readiness.BLOCKED:
        return c.provisional_reason or "Missing information — cannot be booked yet"
    if c.readiness is Readiness.NEEDS_REVIEW:
        first = next((f for f in unresolved(c.flags, c.override)), None)
        return (first.action or first.message.split(".")[0]) if first else "Needs a reviewer"
    return "No open exceptions"
