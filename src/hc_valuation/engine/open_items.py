"""E-07 — open items register.

Unfinished business that must survive the quarter boundary: outstanding notes, pending
announced deals, disclosed term sheets, lock-up expiries. Items carried in from a prior
run age by one quarter and escalate on their own once they have sat past policy.
"""
from __future__ import annotations

from ..config import RuleConfig
from .models import OpenItem, OpenItemKind, Severity
from .state import Suggest, Working


def _threshold(kind: OpenItemKind, cfg: RuleConfig) -> int | None:
    o = cfg.open_items
    return {
        OpenItemKind.PENDING_ACQUISITION: o.announced_deal_stale_quarters,
        OpenItemKind.TERM_SHEET: o.term_sheet_stale_quarters,
        OpenItemKind.CONVERTIBLE_NOTE: o.note_unconverted_quarters,
        OpenItemKind.IPO_LOCKUP: None,   # resolves on its own date
        OpenItemKind.ACQUIRER_SHARES: o.announced_deal_stale_quarters,   # shares of a buyer still unpriced
        OpenItemKind.UNCONFIRMED_EXIT: o.unconfirmed_exit_stale_quarters,  # a closed exit whose cash never arrived
        OpenItemKind.DEBT: o.note_unconverted_quarters,                     # a loan HC made ages like an unconverted note
    }[kind]


_SURVIVES_CLOSE = {OpenItemKind.UNCONFIRMED_EXIT, OpenItemKind.ACQUIRER_SHARES}


def carry_prior_items(w: Working, prior: list[OpenItem], cfg: RuleConfig, resolved_kinds: set[OpenItemKind]) -> None:
    """Age items opened in earlier quarters; drop those the current quarter's events resolved;
    escalate those that have sat past policy."""
    md = cfg.quarter.measurement_date
    for item in prior:
        if item.company != w.pos.company or item.kind in resolved_kinds:
            continue
        # A closed position resolves the items that needed it open — a note, a term sheet, a
        # pending deal. It does not resolve the two kinds that only exist *because* it closed: an
        # exit whose cash has not all arrived, and a buyer's shares still unpriced. Those carry
        # until the proceeds are recorded or a person writes them off (the Q3 → Q4 roll lost a
        # $3.14M escrow question on an acquired company this way).
        if w.terminal and item.kind not in _SURVIVES_CLOSE:
            continue
        if item.kind == OpenItemKind.IPO_LOCKUP and item.expected_resolution and item.expected_resolution <= md:
            continue  # expired quietly
        age = item.age_quarters + 1
        limit = _threshold(item.kind, cfg)
        escalated = limit is not None and age >= limit
        aged = item.model_copy(update={"age_quarters": age, "escalated": escalated})
        w.open_items.append(aged)
        if escalated:
            w.flag("E-07", "treatment", Severity.REVIEW,
                   f"A {item.kind.value.replace('_', ' ')} opened {item.opened.isoformat()} is still unresolved {age} quarter(s) "
                   f"later ({item.detail}). Something pending this long is a different fact from something signed last month.",
                   points=(f"A {item.kind.value.replace('_', ' ')} opened {item.opened.isoformat()} is **still unresolved**.",
                           f"It has been open **{age} quarter(s)** ({item.detail}).",
                           "Something pending this long is a **different fact** from something signed last month."),
                   suggestions=(
                       Suggest("as_proposed", "Keep the mark as proposed and chase the item.", ("The delay alone does not change the price basis.", "The item keeps ageing and escalating until it resolves."), "proposed"),
                   ),
                   action=f"Chase the {item.kind.value.replace('_', ' ')}, or reflect the delay in the mark.",
                   kind=item.kind.value, age_quarters=age, opened=item.opened)


RESOLVES: dict[str, set[OpenItemKind]] = {
    "Priced Equity Round": {OpenItemKind.CONVERTIBLE_NOTE, OpenItemKind.TERM_SHEET},   # a note converts into the round
    # a closing (with its proceeds) confirms an exit, so it resolves everything; a shutdown resolves
    # what needed the company open, never the two kinds that exist because an exit already happened
    "Acquisition (Closed)": {k for k in OpenItemKind},
    "Shutdown": {k for k in OpenItemKind} - _SURVIVES_CLOSE,
    "IPO": {OpenItemKind.CONVERTIBLE_NOTE, OpenItemKind.TERM_SHEET, OpenItemKind.PENDING_ACQUISITION},
    "Direct Listing": {OpenItemKind.CONVERTIBLE_NOTE, OpenItemKind.TERM_SHEET, OpenItemKind.PENDING_ACQUISITION},
    "Acquisition (Terminated)": {OpenItemKind.PENDING_ACQUISITION},
    "Note Repaid": {OpenItemKind.CONVERTIBLE_NOTE, OpenItemKind.DEBT},
    "Term Sheet Withdrawn": {OpenItemKind.TERM_SHEET},
    "Lock-up Expiry": {OpenItemKind.IPO_LOCKUP},
}
