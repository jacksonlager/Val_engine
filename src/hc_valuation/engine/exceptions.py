"""Layer 2 — exception rules (X-2xx … X-4xx) and escalation.

These never change a mark. They answer one question per company: should a human look
at this before it is booked? The severity test for every rule is *could a reviewer
change the booked number?* — if not, it is MONITOR however interesting.
"""
from __future__ import annotations

import re

from ..config import RuleConfig
from .inputs import Event, EventType
from .marking import months_between
from .models import OpenItemKind, Disposition, Flag, MarketData, Severity
from .state import Suggest, Working


def assess_carry_side(w: Working, cfg: RuleConfig, market: MarketData) -> None:
    """Staleness, growth, liquidity and mark-vs-performance screens on the post-roll state."""
    if w.terminal:
        return  # a wound-down company does not need a runway flag
    x = cfg.exceptions
    md = cfg.quarter.measurement_date
    p = w.pos
    # A signed, unclosed acquisition (M-050) is a fresh price test on the whole company; asking the
    # committee whether the 2021 round is "still fair value" beside a signed $133M agreement is noise.
    deal_priced = any(i.kind == OpenItemKind.PENDING_ACQUISITION for i in w.open_items)

    # ---- X-201 / X-202 staleness (not applicable to listed positions: they have a daily price)
    if not w.listed and deal_priced:
        age = months_between(w.staleness_anchor, md)
        if age > x.staleness.monitor_months:
            w.flag("X-201", "staleness", Severity.MONITOR,
                   f"Last priced {age} months ago ({w.staleness_anchor.isoformat()}); the signed acquisition this quarter is the "
                   "price test now, so the age of the round is context only while the deal is pending.",
                   months=age, anchor=w.staleness_anchor, superseded_by="pending acquisition")
    elif not w.listed:
        age = months_between(w.staleness_anchor, md)
        if age > x.staleness.review_months:
            w.flag("X-202", "staleness", Severity.REVIEW,
                   f"The mark rests on a round that closed {age} months ago, on {w.staleness_anchor.isoformat()}. Companies at this "
                   "stage normally reprice every 18–24 months, so this valuation predates two funding cycles and probably the "
                   "business it describes.",
                   points=(f"The mark rests on a round **{age} months old** ({w.staleness_anchor.isoformat()}).",
                           "Companies at this stage normally **reprice every 18–24 months**.",
                           "This price **predates two funding cycles** — and probably the business it describes."),
                   suggestions=(
                       Suggest("as_proposed", "Keep the mark as proposed.", ("No transaction or metric in the file says the value moved.", "Staleness alone is not evidence of a decline."), "proposed"),
                       Suggest("calibrate", "Calibrate the mark to public comps.", ("Comps have repriced since the round; the calibration is already computed (M-080).", "Keeps a stale Level 3 mark tied to something observable."), "alternative", value="calibrated_to_comps"),
                   ),
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
                   points=(f"Revenue is **shrinking {g:+.0%}** year on year.",
                           "The mark comes from a round **priced on growth that is no longer happening**.",
                           "The **thesis behind the price is materially broken**."),
                   suggestions=(
                       Suggest("as_proposed", "Keep the mark as proposed.", ("The last round is still the latest priced transaction.", "The decline is recorded and will price into the next round."), "proposed"),
                       Suggest("to_cost", "Mark down to invested cost pending the next round.", ("A round priced on growth does not hold when revenue shrinks.", "Cost is a defensible floor until a new price exists."), "cost"),
                   ),
                   action=f"Confirm the mark survives a {abs(g):.0%} revenue decline.", arr_growth=g)
        elif g < x.arr_growth.monitor_below:
            w.flag("X-301", "growth", Severity.MONITOR, f"Revenue is down {g:+.0%} year on year — mild, but the wrong direction.", arr_growth=g)

    # ---- X-303 / X-304 runway, recomputed and aged by the reporting lag
    rw = p.runway_months
    aged = None
    # The cash figure is as of the metrics date (late in the quarter, `reporting_lag_months` before
    # the close). A financing that closed this quarter is not necessarily in it — the workbook
    # carries HC's cheque, not the round size — so the screen says so rather than guessing a number.
    raised = [(d, kind, inv) for d, kind, inv in w.financings]
    raised_txt = ""
    if raised:
        parts = [f"{kind.lower()} on {d.isoformat()}" + (f" (HC put in ${inv:.2f}M)" if inv else "") for d, kind, inv in raised]
        raised_txt = (f" A financing closed this quarter — {'; '.join(parts)} — and the cash figure may predate it; the round "
                      "size is not in the workbook, so the runway here is pre-raise.")
    if rw is not None:
        # aged for the reporting lag; a company already out of cash has zero months, not minus one
        aged = max(0.0, rw - cfg.metrics.reporting_lag_months)
        if aged < x.runway.review_below_mo:
            w.flag("X-304", "liquidity", Severity.REVIEW,
                   f"About {aged:.1f} months of cash left (${p.cash:.1f}M against ${p.net_burn:.2f}M a month, aged "
                   f"{cfg.metrics.reporting_lag_months} month for the reporting lag). The company has to raise before the next "
                   "close, and the round that saves it may well be priced below this mark." + raised_txt,
                   points=(f"About **{aged:.1f} months of cash** left (${p.cash:.1f}M against ${p.net_burn:.2f}M a month).",
                           (f"A **financing closed this quarter** ({raised[0][1].lower()}, {raised[0][0].isoformat()}); the cash figure may **predate it**."
                            if raised else
                            f"Aged {cfg.metrics.reporting_lag_months} month for the reporting lag — the company **must raise before the next close**."),
                           "The round that saves it **may be priced below this mark**."),
                   suggestions=(
                       Suggest("as_proposed", "Keep the mark as proposed.", ("Cash on hand does not change the last-round price.", "The runway is tracked; the next round will reprice it."), "proposed"),
                       Suggest("to_cost", "Mark down to invested cost pending the raise.", ("A rescue round before the next close is likely to be priced down.", "Cost is a defensible floor when a company must raise to survive."), "cost"),
                   ),
                   action=(f"Confirm the post-raise cash position; the {aged:.1f}-month runway is measured before this quarter's financing."
                           if raised else f"Confirm the mark reflects a company with {aged:.1f} months of cash."),
                   runway_months_aged=round(aged, 2),
                   financings_in_quarter=[{"date": d.isoformat(), "event": kind, "hc_investment": inv} for d, kind, inv in raised])
        elif aged < x.runway.monitor_below_mo:
            w.flag("X-303", "liquidity", Severity.MONITOR,
                   f"About {aged:.1f} months of cash left — enough to reach a raise, worth watching." + raised_txt,
                   runway_months_aged=round(aged, 2),
                   financings_in_quarter=[{"date": d.isoformat(), "event": kind, "hc_investment": inv} for d, kind, inv in raised])

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
            usable = comp is not None and (not x.multiple.require_live_comps or comp.source.startswith("live:"))
            if x.multiple.mode == "relative_to_comps" and usable:
                hi, lo = comp.ev_to_arr * x.multiple.high_x_comp, comp.ev_to_arr * x.multiple.low_x_comp
                comp_txt = f" (bounds {lo:.1f}×–{hi:.1f}× around the {comp.ev_to_arr:.1f}× live sector median)"
            elif comp is not None:
                comp_txt = f" (sector comp {comp.ev_to_arr:.1f}×)"
            if mult > hi:
                w.flag("X-401", "valuation", Severity.MONITOR,
                       f"Carried at {mult:.0f}× revenue{comp_txt}" + (f", growing {g:+.0%}" if g is not None else "")
                       + ". On this screen the mark looks generous — a rough cross-check, not a valuation.",
                       implied_multiple=round(mult, 2), threshold=hi,
                       basis=("live sector median" if (x.multiple.mode == "relative_to_comps" and usable) else "absolute policy bound"))
            elif mult < lo:
                w.flag("X-402", "valuation", Severity.MONITOR,
                       f"Carried at {mult:.1f}× revenue{comp_txt}" + (f", growing {g:+.0%}" if g is not None else "")
                       + ". On this screen the mark looks understated — undermarking is the same failure with the opposite sign.",
                       implied_multiple=round(mult, 2), threshold=lo,
                       basis=("live sector median" if (x.multiple.mode == "relative_to_comps" and usable) else "absolute policy bound"))

    # ---- X-404 MOIC outlier on a stale round
    inv = w.invested
    if inv and not w.listed:
        moic = (w.proposed_mark + p.realized + w.realized_quarter) / inv
        age = months_between(w.staleness_anchor, md)
        if moic > x.moic.monitor_above and age > x.staleness.monitor_months:
            w.flag("X-404", "valuation", Severity.MONITOR,
                   f"Carrying a {moic:.1f}× return on a price set {age} months ago — a large unrealised gain resting on an old mark.",
                   moic=round(moic, 2), months=age)

    # ---- X-405 mark no longer squares with performance: an old price AND a live screen against it.
    # Each half is MONITOR on its own (staleness is not evidence of a move; a screen is not a
    # valuation). Together they are the case the policy exists for: a reviewer could change
    # this number, so it is REVIEW.
    if x.performance_gap.enabled and not w.listed:
        ids = {f.rule_id for f in w.flags}
        age = months_between(w.staleness_anchor, md)
        screens = {
            "X-401": "carried above the multiple screen", "X-402": "carried below the multiple screen",
            "X-404": "an outsized unrealised gain", "X-301": "revenue now shrinking",
        }
        hits = [screens[k] for k in ("X-401", "X-402", "X-404", "X-301") if k in ids]
        if age > x.staleness.monitor_months and hits and not (ids & {"X-302", "X-202"}):
            # (X-302 / X-202 already put the position in REVIEW on their own; no double count)
            mult_txt = f"{w.latest_post / p.arr:.0f}× revenue" if p.arr else "an unscreenable multiple"
            w.flag("X-405", "valuation", Severity.REVIEW,
                   f"The price behind this mark is {age} months old, and the current numbers disagree with it: "
                   f"{'; '.join(hits)} ({mult_txt}"
                   + (f", growing {g:+.0%}" if g is not None else "") + "). Neither fact alone would move the "
                   "mark — an old price is not a wrong price, and a screen is not a valuation — but an old price "
                   "that today's performance argues with is exactly the case a reviewer should reprice or affirm.",
                   points=(f"Price is **{age} months old** — and today's numbers **argue with it**.",
                           f"Screen: **{'; '.join(hits)}** ({mult_txt}" + (f", growing {g:+.0%}" if g is not None else "") + ").",
                           "Two independent signals point the same way: **affirm or reprice**."),
                   suggestions=(
                       Suggest("as_proposed", "Affirm the last-round mark as proposed.",
                               ("No transaction has repriced the company; the round is still the last real price.",
                                "The screen is a cross-check, not a valuation."), "proposed"),
                       Suggest("calibrate", "Calibrate the mark to public comps.",
                               ("Ties a stale Level 3 price to how comparable multiples have moved since the round.",
                                "Uses the M-080 calibration the engine already computed."), "alternative", value="calibrated_to_comps"),
                       Suggest("to_cost", "Mark down to invested cost pending a new price.",
                               ("A defensible floor when the last price no longer describes the business.",
                                "Reverses at the next priced round."), "cost"),
                   ),
                   action="Affirm or reprice: the last-round price is stale and the performance screen disagrees with it.",
                   months=age, screens=[k for k in ("X-401", "X-402", "X-404", "X-301") if k in ids])


