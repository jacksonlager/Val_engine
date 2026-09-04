"""Layer 2 — exception rules (X-2xx … X-4xx) and escalation.

These never change a mark. They answer one question per company: should a human look
at this before it is booked? The severity test for every rule is *could a reviewer
change the booked number?* — if not, it is MONITOR however interesting.
"""
from __future__ import annotations

from ..config import RuleConfig
from .inputs import Event, EventType
from .marking import months_between
from .models import Disposition, Flag, MarketData, Severity
from .state import Working


def assess_carry_side(w: Working, cfg: RuleConfig, market: MarketData) -> None:
    """Staleness, growth, liquidity and mark-vs-performance screens on the post-roll state."""
    if w.terminal:
        return  # a wound-down company does not need a runway flag
    x = cfg.exceptions
    md = cfg.quarter.measurement_date
    p = w.pos

    # ---- X-201 / X-202 staleness (not applicable to listed positions: they have a daily price)
    if not w.listed:
        age = months_between(w.staleness_anchor, md)
        if age > x.staleness.review_months:
            w.flag("X-202", "staleness", Severity.REVIEW,
                   f"The mark rests on a round that closed {age} months ago, on {w.staleness_anchor.isoformat()}. Companies at this "
                   "stage normally reprice every 18–24 months, so this valuation predates two funding cycles and probably the "
                   "business it describes.",
                   action=f"Decide whether a price set {age} months ago is still fair value.",
                   months=age, anchor=w.staleness_anchor)
        elif age > x.staleness.monitor_months:
            w.flag("X-201", "staleness", Severity.MONITOR,
                   f"Last priced {age} months ago ({w.staleness_anchor.isoformat()}) — normal at this stage, worth watching.",
                   months=age, anchor=w.staleness_anchor)

    # ---- X-301 / X-302 ARR contraction
    g = p.arr_growth
    if g is not None:
        if g < x.arr_growth.review_below:
            w.flag("X-302", "growth", Severity.REVIEW,
                   f"Revenue is shrinking {g:+.0%} year on year. The mark comes from a round priced on growth that is no longer "
                   "happening, so the thesis behind it is materially broken.",
                   action=f"Confirm the mark survives a {abs(g):.0%} revenue decline.", arr_growth=g)
        elif g < x.arr_growth.monitor_below:
            w.flag("X-301", "growth", Severity.MONITOR, f"Revenue is down {g:+.0%} year on year — mild, but the wrong direction.", arr_growth=g)

    # ---- X-303 / X-304 runway, recomputed and aged by the reporting lag
    rw = p.runway_months
    aged = None
    if rw is not None:
        aged = rw - cfg.metrics.reporting_lag_months
        if aged < x.runway.review_below_mo:
            w.flag("X-304", "liquidity", Severity.REVIEW,
                   f"About {aged:.1f} months of cash left (${p.cash:.1f}M against ${p.net_burn:.2f}M a month, aged "
                   f"{cfg.metrics.reporting_lag_months} month for the reporting lag). The company has to raise before the next "
                   "close, and the round that saves it may well be priced below this mark.",
                   action=f"Confirm the mark reflects a company with {aged:.1f} months of cash.",
                   runway_months_aged=round(aged, 2))
        elif aged < x.runway.monitor_below_mo:
            w.flag("X-303", "liquidity", Severity.MONITOR,
                   f"About {aged:.1f} months of cash left — enough to reach a raise, worth watching.", runway_months_aged=round(aged, 2))

    # ---- X-401 / X-402 / X-403 mark vs performance (a screen, not a valuation → MONITOR)
    arr = p.arr
    if arr is not None and w.latest_post:
        if arr < x.multiple.min_arr:
            w.flag("X-403", "valuation", Severity.MONITOR,
                   f"At ${arr:.1f}M of revenue the multiple screen produces numbers that mean nothing except that the denominator is "
                   "small. Companies this early are valued on team and product, so the screen is skipped rather than reported.",
                   arr=arr)
        else:
            mult = w.latest_post / arr
            hi, lo = x.multiple.absolute_high, x.multiple.absolute_low
            comp = market.comps.get(p.sector)
            comp_txt = ""
            if x.multiple.mode == "relative_to_comps" and comp is not None:
                hi, lo = comp.ev_to_arr * x.multiple.high_x_comp, comp.ev_to_arr * x.multiple.low_x_comp
                comp_txt = f" (sector comp {comp.ev_to_arr:.1f}×)"
            elif comp is not None:
                comp_txt = f" (sector comp {comp.ev_to_arr:.1f}×)"
            if mult > hi:
                w.flag("X-401", "valuation", Severity.MONITOR,
                       f"Carried at {mult:.0f}× revenue{comp_txt}" + (f", growing {g:+.0%}" if g is not None else "")
                       + ". On this screen the mark looks generous — a rough cross-check, not a valuation.",
                       implied_multiple=round(mult, 2), threshold=hi)
            elif mult < lo:
                w.flag("X-402", "valuation", Severity.MONITOR,
                       f"Carried at {mult:.1f}× revenue{comp_txt}" + (f", growing {g:+.0%}" if g is not None else "")
                       + ". On this screen the mark looks understated — undermarking is the same failure with the opposite sign.",
                       implied_multiple=round(mult, 2), threshold=lo)

    # ---- X-404 MOIC outlier on a stale round
    inv = w.invested
    if inv and not w.listed:
        moic = (w.proposed_mark + p.realized + w.realized_quarter) / inv
        age = months_between(w.staleness_anchor, md)
        if moic > x.moic.monitor_above and age > x.staleness.monitor_months:
            w.flag("X-404", "valuation", Severity.MONITOR,
                   f"Carrying a {moic:.1f}× return on a price set {age} months ago — a large unrealised gain resting on an old mark.",
                   moic=round(moic, 2), months=age)


# A lock-up is the expected consequence of a listing, and M-040 already carries it as an open
# item; on any other event the word means a restriction the schema does not hold.
_LISTING_EVENTS = frozenset({EventType.IPO.value, EventType.DIRECT_LISTING.value})
_LISTING_EXEMPT_TERMS = frozenset({"lock-up", "lockup", "lock up"})


def screen_notes(w: Working, events: list[Event], cfg: RuleConfig) -> None:
    """X-105 — free text carrying a treatment the schema cannot encode. Escalates; never parses a number."""
    if not cfg.note_screen.enabled or not cfg.note_screen.terms:
        return
    terms = [t.lower() for t in cfg.note_screen.terms]
    for e in events:
        text = f"{e.detail} {e.notes}".lower()
        hits = [t for t in terms if t in text
                and not (t in _LISTING_EXEMPT_TERMS and e.event_type in _LISTING_EVENTS)]
        if hits:
            w.flag("X-105", "treatment", Severity.REVIEW,
                   f"The note on this row mentions {', '.join(hits)} — terms the columns cannot represent, so no rule has taken "
                   f"account of them: \"{e.notes or e.detail}\"",
                   action="Read the note on the activity row; it describes a treatment the schema cannot hold.",
                   terms=hits, row_index=e.row_index)


def disposition(flags: list[Flag], terminal: bool, cfg: RuleConfig,
                addressed: set[str] | None = None, overridden: bool = False) -> Disposition:
    """`addressed` are the rule ids a committee override (E-01) explicitly resolves; an override
    with an empty list resolves every BLOCK on the position. The flags stay visible — the
    position simply stops *waiting*. An overridden position is never below MONITOR, so the
    decision itself remains in the queue for the record."""
    addressed = addressed or set()
    blocks = [f for f in flags if f.severity == Severity.BLOCK]
    if overridden and not addressed:
        blocks = []
    else:
        blocks = [f for f in blocks if f.rule_id not in addressed]
    if blocks:
        return Disposition.BLOCK          # a block survives even a terminal event (e.g. exit with no proceeds)
    if terminal:
        return Disposition.CLEAR
    review_families = {f.family for f in flags if f.severity == Severity.REVIEW and f.rule_id not in addressed}
    if len(review_families) >= cfg.exceptions.escalation.review_rules_to_block and not overridden:
        return Disposition.BLOCK
    if review_families:
        return Disposition.REVIEW
    if any(f.severity == Severity.MONITOR for f in flags) or overridden:
        return Disposition.MONITOR
    return Disposition.CLEAR