# A lock-up is the expected consequence of a listing, and M-040 already carries it as an open
# item; on any other event the word means a restriction the schema does not hold.
# Fallback when the policy names no exemptions: a listing's lock-up is M-040's open item.
_DEFAULT_EXEMPT = {EventType.IPO.value: ("lock-up",), EventType.DIRECT_LISTING.value: ("lock-up",)}


from .textscreen import NEGATIONS as _NEGATIONS, term_in as _term_in  # noqa: E402,F401 — one reader of free text, shared with marking.py


def _exempted(term: str, exempt: set[str]) -> bool:
    """`lock-up` in the exemptions covers `lockup` and `lock up`; `warrant` covers `warrants`."""
    norm = lambda t: re.sub(r"[\s-]+", "", t)  # noqa: E731
    return any(norm(term).startswith(norm(x)) or norm(x).startswith(norm(term)) for x in exempt)


def screen_notes(w: Working, events: list[Event], cfg: RuleConfig) -> None:
    """X-105 — free text carrying a treatment the schema cannot encode. Escalates; never parses a number."""
    if not cfg.note_screen.enabled or not cfg.note_screen.terms:
        return
    terms = [t.lower() for t in cfg.note_screen.terms]
    exempt_map = cfg.note_screen.exempt or _DEFAULT_EXEMPT
    for e in events:
        text = f"{e.detail} {e.notes}".lower()
        # a term that names the event type itself ("Earn-out True-up", a promoted custom rule) is
        # the treatment, not an unhandled one
        exempt = {x.lower() for x in exempt_map.get(e.event_type, ())} | {e.event_type.lower()}
        hits = [t for t in terms if _term_in(t, text) and not _exempted(t, exempt) and not _term_in(t, e.event_type.lower())]
        if hits:
            w.flag("X-105", "notes", Severity.REVIEW,
                   f"The note on this row mentions {', '.join(hits)} — terms the columns cannot represent, so no rule has taken "
                   f"account of them: \"{e.notes or e.detail}\"",
                   points=(f"The row note mentions **{', '.join(hits)}** — terms the columns cannot represent.",
                           "**No rule has taken account of them**; the mark ignores the terms entirely.",
                           f"The note has to be read: \"{(e.notes or e.detail)[:120]}\""),
                   suggestions=(
                       Suggest("as_proposed", "Book as proposed; reflect the note's terms by override once read.", ("The engine applied every term the columns can hold.", "Unrepresented terms need a human number, not a guess."), "proposed"),
                   ),
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
    review_families = {f.family for f in flags if f.severity == Severity.REVIEW and f.rule_id not in addressed}
    if terminal and not review_families and not any(f.severity == Severity.MONITOR for f in flags):
        return Disposition.CLEAR          # realized or written off, nothing left to check (post-exit cash stays a watch item)
    if len(review_families) >= cfg.exceptions.escalation.review_rules_to_block and not overridden:
        return Disposition.BLOCK
    if review_families:
        return Disposition.REVIEW
    if any(f.severity == Severity.MONITOR for f in flags) or overridden:
        return Disposition.MONITOR
    return Disposition.CLEAR
