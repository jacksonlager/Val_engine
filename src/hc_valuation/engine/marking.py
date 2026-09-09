"""Layer 1 — mechanical marking rules (M-0xx).

Each rule is a small function that mutates the company's `Working` state and appends
a `MarkStep` explaining exactly what it did and why. Rules raise *treatment* flags
(X-10x) where the right treatment is a policy choice rather than arithmetic; they never
decide the disposition — that is Layer 2's job.

Base identity throughout: mark = FD ownership × post-money.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..config import RuleConfig
from .inputs import Event, EventType, Position, Status
from .models import MarketData, OpenItem, OpenItemKind, Severity
from .registry import rule
from .rerating import SAME_SET, sector_rerating
from .state import Suggest, Working
from .textscreen import any_term_in

# The built-in rules are the base policy and are in force for every quarter the engine is asked to
# value, earlier ones included: a Q2 2026 book that arrives after the Q3 base policy is valued by the
# same rules (found by that exact file — dated 2026-07-01, no rule applied on 30 Jun 2026, not even
# the M-999 fallback, and the engine raised instead of reporting). Only a rule promoted from
# the policy file carries a real `effective_from`, so that a Q4 rule never rewrites a Q3 re-run.
EFFECTIVE = date.min
BASE_RULE_EFFECTIVE = EFFECTIVE
V = "2026Q3.1"

# The config keys are stable identifiers; a rationale a reviewer reads should not contain one.
TREATMENT_WORDS = {
    "probability_weighted": "probability-weighted",
    "full_deal_value": "at the full deal value",
    "hold_prior": "at the prior mark",
}


def months_between(a: date, b: date) -> float:
    """Age in months as a duration, to one decimal: a round dated 2022-09-02 is 48.9 months old on
    2026-09-30 — older than 48 — where calendar-month arithmetic would have said 48 and let it
    slip under a ">48 months" threshold. 30.4375 days per month (365.25 / 12)."""
    return round((b - a).days / 30.4375, 1)


# Every threshold in the policy is a ratio ("beyond 5%", "at or below 80%", "−20% relative",
# "≥ 2×"), and a ratio of two workbook figures is a binary float: 1929.795 / 1837.9 − 1 is
# 0.05000000000000004, so a print stated at exactly the tolerance would fire a "beyond 5%" screen.
# The workbook's own precision is 0.1 $M on a post-money and three decimals on ownership; six
# places is far below either, and the flag already records the ratio to four.
RATIO_PLACES = 6


def ratio(numerator: float, denominator: float) -> float:
    """`numerator / denominator` at the precision a policy comparison can honestly claim."""
    return round(numerator / denominator, RATIO_PLACES)


def ratio_change(numerator: float, denominator: float) -> float:
    """`numerator / denominator − 1`, rounded the same way."""
    return round(numerator / denominator - 1, RATIO_PLACES)


_CAP_PATTERNS = (
    # "$32.0M valuation cap", "$12M post-money cap", "$12M pre-money cap", "$12M cap"
    r"\$([\d.,]+)\s*M?\s*(?:post-money|pre-money|valuation)?\s*cap\b",
    # "cap of $12M", "valuation cap of $12M", "post-money cap $12M", "cap at $12M"
    r"\bcap\s+(?:of\s+|at\s+)?\$([\d.,]+)\s*M?\b",
)


def _cap_from_detail(detail: str) -> float | None:
    """Valuation cap in $M from the Detail text of a note or SAFE. A cap is never a price;
    it is read only so the chain can say how far it sits from the last round."""
    for pat in _CAP_PATTERNS:
        m = re.search(pat, detail, flags=re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:  # pragma: no cover - the pattern only admits digits, dots and commas
                continue
    return None


# Free-text detection for related-party pricing on a priced round (X-117 / X-118).
_HC_LED_TERMS = ("led by hc", "hc led", "hc-led", "human capital led", "human capital-led")
_INSIDER_TERMS = ("insider-led", "insider led", "insider round")

# M-024: an exit whose consideration is the buyer's shares rather than cash.
# Phrases that say the consideration was equity. The bare words "stock" and "shares" were on this
# list and matched as substrings, so "all-cash deal; stockholders approved" and "HC's shares were
# cancelled for cash" both routed a cash exit to the stock-consideration rule and kept a sold
# position on the book at the deal price. Whole-word phrases only, via the negation-aware screen.
_STOCK_TERMS = ("all-stock", "all stock", "stock-for-stock", "stock for stock", "equity consideration",
                "stock consideration", "share consideration", "consideration in shares", "consideration in stock",
                "paid in shares", "paid in stock", "settled in shares", "settled in stock", "in acquirer stock",
                "in acquirer shares", "shares of the acquirer", "shares in the acquirer", "rolled into")

_FUND_RE = re.compile(r"\bFund\s+(III|II|I)\b", flags=re.I)
_STAGE_RE = re.compile(r"\b(Pre-Seed|Seed|Series\s+[A-H](?:\+)?)\b", flags=re.I)


def _text(e: Event) -> str:
    return f"{e.detail} {e.notes}".lower()


def _related_party_flags(w: Working, e: Event, rid: str, cfg: RuleConfig, post: float | None = None,
                         prior_post: float | None = None) -> None:
    """X-117 (REVIEW) when HC led the round: a related-party price is not arm's-length.
    X-118 when the round was insider-led but not by HC: MONITOR, or REVIEW when insiders re-priced
    their own position by `insider_round_review_step_up` or more — a step-up nobody outside tested."""
    text = _text(e)
    hc_led = any(t in text for t in _HC_LED_TERMS)
    insider = any(t in text for t in _INSIDER_TERMS)
    if hc_led or insider:
        w.handled(e, "insider", "internal round", "existing holders", "existing investors", "led by hc", "hc led", "no new investor", "no outside", "inside round")
    if hc_led:
        w.flag("X-117", "related_party", Severity.REVIEW,
               f"The notes say HC led this round ({rid}). A price set by an existing investor that is also the party marking "
               "the position is a related-party price, not an arm's-length one, and ASC 820 asks for an orderly transaction "
               "between market participants.",
               points=("**HC led** the round that set this price.",
                       "A price set by the party marking the position is **not arm's length** (ASC 820).",
                       "Needs an **independent investor** to have set or validated it."),
               suggestions=(
                   Suggest("as_proposed", "Book the round price as proposed.", ("The round is the latest transaction and the price is documented.", "An outside investor's validation can be recorded when it arrives."), "proposed"),
                   Suggest("hold_prior", "Hold the prior mark until an independent investor validates the price.", ("A related-party price is not arm's-length under ASC 820.", "The prior mark is the last price an outside party set."), "prior"),
               ),
               action="Confirm an independent investor set or validated this price.",
               rule=rid, hc_led=True, insider_led=insider)
    elif insider:
        step = ratio(post, prior_post) if (post and prior_post) else None
        limit = cfg.exceptions.indications.insider_round_review_step_up
        if step is not None and step >= limit:
            w.flag("X-118", "related_party", Severity.REVIEW,
                   f"The notes say the round was insider-led ({rid}) and it re-priced the company {step:.1f}× — ${prior_post:.1f}M to "
                   f"${post:.1f}M — with no new investor testing that price. Existing holders marking up their own position is "
                   "weaker evidence than a new lead, and at this step-up a reviewer could reasonably book less.",
                   points=(f"**Insider-led** round re-priced the company **{step:.1f}×** (${prior_post:.1f}M → ${post:.1f}M).",
                           "**No new investor** tested the price.",
                           "A reviewer could reasonably book **less than the round**."),
                   suggestions=(
                       Suggest("as_proposed", "Book the round price as proposed.", ("It is a priced, closed transaction.", "Insiders can still pay a fair price; record the reason."), "proposed"),
                       Suggest("hold_prior", "Hold the prior mark until an outside investor validates the step-up.", ("A step-up nobody outside tested is not a market test.", "The prior mark is the last price an outside party set."), "prior"),
                   ),
                   action=f"Confirm the {step:.1f}× insider step-up reflects a price an outside investor would pay.",
                   rule=rid, insider_led=True, step_up=round(step, 3), threshold=limit)
        else:
            w.flag("X-118", "related_party", Severity.MONITOR,
                   f"The notes say the round was insider-led ({rid}). Existing investors re-pricing their own position is weaker "
                   "evidence than a new lead, though not a related-party price for HC itself.",
                   rule=rid, insider_led=True, step_up=(round(step, 3) if step is not None else None))


def _primary_price_checks(w: Working, e: Event, cfg: RuleConfig, *, post: float, prior_post: float,
                          delta_own: float, implied: float | None) -> None:
    """Two screens on a priced round the workbook lets us do.

    X-119 — the round price does not reconcile to HC's own cheque: `hc_investment ÷ Δownership`
    is the post-money HC actually paid; beyond `indications.cheque_price_tolerance` of the stated
    post it is REVIEW. Ownership is reported to three decimals, so the check only runs where the
    stake bought is big enough (`indications.cheque_check_min_ownership_delta`) for rounding not
    to explain the gap.

    X-122 — a large step-up (`indications.step_up_review_at`, 3×) with no outside investor named
    on the row is REVIEW: nobody the row identifies tested that price. With a new lead named it is
    MONITOR — a fact worth seeing, not a judgment."""
    ind = cfg.exceptions.indications
    round_size = _round_size_from_text(_text(e))
    inv = float(e.hc_investment or 0.0)
    before = float(w.ownership)
    after = float(e.ownership_after) if e.ownership_after is not None else None
    if inv and post and round_size and after is not None and 0 < round_size < post:
        # The text states the round size, so the row can be reconciled properly: the whole round dilutes
        # HC's stake by round ÷ post and the cheque buys cheque ÷ post. "HC's cheque ÷ Δownership" would
        # ignore the dilution and call a clean pro-rata cheque a price error (found on the shipped Q3 book).
        expected = before * (1 - round_size / post) + inv / post
        unit = ind.ownership_rounding
        if abs(after - expected) > max(2 * unit, ind.cheque_ownership_tolerance) and abs(ratio_change(after, expected)) > ind.cheque_price_tolerance:
            implied_pre = round_size * before / max(after - inv / post, 1e-9) if after > inv / post else None
            w.flag("X-119", "treatment", Severity.REVIEW,
                   f"HC's cheque does not reconcile to the row: ${inv:.2f}M into a ${round_size:.1f}M round at ${post:.1f}M post should "
                   f"leave HC at {expected:.1%} ({before:.1%} diluted by the round plus the {inv / post:.1%} bought), but the row says "
                   f"{after:.1%}. One of the cells is wrong — or the ${post:.1f}M is a pre-money, or HC bought at different terms.",
                   points=(f"HC paid **${inv:.2f}M** into a **${round_size:.1f}M** round at **${post:.1f}M** post.",
                           f"That should leave HC at **{expected:.1%}**; the row says **{after:.1%}**.",
                           "One cell is wrong, the post is a **pre-money**, or HC bought at **different terms**."),
                   suggestions=(
                       Suggest("as_proposed", "Book at the stated post-money and ownership; reconcile the cheque separately.", ("The round's headline price is the market's price.", "A cheque at different terms is HC's own economics, not the company's value."), "proposed"),
                       Suggest("at_expected_ownership", f"Book at the {expected:.1%} the round arithmetic implies.", ("The cheque, the round size and the post are three hard facts; the stake follows.", "Right if the ownership cell is the one that is wrong."), "value", value=round(expected * post + w.note_at_cost, 6)),
                   ),
                   action=f"Reconcile the row: ${inv:.2f}M into a ${round_size:.1f}M round at ${post:.1f}M post implies {expected:.1%}, not {after:.1%}. Confirm pre- vs post-money and the ownership cell.",
                   round_size=round_size, expected_ownership=round(expected, 6), stated_ownership=after, stated_post_money=post,
                   hc_investment=inv, ownership_delta=round(delta_own, 6))
    elif implied is not None and delta_own >= ind.cheque_check_min_ownership_delta and post:
        # No round size on the row: only when HC's cheque is big enough to dominate the dilution (the
        # 1pp floor) does `cheque ÷ Δownership` say anything; then the policy line applies as written.
        gap = ratio_change(implied, post)
        if abs(gap) > ind.cheque_price_tolerance:
            w.flag("X-119", "treatment", Severity.REVIEW,
                   f"HC's own cheque says a different price: ${float(e.hc_investment):.2f}M bought {delta_own:.1%}, which is "
                   f"${implied:.1f}M post ({gap:+.0%} against the ${post:.1f}M the row states). One of the three cells is wrong, "
                   "or HC bought at different terms from the headline round.",
                   points=(f"HC paid **${float(e.hc_investment):.2f}M for {delta_own:.1%}** → **${implied:.1f}M** post, {gap:+.0%} vs the stated ${post:.1f}M.",
                           "Either a **cell is wrong** or HC's **terms differ** from the headline.",
                           "The mark rests on the stated price until reconciled."),
                   suggestions=(
                       Suggest("as_proposed", "Book at the stated post-money; reconcile the cheque separately.", ("The round's headline price is the market's price.", "A cheque at different terms is HC's own economics, not the company's value."), "proposed"),
                       Suggest("at_cheque_price", f"Book at the price HC's cheque implies, ${implied:.1f}M.", ("The cash HC actually paid is the hardest fact on the row.", "Right if the stated post-money is the cell that is wrong."), "value", value=float(e.ownership_after) * implied),
                   ),
                   action=f"Reconcile the round price: HC's cheque implies ${implied:.1f}M post against ${post:.1f}M stated.",
                   implied_post_from_hc_cheque=round(implied, 6), stated_post_money=post, gap_pct=round(gap, 4),
                   ownership_delta=round(delta_own, 6))
    if prior_post and ratio(post, prior_post) >= ind.step_up_review_at:
        step = ratio(post, prior_post)
        text = _text(e)
        outside = any_term_in(_NEW_LEAD_TERMS, text)     # "no new investor" names nobody
        w.handled(e, "insider", "internal round", "existing holders", "existing investors", "no new investor", "no outside", "outside investor", "step-up")
        if outside:
            w.flag("X-122", "treatment", Severity.MONITOR,
                   f"A {step:.1f}× step-up (${prior_post:.1f}M → ${post:.1f}M) set by an outside investor the row names. "
                   "A fact worth seeing; a priced round by a new lead is the strongest input there is.",
                   step_up=round(step, 3), threshold=ind.step_up_review_at, new_lead_named=True)
        else:
            w.flag("X-122", "treatment", Severity.REVIEW,
                   f"A {step:.1f}× step-up (${prior_post:.1f}M → ${post:.1f}M) with no outside investor named on the row. "
                   "A price nobody the row identifies has tested is weaker evidence than the headline suggests.",
                   points=(f"**{step:.1f}× step-up** (${prior_post:.1f}M → ${post:.1f}M).",
                           "**No outside investor** is named on the row.",
                           "Confirm **who set the price** before it carries the mark."),
                   suggestions=(
                       Suggest("as_proposed", "Book the round price as proposed.", ("It is a priced, closed transaction.", "Record the lead once confirmed."), "proposed"),
                       Suggest("hold_prior", "Hold the prior mark until the investor set is confirmed.", ("A step-up nobody outside tested is not a market test.", "The prior mark is the last price an outside party set."), "prior"),
                   ),
                   action=f"Confirm an outside investor set the {step:.1f}× step-up price.",
                   step_up=round(step, 3), threshold=ind.step_up_review_at, new_lead_named=False)


# "$26.0M Series B", "$10.8M round", "round of $8.0M", "raised $12M": the size of the round, when the text states it.
# Read for the cheque reconciliation only (X-119) — a cross-check, never a number that is booked.
_ROUND_SIZE = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s?m(?:illion)?\s+(?:series\s+[a-z](?:-\d)?|seed|round|financing|raise|extension|insider-led|internal)"
                         r"|(?:round|financing|raise)\s+of\s+\$\s?(\d+(?:\.\d+)?)\s?m(?:illion)?|raised\s+\$\s?(\d+(?:\.\d+)?)\s?m(?:illion)?", re.I)


def _round_size_from_text(text: str) -> float | None:
    m = _ROUND_SIZE.search(text or "")
    if not m:
        return None
    return float(next(g for g in m.groups() if g))


# "not subject to a lock-up", "no lock-up", "freely tradable from the first day": the row says the shares are not restricted
_NO_LOCKUP = re.compile(r"(?:\bno\b|\bnot subject to\b|\bwithout\b|\bfree of\b|\bnot under\b)[^.;]{0,25}?\block[\s-]?ups?\b"
                        r"|\bfreely trad(?:e)?able\b|\bnot locked[\s-]?up\b", re.I)

_NEW_LEAD_TERMS = ("led by", "new investor", "new lead", "outside investor", "lead investor", "new money from")


def _stage_from_detail(detail: str) -> str | None:
    m = _STAGE_RE.search(detail or "")
    return re.sub(r"\s+", " ", m.group(1)).title() if m else None


def _dilution_check(w: Working, e: Event, cfg: RuleConfig, before: float, after: float) -> None:
    """X-103 — HC did not participate and ownership fell materially. MONITOR: a portfolio
    signal, not a valuation one; the mark comes from a fresh arm's-length round."""
    if before <= 0 or after is None:
        return
    rel = ratio_change(after, before)
    funded = bool(e.hc_investment)
    # X-123 — the stake rose with no cheque. Anti-dilution, a ratchet or a warrant can do that;
    # so can a mis-typed cell, and the row cannot say which. The mark moves with the stated
    # ownership either way, so a person confirms the mechanism before it is booked.
    if not funded and after - before >= cfg.exceptions.indications.cheque_check_min_ownership_delta:
        w.flag("X-123", "treatment", Severity.REVIEW,
               f"HC's ownership rose {before:.1%} → {after:.1%} in a round HC did not fund. Anti-dilution, a ratchet or a "
               f"warrant exercise can do that; so can a wrong cell. The mark of {after:.1%} × the new post-money rests on "
               "the stated stake until the mechanism is confirmed.",
               points=(f"Ownership **rose {before:.1%} → {after:.1%}** with **no HC cheque** on the row.",
                       "Anti-dilution, a ratchet or a warrant explains it — **or a wrong cell** does.",
                       "The mark rests on the **stated stake** until the mechanism is confirmed."),
               suggestions=(
                   Suggest("as_proposed", "Book at the stated ownership; the protection or warrant is real.", ("The row's ownership is the fund's own record.", "Right when the round documents show the mechanism."), "proposed"),
                   Suggest("prior_stake", f"Book at the prior stake, {before:.1%}, against the new post-money.", ("Removes the unexplained increase from the mark.", "Right if the cell is wrong or the mechanism is unconfirmed."), "value", value=before * float(e.value)),
               ),
               action=f"Confirm what raised HC's stake from {before:.1%} to {after:.1%} without a cheque before booking it.",
               ownership_before=before, ownership_after=after, relative_change=round(rel, 4))
    if not funded and rel < -cfg.exceptions.dilution.monitor_relative_drop:
        w.flag("X-103", "treatment", Severity.MONITOR,
               f"HC did not follow its pro rata, so ownership fell {before:.1%} → {after:.1%} ({rel:+.1%}). The mark itself "
               "comes from the new round and is unaffected — this is a reserves question, not a valuation one.",
               ownership_before=before, ownership_after=after, relative_change=round(rel, 4))


# --------------------------------------------------------------------------- M-000

@rule(rule_id="M-000", version=V, applies_to=(), severity=None, effective_from=EFFECTIVE, tier=8,
      description="Carry forward: no qualifying event, prior mark stands.")
def carry_forward(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:  # pragma: no cover - applied by run.py
    raise NotImplementedError("M-000 is applied by the orchestrator, not dispatched on an event")


def apply_carry(w: Working, reason: str = "No activity in the quarter") -> None:
    # The mark carried is equity plus any note leg restored from last quarter's sidecar; the step
    # records both parts so the chain shows the split rather than a single number.
    inputs = {"prior_mark": w.pos.prior_mark, "ownership": w.ownership, "latest_post_money": w.latest_post}
    if w.note_at_cost:
        inputs.update(equity_mark=round(w.equity_mark, 6), note_at_cost=round(w.note_at_cost, 6))
    w.step("M-000", V, inputs, w.proposed_mark, w.proposed_mark,
           f"{reason}; the most recent priced round remains the best evidence of value."
           + (f" ${w.note_at_cost:.2f}M of the mark is a note carried at cost (M-060), restored from the prior quarter." if w.note_at_cost else ""))


# --------------------------------------------------------------------------- M-010 / 011 / 012

@rule(rule_id="M-010", version=V, applies_to=(EventType.PRICED_ROUND.value,), severity=None,
      effective_from=EFFECTIVE, tier=3,
      description="Priced equity round resets the mark: ownership_after × post_money. Delegates to M-011 (flat) and M-012 (down/recap).")
def priced_round(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    post = float(e.value)
    after = float(e.ownership_after)
    before = w.ownership
    prior_post = w.latest_post
    detail = e.detail.lower()
    inv = float(e.hc_investment or 0.0)
    if after <= 0 < before:
        # A priced round cannot take a holder to zero; either HC was crammed out (a recap the
        # schema cannot see) or the cell is wrong. Either way nothing books without a person.
        w.step("M-010", V, {"post_money": post, "prior_post_money": prior_post, "ownership_before": before,
                            "ownership_after": after, "hc_investment": inv, "detail": e.detail},
               w.proposed_mark, w.proposed_mark,
               f"Priced round at ${post:.1f}M records HC's ownership going from {before:.1%} to zero. A round does not take a "
               "holder to nothing; mark unchanged and blocked for a human to establish what happened to the position.", e)
        w.flag("X-101", "treatment", Severity.BLOCK,
               f"The row says HC owns nothing after this round, down from {before:.1%}, with no exit recorded. Either the position "
               "was crammed out in a recapitalisation the columns cannot describe, or the ownership cell is wrong.",
               points=(f"Ownership **{before:.1%} → 0%** on a priced round, **no exit** recorded.",
                       "Either a **cram-out** the columns cannot describe, or **the cell is wrong**.",
                       "**Nothing books** until a person establishes which."),
               suggestions=(
                   Suggest("hold_prior", "Hold the prior mark; establish what happened to the position and rerun.", ("A round that leaves HC with nothing is not a pricing event for HC's stake.", "If the position really is gone, record the exit or shutdown instead."), "prior"),
                   Suggest("write_to_zero", "Write the position to zero — HC was crammed out.", ("Right if the recapitalisation extinguished HC's shares.", "Reverses cleanly if the cell turns out to be an error."), "value", value=0.0),
               ),
               action="Establish whether HC was crammed out or the ownership cell is wrong; nothing books until then.",
               ownership_before=before, ownership_after=after, post_money=post)
        return
    is_recap = "recap" in detail
    is_down = post < prior_post - 1e-9
    # A same-terms extension is one priced *at the last round's post-money*. The words "extension" or
    # "same terms" on a row at a different price do not make it flat: the price moved, so the round is
    # a priced round (up) or a down round, and the staleness clock resets with it.
    is_flat = (not is_down) and abs(post - prior_post) < 1e-9
    new_equity = after * post
    note_converted = w.note_at_cost   # a note leg outstanding at a priced round converts into it
    prior = w.proposed_mark
    conv_txt = (f" HC's ${note_converted:.2f}M note leg converts into the round and is folded into the equity mark."
                if note_converted else "")
    common = {"post_money": post, "prior_post_money": prior_post, "ownership_before": before,
              "ownership_after": after, "hc_investment": inv, "detail": e.detail}
    if note_converted:
        common["note_converted"] = note_converted

    if is_down or is_recap:
        rid = "M-012"
        haircut = cfg.marking.down_round.structure_haircut_pct
        w.step(rid, V, {**common, "structure_haircut_pct": haircut, "structure_adjusted": round(new_equity * (1 - haircut), 6)},
               prior, new_equity,
               f"{'Recap' if is_recap else 'Down round'} at ${post:.1f}M post vs ${prior_post:.1f}M prior. Priced mechanically at "
               f"{after:.1%} × ${post:.1f}M, which assumes every class shares the post-money pro rata. The allocation is "
               "unknown: the preference stack and pay-to-play the schema cannot see move HC's share down if HC's class is "
               "junior to the new money and up if HC funded the senior class." + conv_txt, e,
               formula=f"{after:.1%} × ${post:.1f}M = ${new_equity:.2f}M · structure-adjusted alternative "
                       f"${new_equity:.2f}M × (1 − {haircut:.0%}) = ${new_equity * (1 - haircut):.2f}M")
        w.handled(e, "recap", "recapitalization", "recapitalisation", "down round", "down-round", "pay-to-play", "cram", "cram-down", "washout")
        w.flag("X-102", "treatment", Severity.BLOCK,
               f"{'Recap' if is_recap else 'Down round'}: the round priced at ${post:.1f}M against ${prior_post:.1f}M last time. "
               "Ownership × post-money assumes every class shares pro rata; rounds like this almost always carry a "
               "liquidation preference and pay-to-play that move HC's share — down if HC's class sits behind the new money, "
               "up if HC funded the senior class. The allocation is in the round documents, not the workbook.",
               points=(f"{'Recap' if is_recap else 'Down round'}: priced at **${post:.1f}M** against ${prior_post:.1f}M last round.",
                       "Ownership × post-money **assumes pro rata**; preference and pay-to-play **move HC's share either way**.",
                       "The **allocation is unknown** until the round documents are read."),
               suggestions=(
                   Suggest("as_proposed", f"Book the {'recap' if is_recap else 'down-round'} figure as proposed.", ("It is the only priced transaction and reflects the new capital structure.", "Right if HC's class shares roughly pro rata with the new money."), "proposed"),
                   Suggest("structure_adjusted", f"Apply the policy's {haircut:.0%} junior-class haircut: ${new_equity * (1 - haircut):.2f}M.", ("A placeholder for a preference stack that sits ahead of HC's class.", "Replace it with the waterfall — which may also raise the mark — once the documents are read."), "alternative", value="structure_adjusted"),
                   Suggest("hold_prior", "Hold the prior mark until the round documents are read.", ("Defers the write-down until the preference terms are known.", "Overstates if the round closed as priced — only if documents arrive before the close."), "prior"),
               ),
               action="Read the round documents and allocate the post-money across the classes before booking this mark.",
               prior_post_money=prior_post, post_money=post, insider_led=("insider" in e.notes.lower()),
               structure_haircut_pct=haircut, hc_funded_new_class=bool(inv))
        w.alternative_marks["structure_adjusted"] = round(new_equity * (1 - haircut), 6)
        w.staleness_anchor = e.date
    elif is_flat:
        rid = "M-011"
        w.step(rid, V, common, prior, new_equity,
               f"Same-terms extension at ${post:.1f}M post. Ownership {before:.1%} → {after:.1%} reprices the position "
               "mechanically, but no new price discovery occurred: the staleness clock is NOT reset "
               f"(still runs from {w.staleness_anchor.isoformat()})." + conv_txt, e,
               formula=f"{after:.1%} × ${post:.1f}M = ${new_equity:.2f}M" + (f" + note at cost ${w.note_at_cost:.2f}M" if w.note_at_cost else ""))
        w.flag("X-106", "treatment", Severity.REVIEW,
               f"The extension raised money at the same ${post:.1f}M price, so ownership moved but nobody re-tested what the "
               f"company is worth. The last real price discovery was {months_between(w.staleness_anchor, cfg.quarter.measurement_date)} "
               f"months ago, on {w.staleness_anchor.isoformat()}.",
               points=(f"Extension at the **same ${post:.1f}M price** — ownership moved, valuation did not.",
                       "**No price discovery**: nobody re-tested what the company is worth.",
                       f"Last real price was **{months_between(w.staleness_anchor, cfg.quarter.measurement_date)} months ago** ({w.staleness_anchor.isoformat()})."),
               suggestions=(
                   Suggest("as_proposed", "Keep the mark on the extension price as proposed.", ("New money came in at that price, even without a new lead.", "Nothing in the file says the company is worth less."), "proposed"),
                   Suggest("calibrate", "Calibrate the mark to public comps instead.", ("The extension is not price discovery; comps have moved since the last round.", "Uses the M-080 calibration the engine already computed."), "alternative", value="calibrated_to_comps"),
               ),
               action="Confirm the mark should still rest on a price nobody has re-tested since "
                      f"{w.staleness_anchor.isoformat()}.",
               post_money=post, anchor=w.staleness_anchor)
        # anchor deliberately unchanged
    else:
        rid = "M-010"
        delta_own = after - before
        implied_from_cheque = (inv / delta_own) if (inv and delta_own > 1e-12) else None
        w.step(rid, V, {**common, **({"implied_post_from_hc_cheque": round(implied_from_cheque, 6)} if implied_from_cheque else {})},
               prior, new_equity,
               f"Priced round at ${post:.1f}M post ({e.detail}). Mark = {after:.1%} × ${post:.1f}M. "
               "An arm's-length transaction in the subject security is the strongest Level 3 input available." + conv_txt, e,
               formula=f"{after:.1%} × ${post:.1f}M = ${new_equity:.2f}M" + (f" + note at cost ${w.note_at_cost:.2f}M" if w.note_at_cost else ""))
        w.staleness_anchor = e.date
        _primary_price_checks(w, e, cfg, post=post, prior_post=prior_post, delta_own=delta_own, implied=implied_from_cheque)

    _dilution_check(w, e, cfg, before, after)
    _related_party_flags(w, e, rid, cfg, post=post, prior_post=prior_post)
    if prior_post and post >= prior_post and any_term_in(("down round", "down-round", "downround"), _text(e)):
        w.handled(e, "down round", "down-round")
        w.flag("X-135", "data", Severity.REVIEW,
               f"The row calls this a down round, but the ${post:.1f}M post-money is not below the ${prior_post:.1f}M last round. "
               "Either the label is wrong or the figure is: a down round priced above the last round cannot both be true.",
               points=(f"The row says **down round**; the price says **${post:.1f}M ≥ ${prior_post:.1f}M**.",
                       "The **label and the figure disagree**.",
                       "Confirm which is right before the mark rests on it."),
               suggestions=(
                   Suggest("as_proposed", "Book the stated price; correct the label.", ("The columns are the input the engine can audit.", "Right if the wording is loose."), "proposed"),
                   Suggest("hold_prior", "Hold the prior mark until the row is corrected.", ("A price that contradicts its own description is not evidence yet.", "Rerun after the fix."), "prior"),
               ),
               action=f"Confirm whether the ${post:.1f}M is right (the label is wrong) or the round really was priced below ${prior_post:.1f}M.",
               post_money=post, prior_post_money=prior_post)
    w.equity_mark = new_equity
    if note_converted:
        _note_converted(w, e, note_converted, post, after, "the round")
    w.note_at_cost = 0.0   # converted; cost basis already in `invested`
    w.open_items = [i for i in w.open_items if i.kind != OpenItemKind.CONVERTIBLE_NOTE]   # a note converts at the round
    w.ownership = after
    w.invested += inv
    w.financings.append((e.date, e.event_type, inv))
    w.latest_post = post
    w.latest_round = e.date
    # The round name is the stage ("Series B", from "Series B extension (same terms)"); a Detail that
    # is a memo rather than a name must not become a 2,000-character Stage in next quarter's book.
    w.stage = _stage_from_detail(e.detail) or e.detail.split(" (")[0].split(" extension")[0] or w.stage
    w.fv_level = 3


@rule(rule_id="M-011", version=V, applies_to=(), severity=Severity.REVIEW, effective_from=EFFECTIVE, tier=3,
      description="Flat / same-terms extension: reprices, does not reset the staleness clock.")
def _m011_doc(w, e, cfg, market):  # pragma: no cover - documentation entry; dispatched via M-010
    raise NotImplementedError


@rule(rule_id="M-012", version=V, applies_to=(), severity=Severity.BLOCK, effective_from=EFFECTIVE, tier=3,
      description="Down round / recap: prices mechanically as an upper bound; always blocks.")
def _m012_doc(w, e, cfg, market):  # pragma: no cover
    raise NotImplementedError


# --------------------------------------------------------------------------- M-020 / M-021

@rule(rule_id="M-020", version=V, applies_to=(EventType.ACQ_CLOSED.value,), severity=None,
      effective_from=EFFECTIVE, terminal=True, tier=1,
      description="Closed exit: mark to zero, proceeds to realized, status Acquired.")
def closed_exit(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    if not e.proceeds and any_term_in(_STOCK_TERMS, _text(e)):
        return stock_exit(w, e, cfg, market)
    proceeds = float(e.proceeds or 0.0)
    implied = w.ownership * float(e.value) if e.value else None
    w.step("M-020", V, {"deal_value": e.value, "proceeds": proceeds, "ownership": w.ownership,
                        "implied_from_deal_value": implied, "detail": e.detail},
           w.proposed_mark, 0.0,
           f"Acquisition closed at ${float(e.value or 0):.1f}M; ${proceeds:.1f}M received against a ${w.equity_mark:.1f}M carrying value. "
           "Position realized; mark to zero.", e,
           formula=f"${w.equity_mark:.2f}M carrying value → $0.00M; ${proceeds:.2f}M realized"
                   + (f" · entitlement {w.ownership:.1%} × ${float(e.value):.1f}M deal = ${implied:.2f}M" if implied is not None else ""))
    if e.proceeds is None or float(e.proceeds) == 0.0:
        w.flag("X-101", "treatment", Severity.BLOCK,
               "The exit closed but no cash was recorded against it. Either the consideration is missing from the feed or it is "
               "sitting in escrow, and those book very differently.",
               points=("Exit closed but **no cash recorded** against it.",
                       "Either the consideration is **missing from the feed** or it sits in **escrow**.",
                       "Those two book very differently."),
               suggestions=(
                   Suggest("hold_prior", "Hold the prior mark until the consideration is confirmed.", ("An exit with unknown proceeds cannot be booked either way.", "Keeps the position open so escrow or missing cash is chased."), "prior"),
                   Suggest("write_to_zero", "Write the position to zero — exit closed, nothing recoverable recorded.", ("Nothing was received and nothing is recorded as receivable.", "Reverses cleanly if proceeds arrive in a later quarter."), "value", value=0.0),
               ),
               action="Confirm what HC actually received, and whether any of it is held in escrow.",
               deal_value=e.value)
        # The consideration is unfinished business. If the committee holds the prior mark rather than
        # writing the position off, the next-quarter book carries it open (snapshot.py) and this item
        # ages past policy at once, so the receivable is in front of a reviewer every quarter until a
        # closing row with its proceeds arrives or a decision writes it to zero (D-9).
        w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.UNCONFIRMED_EXIT, opened=e.date,
                                     opened_quarter=w.quarter_label, amount_musd=e.value,
                                     detail=f"exit closed {e.date.isoformat()} at ${float(e.value or 0):.1f}M with no cash recorded; "
                                            "record the closing with its proceeds when the cash arrives, or write the position to zero"))
    elif implied is not None and proceeds - implied > cfg.tolerances.prior_mark_reconciliation_musd * 10:
        w.flag("X-101", "treatment", Severity.REVIEW,
               f"HC received ${proceeds:.2f}M, more than the ${implied:.2f}M its {w.ownership:.1%} of a ${float(e.value):.0f}M deal "
               "would give pro rata. A liquidation preference or participation pays more than the common share; so does a wrong "
               "ownership or deal-value cell.",
               points=(f"Received **${proceeds:.2f}M**, **more than** the ${implied:.2f}M that {w.ownership:.1%} of ${float(e.value):.0f}M gives pro rata.",
                       "A **preference or participation** pays more than the common share — or a cell is wrong.",
                       "Confirm the waterfall; the cash received is booked either way."),
               suggestions=(
                   Suggest("as_proposed", "Book the cash received as realized; confirm the preference that produced it.", ("Cash received is the fact.", "A preference paying out is the ordinary reason for excess over pro rata."), "proposed"),
               ),
               action=f"Confirm why HC received ${proceeds - implied:.2f}M more than its pro-rata share (preference, participation, or a wrong cell).",
               implied=implied, proceeds=proceeds, excess=round(proceeds - implied, 6))
        w.handled(e, "preference", "participating", "participation", "waterfall", "senior")
    elif implied is not None and implied - proceeds > cfg.tolerances.prior_mark_reconciliation_musd * 10:
        w.flag("X-101", "treatment", Severity.REVIEW,
               f"HC received ${proceeds:.2f}M, but its {w.ownership:.1%} of a ${float(e.value):.0f}M deal implies ${implied:.2f}M. "
               "A gap that size is usually escrow, a holdback, or transaction fees.",
               points=(f"Received **${proceeds:.2f}M**; {w.ownership:.1%} of a ${float(e.value):.0f}M deal implies ${implied:.2f}M.",
                       f"A **${abs(implied - proceeds):.2f}M gap** is unexplained.",
                       "Usually **escrow, a holdback or fees** — but it has to be confirmed."),
               suggestions=(
                   Suggest("as_proposed", "Accept the recorded proceeds; treat the gap as escrow or fees.", ("Recorded cash is the fact; a gap this size is a normal deal structure.", "An open item can track any escrow release."), "proposed"),
                   Suggest("carry_gap", f"Carry the ${abs(implied - proceeds):.2f}M gap as an escrow receivable.", ("Matches the deal value HC is owed on its ownership.", "Only if the purchase agreement confirms an escrow or holdback."), "value", value=max(0.0, implied - proceeds)),
               ),
               action=f"Reconcile the ${abs(implied - proceeds):.2f}M difference between proceeds and deal value.",
               implied=implied, proceeds=proceeds)
        w.handled(e, "escrow", "holdback", "earn-out", "earnout", "contingent", "milestone", "indemnification", "indemnity", "indemnities")
        # The gap is a claim HC still holds. If the committee carries it (the `carry_gap` option), the
        # position rolls forward open with this item ageing on it until the escrow is released.
        w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.UNCONFIRMED_EXIT, opened=e.date,
                                     opened_quarter=w.quarter_label, amount_musd=round(max(0.0, implied - proceeds), 6),
                                     detail=f"exit closed {e.date.isoformat()}: ${proceeds:.2f}M received against ${implied:.2f}M implied; "
                                            f"${abs(implied - proceeds):.2f}M in escrow, holdback or fees to confirm"))
    w.realized_quarter += proceeds
    w.flags = [f for f in w.flags if f.rule_id != "X-116"]      # a Chapter 11 question is moot once the position has closed
    retained = float(e.ownership_after) if e.ownership_after else 0.0
    # A non-zero ownership cell on a closed deal used to be read, unconditionally, as "HC rolled
    # its stake into the buyer" — and the cash-vs-stake reconciliation was deleted on that path. A
    # cell simply copied forward from last quarter then produced $20M of cash *plus* a $20M carried
    # stake for a $20M position. If the cash already accounts for the whole stake at the deal
    # value, nothing was rolled: the cell is stale, and that is the finding, not a rollover.
    cash_covers_stake = (e.value and abs(proceeds - w.ownership * float(e.value))
                         <= cfg.tolerances.prior_mark_reconciliation_musd * 10)
    if retained > 0 and e.value and cash_covers_stake:
        w.flag("X-134", "data", Severity.REVIEW,
               f"Row {e.row_index} carries HC Ownership After = {retained:.1%} on a closed acquisition whose ${proceeds:.2f}M of "
               f"cash already equals the whole {w.ownership:.1%} stake at the ${float(e.value):.1f}M deal value. Nothing was rolled "
               "into the buyer; the ownership cell reads as copied forward from the prior quarter and went nowhere.",
               points=(f"Ownership after = **{retained:.1%}** on a closed deal whose cash **covers the whole stake**.",
                       "**Nothing rolled** into the buyer — the cell reads as copied forward.",
                       "Clear the cell (or record the rollover terms) and rerun."),
               suggestions=(Suggest("as_proposed", "Book the exit as an all-cash sale; clear the stray ownership cell.",
                                    ("The proceeds tie to the whole stake at the deal value.", "A cell that went nowhere is a data question."), "proposed"),),
               action=f"Confirm row {e.row_index}'s ownership-after cell is stale; clear it and rerun, or record the rollover.",
               row_index=e.row_index, ownership_after=retained, proceeds=proceeds, deal_value=float(e.value))
        retained = 0.0
    if retained > 0 and e.value:
        # HC rolled part of its stake into the buyer: the cash is realized, the rest is a new holding in
        # another company, priced at the deal like a stock-consideration exit (M-024), and blocked the same way.
        # The proceeds gap the cash branch measured against the whole stake is not an escrow here: it is the
        # rolled stake, which the finding below carries.
        w.flags = [f for f in w.flags if not (f.rule_id == "X-101" and "implied" in f.evidence)]
        w.open_items = [i for i in w.open_items if i.kind != OpenItemKind.UNCONFIRMED_EXIT]
        deal = float(e.value)
        rolled = retained * deal
        w.step("M-024", V, {"deal_value": deal, "ownership_retained": retained, "proceeds": proceeds, "rolled_value": round(rolled, 6)},
               0.0, rolled + 0.0,
               f"HC kept {retained:.1%} of the deal in the buyer's shares (${rolled:.2f}M at the ${deal:.1f}M deal value) alongside the "
               f"${proceeds:.2f}M of cash. The rolled stake is a new holding, not an escrow: it stays on the book, priced at the deal.", e,
               formula=f"{retained:.1%} × ${deal:.1f}M = ${rolled:.2f}M rolled into the buyer; ${proceeds:.2f}M cash realized")
        w.flag("X-112", "treatment", Severity.BLOCK,
               f"HC rolled {retained:.1%} into the buyer: ${rolled:.2f}M of the consideration is shares in another company, priced here "
               "at the deal value, which is not a price for what HC now holds. If the buyer is listed this is Level 1; if private, a new "
               "Level 3 position.",
               points=(f"HC **rolled {retained:.1%}** into the buyer: **${rolled:.2f}M** in the buyer's shares.",
                       "Priced at the **deal value**, which is not a price for what HC now holds.",
                       "Listed buyer → **Level 1**; private → a new **Level 3** position."),
               suggestions=(
                   Suggest("as_proposed", "Carry the rolled stake at the deal value as proposed.", ("The deal value is the only price for the new holding.", "Right if the buyer is private or the lock-up is short."), "proposed"),
                   Suggest("write_to_zero", "Book the cash only and carry the rolled stake at zero until it is priced.", ("Nothing observable prices the buyer's shares yet.", "Conservative; corrected once the buyer is identified and priced."), "value", value=0.0),
               ),
               action="Confirm the buyer, whether it is listed, the share count HC holds and any lock-up; then price the rolled stake.",
               deal_value=deal, ownership_retained=retained, rolled_value=round(rolled, 6), proceeds=proceeds)
        w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.ACQUIRER_SHARES, opened=e.date,
                                     opened_quarter=w.quarter_label, amount_musd=round(rolled, 6),
                                     detail=f"{retained:.1%} rolled into the buyer on a ${deal:.1f}M deal; {e.notes or e.detail}"))
        w.equity_mark = rolled
        w.note_at_cost = 0.0
        w.ownership = retained
        w.latest_post = deal
        w.latest_round = e.date
        w.staleness_anchor = e.date
        w.stage = "Acquired (stock)"
        w.status = Status.ACTIVE
        w.fv_level = 3
        return
    w.equity_mark = 0.0
    w.note_at_cost = 0.0
    w.status = Status.ACQUIRED
    w.terminal = True
    w.fv_level = None


@rule(rule_id="M-024", version=V, applies_to=(), severity=Severity.BLOCK, effective_from=EFFECTIVE, tier=1,
      description="Stock-consideration exit: HC now holds the acquirer's shares, marked at ownership × deal value; "
                  "position stays Active; always blocks. Dispatched from M-020 when the consideration is shares and no cash arrived.")
def stock_exit(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    deal = float(e.value or 0.0)
    new_equity = w.ownership * deal
    w.step("M-024", V, {"deal_value": deal, "ownership": w.ownership, "proceeds": e.proceeds, "consideration": "stock",
                        "detail": e.detail},
           w.proposed_mark, new_equity + w.note_at_cost,
           f"Acquisition closed at ${deal:.1f}M with the consideration paid in the acquirer's shares, not cash ({e.detail}). "
           f"HC's {w.ownership:.1%} of the deal value, ${new_equity:.2f}M, is the value of the shares received: the position "
           "is not realized — it has changed from one company's stock into another's.", e,
           formula=f"{w.ownership:.1%} × ${deal:.1f}M = ${new_equity:.2f}M in the acquirer's shares")
    w.flag("X-112", "treatment", Severity.BLOCK,
           f"HC was paid in shares of the buyer rather than cash, so ${new_equity:.2f}M is the deal value of what it received, "
           "not a price for what it now holds. If the acquirer is listed the position is Level 1 from here and moves daily; "
           "if it is private this is a new Level 3 position priced at the deal; either way a lock-up or escrow changes the answer.",
           points=(f"Paid in **buyer's shares**, not cash — ${new_equity:.2f}M is deal value, not a price for what HC now holds.",
                   "If the acquirer is **listed** this is Level 1 from here; if private, a new Level 3 position priced at the deal.",
                   "A **lock-up or escrow** changes the answer either way."),
           suggestions=(
               Suggest("as_proposed", "Book the shares received at the deal value as proposed.", ("The deal value is the only price for the new holding.", "Right if the acquirer is private or the lock-up is short."), "proposed"),
               Suggest("hold_prior", "Hold the prior mark until the acquirer's listing and lock-up are confirmed.", ("A listed acquirer makes this Level 1 — priced daily, not at the deal.", "Lock-up or escrow could reduce what HC can realise."), "prior"),
           ),
           action="Confirm the acquirer, whether it is listed, the share count HC received and any lock-up.",
           deal_value=deal, ownership=w.ownership, value_of_shares=round(new_equity, 6))
    w.handled(e, "lock-up", "lockup", "cancelled", "canceled", "exchanged", "stock", "shares", "all-stock", "all stock",
              "acquirer shares", "shares of the acquirer", "stock consideration", "stock-for-stock", "rollover")
    w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.ACQUIRER_SHARES, opened=e.date,
                                 opened_quarter=w.quarter_label, amount_musd=round(new_equity, 6),
                                 detail=f"Shares of acquirer received on ${deal:.1f}M deal; {e.notes or e.detail}"))
    w.equity_mark = new_equity
    w.latest_post = deal
    w.latest_round = e.date
    w.staleness_anchor = e.date
    w.stage = "Acquired (stock)"
    w.status = Status.ACTIVE
    w.fv_level = 3


@rule(rule_id="M-021", version=V, applies_to=(EventType.SHUTDOWN.value,), severity=None,
      effective_from=EFFECTIVE, terminal=True, tier=1,
      description="Shutdown: mark to zero, residual proceeds to realized, status Shut Down.")
def shutdown(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    proceeds = float(e.proceeds or 0.0)
    w.flags = [f for f in w.flags if f.rule_id != "X-116"]      # a Chapter 11 question is moot once the company is gone
    w.step("M-021", V, {"proceeds": proceeds, "prior_mark": w.equity_mark, "detail": e.detail},
           w.proposed_mark, 0.0,
           f"Company ceased operations. ${w.equity_mark:.1f}M written off"
           + (f"; ${proceeds:.1f}M residual cash distributed." if proceeds else "; no recovery expected."), e,
           formula=f"${w.equity_mark:.2f}M written off → $0.00M" + (f"; ${proceeds:.2f}M realized" if proceeds else ""))
    if proceeds > w.equity_mark + w.note_at_cost + 1e-9 and w.equity_mark + w.note_at_cost > 0:
        w.flag("X-101", "treatment", Severity.REVIEW,
               f"A shutdown that returns ${proceeds:.2f}M against a ${w.equity_mark + w.note_at_cost:.2f}M carrying value reads "
               "like a sale typed as a shutdown: a wind-down rarely returns more than the mark. The cash is booked as realized "
               "either way; the event type decides whether the write-off line or the exit line carries it.",
               points=(f"Shutdown returns **${proceeds:.2f}M**, **more than the ${w.equity_mark + w.note_at_cost:.2f}M mark**.",
                       "A wind-down rarely returns more than the mark — **is this an exit typed as a shutdown?**",
                       "Realized cash books either way; the **event type** is the question."),
               suggestions=(
                   Suggest("as_proposed", "Book as a shutdown with residual proceeds, as proposed.", ("The row says shutdown; the cash is realized.", "Right if the recovery really was a wind-down."), "proposed"),
               ),
               action="Confirm this was a wind-down and not an acquisition typed as a shutdown.",
               proceeds=proceeds, carrying_value=round(w.equity_mark + w.note_at_cost, 6))
    w.realized_quarter += proceeds
    w.equity_mark = 0.0
    w.note_at_cost = 0.0
    w.status = Status.SHUT_DOWN
    w.terminal = True
    w.fv_level = None


# --------------------------------------------------------------------------- M-030

@rule(rule_id="M-030", version=V, applies_to=(EventType.SECONDARY.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=4,
      description="Secondary sale: proceeds realized; remainder re-marked on the configured basis.")
def secondary(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    before = w.ownership
    after = float(e.ownership_after)
    sold = before - after
    proceeds = float(e.proceeds or 0.0)
    # The price of the sale. The row's own value column is defined as "implied valuation for
    # secondaries" and is read first; proceeds ÷ stake sold is the cross-check (ownership is
    # reported to three decimals, so on a small block it carries rounding noise of several
    # percent — Marrowick: 0.8% sold, $487.5M implied against the $516M the row states).
    implied_from_ownership = proceeds / sold if sold > 1e-12 else None
    implied_post = float(e.value) if e.value else implied_from_ownership
    if implied_from_ownership is None and e.value and sold <= 1e-12:
        implied_post = None                                    # a price with no block sold: still unreconcilable
    basis = cfg.marking.secondary.remainder_basis
    at_last_round = after * w.latest_post
    at_secondary = after * implied_post if implied_post else None
    new_equity = at_secondary if (basis == "secondary_price" and at_secondary is not None) else at_last_round
    spread = ratio_change(implied_post, w.latest_post) if (implied_post and w.latest_post) else None

    if after <= 1e-9 and sold > 1e-12:
        # The whole stake was sold: cash realized, nothing left to mark. Terminal, like an exit.
        implied_whole = float(e.value) if e.value else (proceeds / sold if sold else None)
        w.step("M-030", V, {"ownership_before": before, "ownership_after": 0.0, "ownership_sold": round(sold, 6), "proceeds": proceeds,
                            "implied_post_money": implied_whole, "last_round_post_money": w.latest_post},
               w.proposed_mark, 0.0,
               f"HC sold its entire {before:.1%} stake for ${proceeds:.1f}M"
               + (f" at ${implied_whole:.1f}M post ({ratio_change(implied_whole, w.latest_post):+.1%} vs the last round)" if implied_whole and w.latest_post else "")
               + ". Position realized; mark to zero.", e,
               formula=f"{before:.1%} sold for ${proceeds:.2f}M → $0.00M"
                       + (f" · implied ${proceeds:.2f}M ÷ {sold:.1%} = ${proceeds / sold:.1f}M post" if sold > 1e-12 else ""))
        if implied_whole and w.latest_post and abs(ratio_change(implied_whole, w.latest_post)) > cfg.exceptions.secondary.spread_tolerance_pct:
            w.flag("X-104", "treatment", Severity.REVIEW,
                   f"The sale of the whole stake implies ${implied_whole:.1f}M for the company, {ratio_change(implied_whole, w.latest_post):+.1%} "
                   f"against the ${w.latest_post:.1f}M last round. Nothing is left to mark, but the gap says something about the "
                   "book's other marks on this basis.",
                   points=(f"Whole stake sold at **${implied_whole:.1f}M** implied, **{ratio_change(implied_whole, w.latest_post):+.1%}** vs the last round.",
                           "Nothing is left to mark on this position.",
                           "The gap is evidence about **similar marks** in the book."),
                   suggestions=(Suggest("as_proposed", "Book the cash as realized and close the position, as proposed.", ("The sale price is the exit price.", "No residual position to re-mark."), "proposed"),),
                   action="Confirm the sale price against the last round; the position is closed either way.",
                   implied_post_money=implied_whole, last_round_post_money=w.latest_post)
        w.realized_quarter += proceeds
        w.equity_mark = 0.0
        w.note_at_cost = 0.0
        w.ownership = 0.0
        w.status = Status.ACQUIRED
        w.stage = "Sold (secondary)"
        w.terminal = True
        w.fv_level = None
        return
    if implied_post is None:
        # Nothing sold (ownership unchanged) or a proceeds-only row: the arithmetic has no meaning.
        w.step("M-030", V, {"ownership_before": before, "ownership_after": after, "proceeds": proceeds,
                            "last_round_post_money": w.latest_post},
               w.proposed_mark, w.proposed_mark,
               f"Secondary sale recorded with no ownership change ({before:.1%} → {after:.1%}); ${proceeds:.1f}M proceeds cannot "
               "be tied to a block sold. Mark unchanged; position blocked for a human to reconcile the row.", e)
        w.flag("X-101", "treatment", Severity.BLOCK,
               f"The row records ${proceeds:.1f}M of proceeds but no change in ownership, so there is no block sold to price the "
               "sale against. One of the two figures is wrong.",
               points=(f"Row records **${proceeds:.1f}M of proceeds** but **no change in ownership**.",
                       "There is no block sold to price the sale against.",
                       "**One of the two figures is wrong.**"),
               suggestions=(
                   Suggest("hold_prior", "Hold the prior mark; correct the activity row and rerun.", ("A sale with no stake sold cannot be priced.", "Fixing the row is the clean resolution — nothing to book until then."), "prior"),
               ),
               action="Reconcile the activity row: proceeds are recorded but no stake was sold.",
               proceeds=proceeds, ownership_before=before, ownership_after=after)
        w.realized_quarter += proceeds
        return
    price_source = "the row's implied valuation" if e.value else "proceeds ÷ stake sold"
    cross = (implied_from_ownership / implied_post - 1) if (e.value and implied_from_ownership and implied_post) else None
    w.step("M-030", V, {"ownership_before": before, "ownership_after": after, "ownership_sold": round(sold, 6),
                        "proceeds": proceeds, "implied_post_money": implied_post, "implied_price_source": price_source,
                        "implied_from_ownership": (round(implied_from_ownership, 6) if implied_from_ownership else None),
                        "last_round_post_money": w.latest_post,
                        "remainder_basis": basis, "at_last_round": at_last_round, "at_secondary_price": at_secondary},
           w.proposed_mark, new_equity + w.note_at_cost,
           f"Sold {sold/before:.0%} of the position for ${proceeds:.1f}M at ${implied_post:.1f}M post ({price_source}) vs "
           f"${w.latest_post:.1f}M last round" + (f", {spread:+.1%}" if spread is not None else "")
           + (f"; proceeds ÷ stake sold gives ${implied_from_ownership:.1f}M ({cross:+.1%}" + (", within tolerance" if abs(cross) <= cfg.exceptions.secondary.spread_tolerance_pct else ", a gap to confirm") + ")"
              if cross is not None else "")
           + f". Remainder {after:.1%} marked at the {'last-round' if basis == 'last_round' else 'secondary'} price.", e,
           formula=f"remainder {after:.1%} × ${(implied_post if (basis == 'secondary_price' and at_secondary is not None) else w.latest_post):.1f}M"
                   f" = ${new_equity:.2f}M; ${proceeds:.2f}M realized"
                   + (f" · implied ${proceeds:.2f}M ÷ {sold:.1%} = ${implied_from_ownership:.1f}M post" if implied_from_ownership else ""))
    if at_secondary is not None:
        w.alternative_marks["at_secondary_price" if basis == "last_round" else "at_last_round"] = (
            at_secondary if basis == "last_round" else at_last_round)
    w.handled(e, "discount", "premium", "secondary", "block", "spread", "partial", "no new capital")
    # Ownership is carried to three decimals, so the stake sold is known only to ± one rounding unit each
    # side: proceeds ÷ stake sold is a range (Marrowick: 0.8% sold, $433M–$557M around the $516M the row
    # states). Only a value column outside that range, by more than the spread tolerance, disagrees.
    unit = cfg.exceptions.indications.ownership_rounding
    lo_p = proceeds / (sold + 2 * unit) if proceeds else None
    hi_p = (proceeds / (sold - 2 * unit) if sold > 2 * unit else float("inf")) if proceeds else None
    tol = cfg.exceptions.secondary.spread_tolerance_pct
    disagree = (cross is not None and lo_p is not None
                and (implied_post * (1 + tol) < lo_p or implied_post * (1 - tol) > hi_p))
    if disagree:
        # The row's own two prices disagree: the value column says one company value, proceeds ÷ the
        # stake sold says another. A person decides which is the sale price before anything is marked on it.
        w.alternative_marks["at_proceeds_price"] = after * implied_from_ownership + w.note_at_cost
        w.flag("X-104", "treatment", Severity.REVIEW,
               f"The row prices the sale two ways that disagree: the value column says ${implied_post:.1f}M for the company, but "
               f"${proceeds:.2f}M for {sold:.1%} of it says ${implied_from_ownership:.1f}M ({cross:+.1%}). The remainder is marked on the "
               "last round meanwhile.",
               points=(f"Value column says **${implied_post:.1f}M**; proceeds ÷ stake sold says **${implied_from_ownership:.1f}M** ({cross:+.1%}).",
                       "Both come from this row; **one of them is wrong**.",
                       "Confirm the sale price before the remainder is marked on it."),
               suggestions=(
                   Suggest("as_proposed", "Keep the remainder at the last-round price; reconcile the row.", ("Neither of two disagreeing prices is evidence yet.", "Correct the row and rerun."), "proposed"),
                   Suggest("at_proceeds_price", f"Mark the remainder at the price the proceeds imply (${implied_from_ownership:.1f}M).", ("Cash received against stake sold is the harder fact.", "Right if the value cell is the one that is wrong."), "alternative", value="at_proceeds_price"),
               ),
               action=f"Reconcile the sale price: the row says ${implied_post:.1f}M but ${proceeds:.2f}M for {sold:.1%} implies ${implied_from_ownership:.1f}M.",
               implied_post_money=implied_post, implied_from_proceeds=round(implied_from_ownership, 6), gap_pct=round(cross, 4),
               spread=(round(spread, 6) if spread is not None else None), last_round_post_money=w.latest_post)
    elif spread is not None and abs(spread) > cfg.exceptions.secondary.spread_tolerance_pct:
        w.flag("X-104", "treatment", Severity.REVIEW,
               f"The sale implies the company is worth ${implied_post:.1f}M, {spread:+.1%} against the ${w.latest_post:.1f}M the last "
               "round set. One buyer taking one block is real evidence but not necessarily the principal market, so policy holds "
               f"the remaining stake at the round price. On the secondary price it would be "
               f"${(at_secondary if basis == 'last_round' else at_last_round):.2f}M instead.",
               points=(f"Secondary implies **${implied_post:.1f}M**, **{spread:+.1%}** against the ${w.latest_post:.1f}M round price.",
                       "One buyer taking one block is real evidence but **may not be the principal market**.",
                       f"On the secondary price the remaining stake would be **${(at_secondary if basis == 'last_round' else at_last_round):.2f}M** instead."),
               suggestions=(
                   Suggest("as_proposed", "Keep the remaining stake at the last-round price.", ("The round is the principal market; one block sale is weaker evidence.", "Policy default — the secondary is recorded as an alternative mark."), "proposed"),
                   Suggest("at_secondary", f"Mark the remaining stake at the secondary price ({spread:+.1%}).", ("The secondary is the most recent transaction in this security.", "Right if the buyer was informed and the block was meaningful."), "alternative", value="at_secondary_price" if basis == "last_round" else "at_last_round"),
               ),
               action="Decide whether the stake HC still holds follows the last round or the secondary price.",
               spread=round(spread, 4), implied_post_money=implied_post, basis=basis)
    w.realized_quarter += proceeds
    w.equity_mark = new_equity
    w.ownership = after


# --------------------------------------------------------------------------- M-040

@rule(rule_id="M-040", version=V, applies_to=(EventType.IPO.value, EventType.DIRECT_LISTING.value), severity=Severity.BLOCK,
      effective_from=EFFECTIVE, tier=2,
      description="IPO or direct listing: mark to the measurement-date market cap; Level 1; lock-up treatment from config; always blocks.")
def ipo(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    after = float(e.ownership_after)
    quote = market.quotes.get(w.pos.company)
    if cfg.marking.ipo.price_source == "market_close" and quote is not None:
        cap, source = quote.market_cap_musd, quote.source
        w.market_note = quote.note
    else:
        cap, source = float(e.value), "ipo_print"
    text = _text(e)
    # A direct listing has no lock-up unless the row says it does; an IPO has one unless the row says it does not.
    said_lockup = any_term_in(("lock-up", "lockup", "lock up"), text)
    said_no_lockup = bool(_NO_LOCKUP.search(text))
    has_lockup = (not said_no_lockup) and (said_lockup or e.event_type != EventType.DIRECT_LISTING.value)
    disc = cfg.marking.ipo.lockup_discount_pct if has_lockup else 0.0
    new_equity = after * cap * (1 - disc)
    lockup_end = e.date + timedelta(days=cfg.open_items.ipo_lockup_days) if has_lockup else None
    w.handled(e, "lock-up", "lockup", "freely tradable", "tradable")
    note_converted = w.note_at_cost
    w.step("M-040", V, {"ipo_market_cap": e.value, "measurement_date_market_cap": cap, "price_source": source,
                        "ownership_before": w.ownership, "ownership_after": after, "lockup_discount_pct": disc,
                        "lockup_end": lockup_end, **({"note_converted": note_converted} if note_converted else {})},
           w.proposed_mark, new_equity,
           (f"{e.detail}." if (e.detail or "").lower().startswith("listed") else f"Listed ({e.detail}).")
           + f" Mark = {after:.1%} × ${cap:,.0f}M market cap at measurement date ({price_source_words(source)})"
           + (f" less {disc:.0%} lock-up discount" if disc else
              (" with no lock-up discount (ASU 2022-03: a contractual sale restriction is not a characteristic of the security)" if has_lockup
               else " with no lock-up: the shares are freely tradable" + (" (per the row)" if said_no_lockup else " (a direct listing)")))
           + ". Fair value hierarchy: Level 3 → Level 1."
           + (f" HC's ${note_converted:.2f}M note leg converts on listing and is folded into the equity mark." if note_converted else ""), e,
           formula=f"{after:.1%} × ${cap:,.0f}M" + (f" × (1 − {disc:.0%})" if disc else "") + f" = ${new_equity:.2f}M")
    md = cfg.quarter.measurement_date
    seeded = source.startswith("stub:") or abs(cap - float(e.value)) < 1e-9
    if seeded:
        quote_line = (f"No exchange quote is on file for the {md.isoformat()} close: the quote in this run is {price_source_words(source)} "
                      f"(${cap:,.0f}M market cap), so the proposed mark is the listing-day market cap of ${float(e.value):,.0f}M "
                      f"and stands in for the close until the actual {md.strftime('%d %b')} price is confirmed.")
        quote_point = (f"Now **listed**: the mark should be the **{md.isoformat()} close**; no quote is on file, so the "
                       f"**${float(e.value):,.0f}M listing-day market cap** stands in ({price_source_words(source, short=True)}).")
    else:
        quote_line = (f"The mark should be the closing price on {md.isoformat()} (${cap:,.0f}M market cap, {source}) — not the "
                      f"${float(e.value):,.0f}M market cap the shares priced at on listing day.")
        quote_point = (f"Now **listed**: the mark is the **{md.isoformat()} close** (${cap:,.0f}M), not the "
                       f"${float(e.value):,.0f}M listing-day market cap.")
    lockup_line = (f"HC also cannot sell until {lockup_end.isoformat()}. Under ASU 2022-03 a contractual sale restriction is "
                   f"not a characteristic of the security and takes no discount, so policy applies {disc:.0%}; a reviewer ratifies that."
                   if has_lockup else "There is no lock-up: HC's shares are freely tradable" + (" (per the row)." if said_no_lockup else " (a direct listing)."))
    lockup_points = ((f"HC **cannot sell until {lockup_end.isoformat()}**.",
                      f"Policy applies a **{disc:.0%}** lock-up discount (ASU 2022-03: a contractual restriction takes no discount) — ratified by a reviewer.")
                     if has_lockup else ("**No lock-up**: the shares are freely tradable" + (" (per the row)." if said_no_lockup else " (a direct listing)."),
                                         "Level 1 from here: the mark is the **market close**, with no discount."))
    w.flag("X-101", "treatment", Severity.BLOCK,
           f"The position is now listed, so the mark comes from a market capitalisation rather than a funding round. {quote_line} "
           f"{lockup_line}",
           points=(quote_point, *lockup_points),
           suggestions=(
               Suggest("as_proposed", (f"Book the ${float(e.value):,.0f}M listing-day stand-in" + (f" with the {disc:.0%} lock-up discount" if has_lockup else "") + f", as proposed, pending the {md.strftime('%d %b')} close." if seeded else
                                       f"Book the {md.strftime('%d %b')} close" + (f" with the {disc:.0%} lock-up discount" if has_lockup else "") + ", as proposed."), ("Level 1: the quoted price is fair value under ASC 820.", "ASU 2022-03: a contractual lock-up is not a characteristic of the security, so no discount."), "proposed"),
               Suggest("at_ipo_print", "Book at the listing-day market cap instead of the close.", ("Avoids marking to post-listing swings HC cannot trade during the lock-up.", "Conservative if the shares have run up since listing; the reverse if they fell."), "alternative", value="at_ipo_print"),
           ),
           action=(f"Obtain the {md.strftime('%d %b')} closing price (none is on file) and confirm the ${float(e.value):,.0f}M stand-in" if seeded else
                   f"Confirm the {md.strftime('%d %b')} closing price") + (f", then ratify or change the {disc:.0%} lock-up discount." if has_lockup else "."),
           price_source=source, price_source_note=w.market_note, lockup_end=lockup_end, measurement_date=md,
           ipo_print_mark=round(after * float(e.value), 6))
    w.alternative_marks["at_ipo_print"] = after * float(e.value)
    if has_lockup:
        w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.IPO_LOCKUP, opened=e.date,
                                     opened_quarter=w.quarter_label, expected_resolution=lockup_end,
                                     detail=f"{cfg.open_items.ipo_lockup_days}-day lock-up; {after:.1%} of listed equity"))
    w.equity_mark = new_equity
    if note_converted:
        _note_converted(w, e, note_converted, cap, after, "the listing")
    w.note_at_cost = 0.0
    w.open_items = [i for i in w.open_items if i.kind != OpenItemKind.CONVERTIBLE_NOTE]   # converts on listing
    w.ownership = after
    w.latest_post = cap
    w.latest_round = e.date
    w.staleness_anchor = e.date
    w.listed = True
    w.fv_level = 1
    w.stage = "Public"


# --------------------------------------------------------------------------- M-050

# An announced deal that the row itself says is not a signed agreement. A letter of intent or an
# indicative offer is a term sheet for an exit: real information, no contract, so the policy's
# close probability does not apply and the mark holds until a definitive agreement is signed.
# (Found by the Q2 2026 test file: an LOI at $120M was weighted at 90% like a signed deal.)
_NON_BINDING_TERMS = ("non-binding", "nonbinding", "letter of intent", "loi", "indicative offer", "indicative proposal")


@rule(rule_id="M-050", version=V, applies_to=(EventType.ACQ_ANNOUNCED.value,), severity=Severity.BLOCK,
      effective_from=EFFECTIVE, tier=5,
      description="Announced, unclosed acquisition: probability-weighted deal value by default; always blocks.")
def announced(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    deal = float(e.value)
    p = cfg.marking.announced.close_probability
    treatment = cfg.marking.announced.treatment
    full = w.ownership * deal
    hold = w.equity_mark
    # Probability-weighted expected return (PWERM): the close branch at the deal price, the
    # break branch at the standalone value — the carrying mark, not zero. A deal that fails
    # leaves HC holding the company it held before.
    weighted = p * full + (1 - p) * hold
    non_binding = any_term_in(_NON_BINDING_TERMS, _text(e))
    if non_binding:
        w.handled(e, "non-binding", "nonbinding", "loi", "letter of intent", "indicative", "proposal")
    if non_binding:
        treatment = "hold_prior"
    new_equity = {"probability_weighted": weighted, "full_deal_value": full, "hold_prior": hold}[treatment]
    w.step("M-050", V, {"deal_value": deal, "ownership": w.ownership, "treatment": treatment, "close_probability": p,
                        "at_full_deal_value": full, "standalone_if_deal_breaks": hold, "probability_weighted": weighted,
                        "hold_prior": hold, "detail": e.detail, "non_binding": non_binding},
           w.proposed_mark, new_equity + w.note_at_cost,
           (f"Non-binding offer at ${deal:.0f}M ({e.detail}): a letter of intent is not a signed agreement, so the "
            f"{p:.2f} close probability does not apply and the mark holds at ${hold:.2f}M. The offer is disclosed: "
            f"${weighted:.2f}M if weighted as a signed deal, ${full:.2f}M at full value." if non_binding else
            f"Definitive agreement at ${deal:.0f}M, not closed ({e.notes or 'no closing detail'}). "
            f"Marked {TREATMENT_WORDS[treatment]}: "
            + (f"{p:.2f} × ${full:.2f}M (closes at {w.ownership:.1%} × ${deal:.0f}M) + {1 - p:.2f} × ${hold:.2f}M (breaks; standalone at the last round)"
               if treatment == "probability_weighted" else f"{w.ownership:.1%} × ${deal:.0f}M")
            + f" = ${new_equity:.2f}M. Alternatives: full ${full:.2f}M, hold ${hold:.2f}M."), e,
           formula=(f"{p:.2f} × ({w.ownership:.1%} × ${deal:.0f}M = ${full:.2f}M) + {1 - p:.2f} × ${hold:.2f}M = ${weighted:.2f}M"
                    if treatment == "probability_weighted" else
                    f"{w.ownership:.1%} × ${deal:.0f}M = ${full:.2f}M" if treatment == "full_deal_value" else
                    f"hold ${hold:.2f}M (non-binding: no probability applied)"))
    if non_binding:
        w.flag("X-101", "treatment", Severity.BLOCK,
               f"A buyer has put ${deal:.0f}M in writing, but the row says the offer is non-binding: no signed agreement, no "
               f"closing conditions to satisfy, nothing HC can enforce. Policy holds the mark at ${hold:.2f}M and discloses the "
               f"offer; weighting it like a signed deal would give ${weighted:.2f}M, full value ${full:.2f}M.",
               points=(f"**Non-binding** offer at **${deal:.0f}M** — a letter of intent, not a signed agreement.",
                       f"Mark **held at ${hold:.2f}M**; the offer is disclosed, not booked.",
                       f"If it were a signed deal: **${weighted:.2f}M** weighted, **${full:.2f}M** at full value."),
               suggestions=(
                   Suggest("as_proposed", f"Hold the prior mark, ${hold:.2f}M; the offer is not a contract.", ("Nothing is signed; execution risk is the whole question.", "Policy default for a non-binding offer."), "proposed"),
                   Suggest("weighted", f"Weight it like a signed deal, ${weighted:.2f}M.", ("Right if the parties are effectively committed and diligence is a formality.", "The policy's close probability, applied to an unsigned offer."), "value", value=weighted),
                   Suggest("full_value", f"Book the full offer, ${full:.2f}M.", ("Right only if the offer is as good as closed.", "Aggressive for a letter of intent."), "value", value=full),
               ),
               action="Confirm the offer is non-binding and hold the mark, or treat it as a signed deal.",
               deal_value=deal, close_probability=p, treatment=treatment, non_binding=True)
    else:
        w.flag("X-101", "treatment", Severity.BLOCK,
               f"A buyer has signed for ${deal:.0f}M but the deal has not closed and still needs approval. Booking the full deal value "
               "ignores that contingency; holding the old mark ignores a signed agreement. Policy weights the two outcomes at "
               f"{p:.2f} — the deal price if it closes, the standalone mark if it breaks — giving ${weighted:.2f}M against "
               f"${full:.2f}M at full value and ${hold:.2f}M if held.",
               points=(f"Buyer signed for **${deal:.0f}M**, but the deal has **not closed** and still needs approval.",
                       f"Policy weights **{p:.2f} × deal price + {1 - p:.2f} × standalone** → **${weighted:.2f}M**.",
                       f"Alternatives: **${full:.2f}M** at full value, **${hold:.2f}M** held at prior."),
               suggestions=(
                   Suggest("as_proposed", f"Ratify the {p:.2f}-weighted mark of ${weighted:.2f}M.", ("Reflects a signed agreement with a real chance of not closing.", "Policy default for an announced, unclosed deal."), "proposed"),
                   Suggest("full_value", f"Book the full deal value, ${full:.2f}M.", ("The buyer has signed; only approval remains.", "Right if the closing conditions are formalities."), "value", value=full),
                   Suggest("hold_prior", f"Hold the prior mark, ${hold:.2f}M, until the deal closes.", ("Nothing is realised until closing; a signed deal can still break.", "Right if approval is uncertain or the buyer is stretched."), "value", value=hold),
               ),
               action=f"Ratify the {p:.2f} close probability, or choose full deal value or hold at prior.",
               deal_value=deal, close_probability=p, treatment=treatment)
    w.alternative_marks.update({"at_full_deal_value": full, "hold_prior": hold, "probability_weighted": weighted})
    w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.PENDING_ACQUISITION, opened=e.date,
                                 opened_quarter=w.quarter_label, amount_musd=deal, detail=e.notes or e.detail))
    w.equity_mark = new_equity


# --------------------------------------------------------------------------- M-060

@rule(rule_id="M-060", version=V, applies_to=(EventType.CONVERTIBLE_NOTE.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=6,
      description="Convertible note or SAFE: a cap is not a price. Equity mark unchanged; HC's new money carried at cost as a separate leg.")
def convertible_note(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    inv = float(e.hc_investment or 0.0)
    cap = _cap_from_detail(e.detail)
    cap_vs_last = (cap / w.latest_post - 1) if (cap and w.latest_post) else None
    w.step("M-060", V, {"hc_investment": inv, "valuation_cap": cap, "last_round_post_money": w.latest_post,
                        "cap_vs_last_round": cap_vs_last, "new_money_basis": cfg.marking.convertible.new_money_basis, "detail": e.detail},
           w.proposed_mark, w.proposed_mark + inv,
           f"Bridge note ({e.detail}). A valuation cap is a ceiling on a future conversion price, not a price: equity mark unchanged at "
           f"${w.equity_mark:.2f}M." + (f" HC's ${inv:.2f}M new money carried at cost as a separate note leg." if inv else " HC did not fund the note."), e,
           formula=(f"equity ${w.equity_mark:.2f}M + note at cost ${w.note_at_cost + inv:.2f}M = ${w.proposed_mark + inv:.2f}M" if inv
                    else f"equity ${w.equity_mark:.2f}M unchanged; HC did not fund the note"))
    cap_txt = (f"cap ${cap:.1f}M" + (f", {cap_vs_last:+.0%} vs last round" if cap_vs_last is not None else "")) if cap else "no parsable valuation cap"
    if inv:
        w.flag("X-107", "treatment", Severity.REVIEW,
               f"HC put ${inv:.2f}M into a bridge note ({cap_txt}). The equity mark cannot move — a cap is a ceiling on a future "
               "conversion price, not a price — so the new money is carried separately at cost until the note converts.",
               points=(f"**${inv:.2f}M** into a bridge note ({cap_txt}).",
                       "A cap is a **ceiling on a future conversion**, not a price — the equity mark cannot move.",
                       "The new money is carried **separately at cost** until it converts."),
               suggestions=(
                   Suggest("as_proposed", "Carry the note at cost beside the unchanged equity mark, as proposed.", ("A cap is not a price; cost is the only observable value for the note.", "Standard treatment until the note converts."), "proposed"),
                   Suggest("impair_note", f"Treat the bridge as distress: carry equity only, note written to zero.", ("A bridge instead of a priced round often means the company cannot raise.", "Conservative; reverses on conversion."), "value", value=max(0.0, w.proposed_mark - inv)),
               ),
               action=f"Confirm the ${inv:.2f}M is carried at cost, and whether the bridge signals distress.",
               hc_investment=inv, valuation_cap=cap, cap_vs_last_round=cap_vs_last)
    else:
        # A cap above the last round is a company bridging on its way up: nothing to decide. A cap
        # materially *below* it is the same evidence a low term sheet is (X-109) — the market is
        # pricing the next round under the mark the book still carries — and HC declining to fund
        # it says so twice. Severity follows the cap, on the same policy line as the term sheet.
        low = cap is not None and w.latest_post and ratio(cap, w.latest_post) <= cfg.exceptions.indications.note_cap_review_below
        if low:
            w.flag("X-108", "treatment", Severity.REVIEW,
                   f"The company raised a bridge note HC did not fund, capped below its own last round ({cap_txt}). A cap is not a "
                   "price, so nothing is booked from it — but the next round converting at that ceiling would land under the mark "
                   "the book still carries, and HC did not take its share.",
                   points=(f"Bridge note **HC did not fund**, {cap_txt}.",
                           "A conversion at that ceiling would price **below the carried mark**.",
                           "**Nothing is booked** from a cap; a reviewer decides whether the mark still holds."),
                   suggestions=(
                       Suggest("as_proposed", "Keep the mark on the last round as proposed.", ("A cap is a ceiling on a future conversion, not a price.", "Right while the company is still expected to raise above it."), "proposed"),
                       Suggest("at_cap", f"Mark at the cap: {w.ownership:.1%} × ${cap:.1f}M.", ("Treats the cap as the best available forward price.", "Conservative, and reverses if the next round prices above it."), "value", value=w.ownership * cap),
                   ),
                   action=f"Decide whether a mark set at ${w.latest_post:.1f}M still holds against a bridge capped at ${cap:.1f}M.",
                   valuation_cap=cap, cap_vs_last_round=cap_vs_last, threshold=cfg.exceptions.indications.note_cap_review_below)
        else:
            w.flag("X-108", "treatment", Severity.MONITOR,
                   f"The company raised a bridge note that HC did not fund ({cap_txt}). A cap is not a price, so the mark is unchanged "
                   "and there is nothing to decide.",
                   valuation_cap=cap, cap_vs_last_round=cap_vs_last)
    if cap is None:
        w.flag("X-101", "treatment", Severity.REVIEW,
               f"The engine could not read a valuation cap out of the Detail text ({e.detail!r}), so it cannot tell how this note "
               "would convert.",
               points=("**No valuation cap** could be read out of the Detail text.",
                       "The engine **cannot tell how the note converts**.",
                       "Cap, discount and interest have to be read **by hand**."),
               suggestions=(
                   Suggest("as_proposed", "Carry the note at cost as proposed until the terms are read.", ("Cost is the only observable value without a cap or discount.", "The terms can be entered on the row next quarter."), "proposed"),
               ),
               action="Read the note terms by hand — cap, discount and interest.",
               detail=e.detail)
    w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.CONVERTIBLE_NOTE, opened=e.date,
                                 opened_quarter=w.quarter_label, amount_musd=inv or None,
                                 detail=e.detail + ("" if inv else " (HC did not participate)")))
    w.note_at_cost += inv
    w.invested += inv
    w.financings.append((e.date, e.event_type, inv))


# --------------------------------------------------------------------------- M-070

@rule(rule_id="M-070", version=V, applies_to=(EventType.TERM_SHEET.value,), severity=Severity.MONITOR,
      effective_from=EFFECTIVE, tier=7,
      description="Signed term sheet: non-binding; mark unchanged; disclosed as a pending event.")
def term_sheet(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    indicated = w.ownership * float(e.value) if e.value else None
    w.handled(e, "non-binding", "nonbinding", "term sheet", "indicative", "proposal")
    w.step("M-070", V, {"indicated_post_money": e.value, "ownership": w.ownership, "indicated_mark": indicated, "detail": e.detail},
           w.proposed_mark, w.proposed_mark,
           formula=(f"indicated: {w.ownership:.1%} × ${float(e.value):.1f}M = ${indicated:.2f}M (disclosed, not booked)" if indicated else None),
           rationale=f"Term sheet signed ({e.detail}); not closed. No enforceable transaction — mark unchanged"
           + (f"; indicated value ${indicated:.2f}M disclosed, not booked." if indicated else "."), e=e)
    ratio_ = ratio(float(e.value), w.latest_post) if (e.value and w.latest_post) else None
    limit = cfg.exceptions.indications.term_sheet_review_below
    if indicated is not None:
        w.alternative_marks["term_sheet_indicated"] = indicated
    if ratio_ is not None and ratio_ <= limit:
        w.handled(e, "down round", "down-round", "discount", "below", "lower", "66%", "of the last round")
        w.flag("X-109", "treatment", Severity.REVIEW,
               f"A signed term sheet indicates ~${float(e.value):.1f}M, {ratio_ - 1:+.0%} against the ${w.latest_post:.1f}M the mark "
               "rests on. It is non-binding, so nothing is booked from it — but a buyer putting a lower price in writing is "
               "evidence a market participant would not pay the carried price today, and a reviewer could book less.",
               points=(f"Term sheet at **${float(e.value):.1f}M**, **{ratio_ - 1:+.0%}** against the ${w.latest_post:.1f}M round price.",
                       "Non-binding — but a **lower price in writing** is evidence the mark is high.",
                       f"On the indicated price the position would be **${indicated:.2f}M**."),
               suggestions=(
                   Suggest("as_proposed", "Keep the mark at the last round; the term sheet is not a transaction.", ("Nothing has closed and diligence is open.", "Policy default — the indicated value is disclosed as an alternative."), "proposed"),
                   Suggest("at_indication", f"Mark down to the indicated price ({ratio_ - 1:+.0%}).", ("The most recent price a market participant put in writing.", "Right if the term sheet is likely to close near its terms."), "alternative", value="term_sheet_indicated"),
               ),
               action="Decide whether a term sheet below the carried price is evidence to mark down on.",
               indicated_post_money=e.value, indicated_mark=indicated, ratio_to_last_round=round(ratio_, 4), threshold=limit)
    else:
        w.flag("X-109", "treatment", Severity.MONITOR,
               f"A term sheet indicates ~${float(e.value or 0):.1f}M against the ${w.latest_post:.1f}M the mark rests on. It is "
               "non-binding and diligence is open, so nothing is booked from it — this is disclosure only.",
               indicated_post_money=e.value, indicated_mark=indicated,
               ratio_to_last_round=(round(ratio_, 4) if ratio_ is not None else None))
    w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.TERM_SHEET, opened=e.date,
                                 opened_quarter=w.quarter_label, amount_musd=e.value, detail=e.notes or e.detail))


def _note_converted(w: Working, e: Event, leg: float, post: float, after: float, into: str) -> None:
    """X-124 — HC's note converted into this round or listing. The bridge questions (X-107 funded,
    X-108 unfunded) are settled by the conversion and are dropped; what a reviewer now confirms is the
    conversion itself: the cap or discount applied, accrued interest, and that the principal is in
    `invested` exactly once (it is: the note leg was cost, the round re-marks the whole stake)."""
    w.flags = [f for f in w.flags if f.rule_id not in ("X-107", "X-108")]
    w.handled(e, "conversion", "convert", "converts", "converted", "accrued", "interest", "discount", "cap")
    w.flag("X-124", "treatment", Severity.REVIEW,
           f"HC's ${leg:.2f}M note converted into {into}: the note leg carried at cost is gone and the whole {after:.1%} stake is "
           f"marked at ${post:.1f}M post. The ${leg:.2f}M is in invested capital once. Confirm the conversion terms — the cap or "
           "discount applied, accrued interest, the share count — against the closing cap table.",
           points=(f"HC's **${leg:.2f}M note converted** into {into}; the separate note leg is **removed**.",
                   f"The whole **{after:.1%}** stake is marked at **${post:.1f}M** post; the ${leg:.2f}M is in invested capital **once**.",
                   "Confirm the **conversion terms** (cap or discount, accrued interest, share count) against the cap table."),
           suggestions=(
               Suggest("as_proposed", "Book the converted stake at the round price as proposed.", ("The round is an arm's-length price for the whole stake.", "Right when the cap table's ownership matches the row."), "proposed"),
           ),
           action="Confirm the note's conversion terms and that its principal is counted once.",
           note_leg=round(leg, 6), post_money=post, ownership_after=after)


_METRIC_WORDS = ("cash", "burn", "runway", "revenue", "arr", "headcount", "margin")


def _prose_metrics(w: Working, e: Event) -> None:
    """X-126 — operating metrics reported in the row's prose. The engine never reads a number out of a
    sentence, so a cash balance or burn rate in a note does not reach the runway screen: the Portfolio
    tab still carries the old figures. A person updates the tab (or confirms the note is not newer)
    and the screens re-run on the corrected inputs."""
    text = _text(e)
    hits = [t for t in _METRIC_WORDS if any_term_in((t,), text)]
    if not hits:
        return
    w.handled(e, *hits)
    w.flag("X-126", "liquidity", Severity.REVIEW,
           f"The row's note reports operating figures ({', '.join(hits)}) in prose. The engine does not read numbers out of a "
           "sentence, so the runway, growth and multiple screens still run on the Portfolio tab's columns, which this note may "
           f"supersede: \"{(e.notes or e.detail)[:160]}\"",
           points=(f"The note reports **{', '.join(hits)}** in prose; the screens read the **Portfolio tab**, not the note.",
                   "If the note is newer, the tab's cash, burn or ARR are **stale** and the runway screen is wrong.",
                   "Update the Portfolio tab from the note and rerun, or confirm the tab is current."),
           suggestions=(
               Suggest("as_proposed", "Keep the mark as proposed; update the Portfolio tab's metrics from the note and rerun.", ("A metric in prose is not an input until it is in the tab.", "Rerunning on the corrected tab re-screens runway and growth."), "proposed"),
               Suggest("at_cost", "Mark down to invested cost pending the raise.", ("Cost is a defensible floor for a company that must raise to survive.", "Right if the note says the cash is nearly gone."), "cost"),
           ),
           action="Update the Portfolio tab's Cash, Net Burn and ARR from the note (or confirm the tab is current), then rerun.",
           terms=hits, row_index=e.row_index)


@rule(rule_id="M-071", version=V, applies_to=(EventType.TERM_SHEET_WITHDRAWN.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=7,
      description="Term sheet withdrawn: the pending financing falls away; mark unchanged; an adverse signal a reviewer weighs.")
def term_sheet_withdrawn(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    had = [i for i in w.open_items if i.kind == OpenItemKind.TERM_SHEET]
    indicated = w.alternative_marks.pop("term_sheet_indicated", None)
    w.handled(e, "withdrawn", "withdrew", "cancelled", "canceled", "terminated", "rescinded", "lapsed", "supersede", "supersedes", "superseded")
    w.flags = [f for f in w.flags if f.rule_id != "X-109"]      # the disclosure is moot: the proposal is gone
    w.step("M-071", V, {"withdrawn": e.detail, "term_sheet_indicated": indicated, "open_term_sheets_closed": len(had)},
           w.proposed_mark, w.proposed_mark,
           f"Term sheet withdrawn ({e.detail}). No financing closed, no cash, no shares: the mark is unchanged at "
           f"${w.proposed_mark:.2f}M" + (f" and the ${indicated:.2f}M stake the term sheet indicated is no longer an alternative" if indicated else "")
           + ". A financing that fell through is evidence about the company, not a transaction in it.", e)
    w.flag("X-125", "treatment", Severity.REVIEW,
           f"A signed term sheet was withdrawn before closing. Nothing was booked from it, so the mark still rests on the last "
           f"round — but an investor walking away is evidence a market participant would not pay that price today, and the "
           "company still has to raise.",
           points=("A signed **term sheet was withdrawn**; nothing was booked from it.",
                   "An investor **walking away** is evidence about the last-round price, and the **raise is still ahead**.",
                   f"The mark stays at **${w.proposed_mark:.2f}M** until a reviewer says otherwise."),
           suggestions=(
               Suggest("as_proposed", "Hold the mark at the last round; the withdrawal changes the evidence, not the price paid.", ("No transaction occurred either way.", "Right if the company can still raise on its plan."), "proposed"),
               Suggest("at_cost", "Mark down to invested cost pending a new financing.", ("A failed raise is the strongest sign the last price is high.", "Cost is a defensible floor until the company prices again."), "cost"),
           ),
           action="Weigh the withdrawn financing: hold the last-round mark, or mark down pending a new raise.",
           detail=e.detail, term_sheet_indicated=indicated)
    _prose_metrics(w, e)


@rule(rule_id="M-072", version=V, applies_to=(EventType.OPERATING_UPDATE.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=7,
      description="Operating update: no transaction, mark unchanged; the figures it reports belong on the Portfolio tab.")
def operating_update(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    w.step("M-072", V, {"detail": e.detail}, w.proposed_mark, w.proposed_mark,
           f"Operating update ({e.detail}): no transaction, so the mark is unchanged at ${w.proposed_mark:.2f}M. Figures reported "
           "in the note belong on the Portfolio tab, where the screens read them.", e)
    _prose_metrics(w, e)
    if not any(f.rule_id == "X-126" for f in w.flags):
        w.flag("X-126", "liquidity", Severity.REVIEW,
               f"An operating update was recorded ({e.detail}) but its figures are not on the Portfolio tab; the screens ran on "
               "the tab's columns. Confirm the tab is current or update it and rerun.",
               points=("An **operating update** was recorded with **no figures in the columns**.",
                       "The screens ran on the **Portfolio tab**, which the update may supersede.",
                       "Confirm the tab is current, or update it and rerun."),
               suggestions=(Suggest("as_proposed", "Keep the mark as proposed; update the Portfolio tab and rerun.", ("No transaction occurred.", "The tab is the input; the note is context."), "proposed"),),
               action="Confirm the Portfolio tab reflects this update, then rerun.", detail=e.detail, row_index=e.row_index)


@rule(rule_id="M-015", version=V, applies_to=(EventType.SHARE_RESTRUCTURE.value,), severity=Severity.MONITOR,
      effective_from=EFFECTIVE, tier=4,
      description="Share restructure (split, reverse split, reclassification): no economic change; mark and ownership unchanged. "
                  "A row that also moves the ownership is a cap-table change and goes to a reviewer.")
def share_restructure(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    before = w.ownership
    after = float(e.ownership_after) if e.ownership_after is not None else before
    moved = abs(after - before) > cfg.exceptions.indications.restructure_ownership_tolerance
    w.step("M-015", V, {"detail": e.detail, "ownership_before": before, "ownership_after": after, "ownership_moved": moved},
           w.proposed_mark, w.proposed_mark,
           f"Share restructure ({e.detail}). Share counts change, economics do not: mark unchanged at ${w.proposed_mark:.2f}M"
           + (f"; the row's {after:.1%} ownership differs from the book's {before:.1%} and is not applied until confirmed." if moved
              else f"; ownership stays {before:.1%}."), e)
    if moved:
        w.flag("X-133", "treatment", Severity.REVIEW,
               f"A share restructure should not move HC's fully diluted stake, but the row says {after:.1%} against {before:.1%} in "
               "the book. Either the restructure was not neutral (a reclassification that converted preferred, a ratchet) or the "
               "cell is wrong. The mark holds on the book's ownership until a person says which.",
               points=(f"A split or reclassification is **not supposed to move the stake**, yet the row says **{after:.1%}** vs **{before:.1%}**.",
                       "Either the restructure **changed the economics** or the cell is **wrong**.",
                       "The mark holds on the **book's ownership** until confirmed."),
               suggestions=(
                   Suggest("as_proposed", "Hold the mark on the book's ownership; the restructure is neutral.", ("Share counts change, the fully diluted stake does not.", "Right when the cell is a share count read as a percentage."), "proposed"),
                   Suggest("at_new_ownership", f"Re-mark at the row's {after:.1%} on the last-round basis.", ("Right if the reclassification actually changed HC's stake.", "The last-round price is unchanged; only the share moved."), "value", value=round(after * w.latest_post + w.note_at_cost, 6)),
               ),
               action="Confirm on the cap table whether the restructure changed HC's fully diluted stake.",
               ownership_before=before, ownership_after=after, detail=e.detail)
    else:
        w.flag("X-133", "treatment", Severity.MONITOR,
               f"Share restructure recorded ({e.detail}): share counts changed, the fully diluted stake and the mark did not.",
               detail=e.detail, ownership=before)


@rule(rule_id="M-062", version=V, applies_to=(EventType.DEBT_FACILITY.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=6,
      description="Debt facility: debt is not a price, so the equity mark is unchanged. A loan HC itself made is carried at cost "
                  "on its own leg until repaid. Always a review: debt ranks ahead of the equity and changes the runway.")
def debt_facility(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    inv = float(e.hc_investment or 0.0)
    size = float(e.value) if e.value else None
    w.step("M-062", V, {"facility_musd": size, "hc_lent": inv, "detail": e.detail},
           w.proposed_mark, w.proposed_mark + inv,
           f"Debt facility ({e.detail}" + (f", ${size:.1f}M" if size else "") + "). Debt is not a price: equity mark unchanged at "
           f"${w.equity_mark:.2f}M." + (f" HC's ${inv:.2f}M loan carried at cost on its own leg." if inv else " HC is not the lender."), e)
    w.handled(e, "covenant", "default", "debt", "loan", "facility", "warrant")
    w.flag("X-127", "liquidity", Severity.REVIEW,
           f"The company took on debt" + (f" (${size:.1f}M)" if size else "") + f" ({e.detail}). Nothing about the equity price changed, "
           "but the debt ranks ahead of HC's shares, usually carries covenants and often warrants, and the drawn cash is not on the "
           "Portfolio tab until someone puts it there."
           + (f" HC lent ${inv:.2f}M, carried at cost." if inv else ""),
           points=(f"**Debt ahead of the equity**" + (f": **${size:.1f}M**" if size else "") + f" ({e.detail}).",
                   "Covenants, warrants and seniority change what HC's shares are worth in a downside; **the mark ignores them**.",
                   "If the cash was drawn, the tab's **cash and runway are stale** until updated."),
           suggestions=(
               Suggest("as_proposed", "Keep the equity mark; carry HC's loan (if any) at cost.", ("Debt is not a price for the equity.", "Standard treatment; revisit if covenants are breached."), "proposed"),
           ),
           action="Confirm seniority, covenants and any warrants attached; update the Portfolio tab's cash if the facility was drawn.",
           facility_musd=size, hc_lent=inv, detail=e.detail)
    if inv:
        w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.DEBT, opened=e.date, opened_quarter=w.quarter_label,
                                     amount_musd=inv, detail=e.detail))
        w.note_at_cost += inv
        w.invested += inv
        w.financings.append((e.date, e.event_type, inv))


@rule(rule_id="M-091", version=V, applies_to=(EventType.VALUATION_ADJUSTMENT.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=7,
      description="Valuation adjustment asserted on an activity row (write-down, impairment, write-up): not a transaction, so the "
                  "engine books nothing from it. The figure is offered as a priced option; the decision is the reviewer's (E-01).")
def valuation_adjustment(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    stated = w.ownership * float(e.value) if e.value else None
    w.step("M-091", V, {"stated_company_value": e.value, "ownership": w.ownership, "stated_mark": stated, "detail": e.detail},
           w.proposed_mark, w.proposed_mark,
           f"Valuation adjustment on the row ({e.detail}). No transaction: the engine proposes the evidence-based mark unchanged at "
           f"${w.proposed_mark:.2f}M" + (f"; the row's ${float(e.value):.1f}M would put HC at ${stated:.2f}M, offered as an option." if stated is not None else
                                        "; the row states no value.") + " A mark change without a transaction is a reviewer decision.", e)
    w.handled(e, "impairment", "write-down", "writedown", "write-off", "restated", "markdown")
    sugg = [Suggest("as_proposed", "Keep the evidence-based mark; record the adjustment as a reviewer decision if it stands.", ("The engine books transactions and observable inputs, not assertions.", "An override with a reason is the audit trail an adjustment needs."), "proposed")]
    if stated is not None:
        sugg.append(Suggest("at_stated", f"Book the row's stated valuation (${stated:.2f}M).", ("Right if a reviewer already decided this and the row records it.", "Recorded as an override addressed to this finding."), "value", value=round(stated, 6)))
    w.flag("X-128", "treatment", Severity.REVIEW,
           f"An activity row asserts a valuation adjustment ({e.detail})" + (f" to ${float(e.value):.1f}M company value, ${stated:.2f}M for HC" if stated is not None else "")
           + f". The engine does not book a mark from an assertion: the proposal stays at ${w.proposed_mark:.2f}M and the adjustment is "
           "a decision for a reviewer to record, with its reason.",
           points=(f"The row **asserts an adjustment** ({e.detail})" + (f" to **${stated:.2f}M**" if stated is not None else "") + ".",
                   "Not a transaction: the engine **books nothing from it**.",
                   "A mark change is a **reviewer decision**, recorded with a reason."),
           suggestions=tuple(sugg),
           action="Decide the adjustment as a reviewer override, or supply the transaction that supports it.",
           stated_company_value=e.value, stated_mark=stated, detail=e.detail)


@rule(rule_id="M-042", version=V, applies_to=(EventType.LOCKUP_EXPIRY.value,), severity=Severity.MONITOR,
      effective_from=EFFECTIVE, tier=4,
      description="Lock-up expiry on a listed position: the shares are now saleable; the lock-up item closes; the mark is the "
                  "market close (M-041) as before. On an unlisted position the row is a contradiction to confirm.")
def lockup_expiry(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    had = [i for i in w.open_items if i.kind == OpenItemKind.IPO_LOCKUP]
    w.step("M-042", V, {"detail": e.detail, "listed": w.listed, "lockups_closed": len(had)}, w.proposed_mark, w.proposed_mark,
           f"Lock-up expiry ({e.detail}). " + ("The shares are saleable; the lock-up item closes; the mark stays at the market close."
                                              if w.listed else "The book does not show this company as listed, so there is no lock-up to end."), e)
    w.handled(e, "lock-up", "lockup")
    if w.listed:
        w.flag("X-129", "treatment", Severity.MONITOR,
               f"Lock-up expired ({e.detail}): HC's shares are saleable. Nothing changes in the mark — a Level 1 price carries no "
               "lock-up discount under this policy — and the lock-up item is closed.",
               detail=e.detail, lockups_closed=len(had))
    else:
        w.flag("X-129", "treatment", Severity.REVIEW,
               f"A lock-up expiry was recorded ({e.detail}) but the book does not show the company as listed. Either the listing "
               "was never recorded on the Portfolio tab (Stage = Public) or the row is on the wrong company.",
               points=("**Lock-up expiry on an unlisted position.**",
                       "Either the **listing was never recorded** on the tab, or the row is on the **wrong company**.",
                       "The mark is unchanged until this is confirmed."),
               suggestions=(Suggest("as_proposed", "Hold the mark; correct the tab or the row and rerun.", ("Nothing on the row prices the position.", "A listing must be on the tab for the market close to apply."), "proposed"),),
               action="Confirm whether the company is listed; if so, mark the Portfolio tab's Stage as Public and rerun.",
               detail=e.detail)


# --------------------------------------------------------------------------- M-013

@rule(rule_id="M-013", version=V, applies_to=(EventType.OWNERSHIP_ADJUSTMENT.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=4,
      description="Ownership adjustment with no price event (warrant exercise, pool expansion, cap-table restatement): "
                  "re-marks at the new ownership on the unchanged last-round basis; staleness clock untouched.")
def ownership_adjustment(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    before = w.ownership
    after = float(e.ownership_after if e.ownership_after is not None else before)
    inv = float(e.hc_investment or 0.0)
    new_equity = after * w.latest_post
    w.step("M-013", V, {"ownership_before": before, "ownership_after": after, "hc_investment": inv,
                        "latest_post_money": w.latest_post, "detail": e.detail},
           w.proposed_mark, new_equity + w.note_at_cost,
           f"Ownership {before:.1%} → {after:.1%} with no price event ({e.detail}). Mark = {after:.1%} × ${w.latest_post:.1f}M on the "
           "unchanged last-round basis" + (f"; ${inv:.2f}M paid (warrant strike) added to cost." if inv else ".")
           + f" The staleness clock still runs from {w.staleness_anchor.isoformat()}.", e,
           formula=f"{after:.1%} × ${w.latest_post:.1f}M = ${new_equity:.2f}M" + (f" + note at cost ${w.note_at_cost:.2f}M" if w.note_at_cost else ""))
    w.flag("X-110", "treatment", Severity.REVIEW,
           f"Ownership moved from {before:.1%} to {after:.1%} with no price event. The mark follows the cap table mechanically, "
           "but a stake that changes without a round means someone restated the table, exercised something or expanded the "
           "pool — and the round basis it is priced on may no longer describe the same security.",
           points=(f"Ownership moved **{before:.1%} → {after:.1%}** with **no price event**.",
                   "Someone **restated the cap table**, exercised something, or expanded the pool.",
                   "The round basis may **no longer price the same security**."),
           suggestions=(
               Suggest("as_proposed", "Book the mechanical mark on the new ownership, as proposed.", ("The cap table is the source of truth for the stake.", "The price basis is unchanged; only the share moved."), "proposed"),
               Suggest("hold_prior", "Hold the prior mark until the cap table is confirmed.", ("A stake change with no round often means a restatement.", "Avoids booking a movement that may be reversed."), "prior"),
           ),
           action="Confirm the cap table: what moved the ownership, and whether the last-round price still applies to it.",
           ownership_before=before, ownership_after=after, hc_investment=inv)
    w.equity_mark = new_equity
    w.ownership = after
    w.invested += inv
    # staleness_anchor and latest_post deliberately unchanged: nothing was re-priced


# --------------------------------------------------------------------------- M-014

@rule(rule_id="M-014", version=V, applies_to=(EventType.NEW_INVESTMENT.value,), severity=Severity.MONITOR,
      effective_from=EFFECTIVE, tier=3,
      description="New investment: first check into a company, entered at cost (ownership × post-money of the entry round). "
                  "A company not in the book is synthesised by the orchestrator and additionally raises X-918.")
def new_investment(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    post = float(e.value or 0.0)
    after = float(e.ownership_after if e.ownership_after is not None else w.ownership)
    inv = float(e.hc_investment or 0.0)
    new_equity = after * post
    created = bool(w.pos.extra.get("synthesised"))
    w.step("M-014", V, {"post_money": post, "ownership_after": after, "hc_investment": inv, "detail": e.detail,
                        "position_created": created},
           w.proposed_mark, new_equity + w.note_at_cost,
           f"New investment ({e.detail}): ${inv:.2f}M for {after:.1%} at ${post:.1f}M post. Mark = {after:.1%} × ${post:.1f}M "
           "— entered at the price HC just paid, the freshest arm's-length evidence there is."
           + (" The company was not in the Portfolio tab; the position was created from this row." if created else ""), e,
           formula=f"{after:.1%} × ${post:.1f}M = ${new_equity:.2f}M")
    w.flag("X-120", "treatment", Severity.MONITOR,
           f"New position entered at cost: {after:.1%} of a ${post:.1f}M post-money for ${inv:.2f}M. Nothing to decide — "
           "the entry price is the mark.",
           post_money=post, ownership_after=after, hc_investment=inv)
    if created:
        w.flag("X-918", "data", Severity.REVIEW,
               f"{w.pos.company} is not in the Portfolio tab. The engine created the position from the activity row "
               f"(fund {w.pos.fund!r}, sector {w.pos.sector!r}, stage {w.pos.stage!r}); anything the row does not say is a placeholder.",
               points=(f"{w.pos.company} is **not in the Portfolio tab**.",
                       f"The position was **created from activity row {e.row_index}**.",
                       "Anything that row does not say — fund, sector, stage — is a **placeholder**."),
               suggestions=(
                   Suggest("as_proposed", "Book on the activity row's terms as proposed.", ("The row is the only record of the position.", "Placeholders are corrected once the Portfolio tab has the company."), "proposed"),
               ),
               action="Add the company to the Portfolio tab with its fund, sector and stage, and confirm the entry terms.",
               fund=w.pos.fund, sector=w.pos.sector, stage=w.pos.stage, row_index=e.row_index)
    w.equity_mark = new_equity
    w.ownership = after
    w.invested += inv
    w.financings.append((e.date, e.event_type, inv))
    w.latest_post = post
    w.latest_round = e.date
    w.staleness_anchor = e.date
    w.status = Status.ACTIVE
    w.terminal = False
    w.stage = _stage_from_detail(e.detail) or w.stage or "Unknown"
    w.fv_level = 3


def synthesise_position(e: Event, known_sectors: set[str], template: Position | None = None) -> Position:
    """M-014 for a company that is not in the book: a zero position built from the activity row,
    so it runs through the same chain, flags and result as every other company. Fund from
    Notes/Detail (`Fund I/II/III`) else `Unassigned`; sector from Detail/Notes if it names a
    known sector else `Unclassified`; stage from Detail else `Unknown`."""
    text = f"{e.detail} {e.notes}"
    m = _FUND_RE.search(text)
    fund = f"Fund {m.group(1).upper()}" if m else "Unassigned"
    low = text.lower()
    sector = next((s for s in sorted(known_sectors) if s.lower() in low), "Unclassified")
    return Position(
        company=e.company, sector=sector, fund=fund, stage=_stage_from_detail(e.detail) or "Unknown",
        status=Status.ACTIVE, first_investment=e.date, latest_round=e.date,
        latest_post_money=0.0, invested=0.0, ownership=0.0, prior_mark=0.0, realized=0.0,
        row_index=e.row_index, extra={"synthesised": True, "activity_sheet_row": e.row_index},
    )


# --------------------------------------------------------------------------- M-022

@rule(rule_id="M-022", version=V, applies_to=(EventType.DISTRIBUTION.value,), severity=Severity.MONITOR,
      effective_from=EFFECTIVE, tier=4,
      description="Distribution: cash to HC with no change in the stake (dividend, escrow release, earn-out, holdback). "
                  "Realized up; mark unchanged. Allowed on Acquired / Shut Down companies.")
def distribution(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    proceeds = float(e.proceeds or 0.0)
    w.step("M-022", V, {"proceeds": proceeds, "ownership": w.ownership, "status": w.status.value, "detail": e.detail},
           w.proposed_mark, w.proposed_mark,
           formula=f"realized ${w.pos.realized + w.realized_quarter:.2f}M + ${proceeds:.2f}M = ${w.pos.realized + w.realized_quarter + proceeds:.2f}M; mark unchanged",
           rationale=f"Cash distribution of ${proceeds:.2f}M ({e.detail}); the stake is unchanged, so the mark is unchanged and the cash "
           "goes to realized proceeds."
           + (f" The position was already {w.status.value}; this is money arriving after the exit." if w.terminal else ""), e=e)
    carrying = w.equity_mark + w.note_at_cost
    if w.terminal:
        # Cash from a company that is already gone: liquidation language is the row's own nature here
        w.handled(e, "liquidating", "liquidation", "dissolved", "dissolution", "wind-down", "wind down", "wound up", "estate", "residual")
    if not w.terminal and proceeds > max(carrying, w.invested) + cfg.tolerances.prior_mark_reconciliation_musd:
        w.flag("X-111", "treatment", Severity.REVIEW,
               f"A ${proceeds:.2f}M distribution against a ${carrying:.2f}M carrying value (${w.invested:.2f}M invested) with the stake "
               "unchanged is not a dividend: it reads like a sale, a liquidation or a return of capital typed as a distribution, and "
               "the mark still stands at the full carrying value.",
               points=(f"**${proceeds:.2f}M distributed** against a **${carrying:.2f}M** carrying value; stake unchanged.",
                       "Larger than the mark and than invested capital: a **sale, liquidation or return of capital**, not a dividend.",
                       "The mark **still stands** at the full carrying value."),
               suggestions=(
                   Suggest("as_proposed", "Book the cash as realized and keep the mark; confirm it really is a distribution.", ("Cash received is the fact.", "Right only if the company and HC's stake are intact."), "proposed"),
                   Suggest("write_to_zero", "Treat it as the exit it looks like: cash realized, mark written to zero.", ("A distribution of the company's proceeds leaves nothing behind.", "Refile the row as an exit or shutdown next quarter."), "value", value=0.0),
               ),
               action=f"Confirm what the ${proceeds:.2f}M was: a dividend with the company intact, or the company's proceeds on exit or liquidation.",
               proceeds=proceeds, carrying_value=round(carrying, 6), invested=round(w.invested, 6))
        w.handled(e, "liquidating", "liquidation", "dissolved", "dissolution", "sale of the business", "wound up", "wind-down", "wind down")
    else:
        w.flag("X-111", "treatment", Severity.MONITOR,
               f"Cash distribution of ${proceeds:.2f}M received; stake unchanged. Nothing to decide — realized proceeds rise, "
               "the mark does not move.",
               proceeds=proceeds)
    w.realized_quarter += proceeds
    # An exit earlier in the quarter whose cash fell short of the deal value raised X-101 for the
    # gap; a distribution that closes the gap (an escrow or holdback released) resolves it.
    tol = cfg.tolerances.prior_mark_reconciliation_musd * 10
    for i, f in enumerate(list(w.flags)):
        if f.rule_id == "X-101" and "implied" in f.evidence and f.severity == Severity.REVIEW:
            received = float(f.evidence["proceeds"]) + proceeds
            if abs(float(f.evidence["implied"]) - received) <= tol:
                w.drop_flag(i)
                last = w.steps[-1]
                w.steps[-1] = last.model_copy(update={
                    "inputs": {**last.inputs, "proceeds_now_received": round(received, 6), "implied_from_deal_value": f.evidence["implied"]},
                    "rationale": last.rationale + (f" It closes the gap between the exit's ${float(f.evidence['proceeds']):.2f}M of "
                                                   f"proceeds and the ${float(f.evidence['implied']):.2f}M the deal value implied; "
                                                   "the reconciliation question on the exit is resolved.")})
                break


# --------------------------------------------------------------------------- M-025

@rule(rule_id="M-025", version=V, applies_to=(EventType.BANKRUPTCY_CH11.value,), severity=Severity.BLOCK,
      effective_from=EFFECTIVE, tier=2,
      description="Chapter 11 reorganisation: going concern, not terminal. Mark unchanged, always blocks — a recovery estimate is a human's job.")
def chapter_11(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    w.step("M-025", V, {"prior_mark": w.equity_mark, "detail": e.detail},
           w.proposed_mark, w.proposed_mark,
           f"Chapter 11 filing ({e.detail}). The company continues as a going concern under court supervision, so this is not a "
           f"write-off — but the ${w.equity_mark:.2f}M carrying value rests on a round priced for a company that was not in "
           "bankruptcy. Mark held unchanged pending a recovery estimate; nothing mechanical can produce one.", e)
    w.flag("X-116", "treatment", Severity.BLOCK,
           f"Chapter 11: the ${w.equity_mark:.2f}M carrying value is almost certainly impaired. In a reorganisation the equity "
           "usually sits behind DIP financing and every class of creditor, and what comes out the other side is a different "
           "security. The workbook has no recovery estimate; only the plan of reorganisation does.",
           points=(f"**Chapter 11** — the **${w.equity_mark:.2f}M** carrying value is almost certainly impaired.",
                   "Equity sits **behind DIP financing and every creditor class**.",
                   "Only the **plan of reorganisation** carries a recovery estimate; the workbook has none."),
           suggestions=(
               Suggest("write_to_zero", "Write the position to zero pending the plan of reorganisation.", ("Equity sits behind DIP financing and every creditor class.", "Recovery to old equity in Chapter 11 is usually nil."), "value", value=0.0),
               Suggest("hold_prior", "Hold the prior mark until the plan is filed.", ("Defers the impairment until a recovery estimate exists.", "Overstates if the plan wipes out equity — short-term only."), "prior"),
           ),
           action="Estimate recovery to HC's class under the plan and book that; the carrying value is almost certainly impaired.",
           prior_mark=round(w.equity_mark, 6))
    w.fv_level = 3
    # not terminal: the company is operating. Carry-side screens still run.


# --------------------------------------------------------------------------- M-031

@rule(rule_id="M-031", version=V, applies_to=(EventType.SECONDARY_PURCHASE.value,), severity=Severity.MONITOR,
      effective_from=EFFECTIVE, tier=4,
      description="Secondary purchase: HC buys more of an existing position from another holder. Ownership up, cost up, "
                  "remainder marked at the last round; the implied price is recorded as an alternative and screened.")
def secondary_purchase(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    before = w.ownership
    after = float(e.ownership_after if e.ownership_after is not None else before)
    bought = after - before
    inv = float(e.hc_investment or 0.0)
    implied_post = inv / bought if (bought > 1e-12 and inv) else None
    at_last_round = after * w.latest_post
    at_implied = after * implied_post if implied_post else None
    spread = ratio_change(implied_post, w.latest_post) if (implied_post and w.latest_post) else None

    if bought <= 1e-12:
        w.step("M-031", V, {"ownership_before": before, "ownership_after": after, "hc_investment": inv,
                            "last_round_post_money": w.latest_post},
               w.proposed_mark, w.proposed_mark,
               f"Secondary purchase recorded with no ownership increase ({before:.1%} → {after:.1%}); ${inv:.2f}M paid cannot be "
               "tied to a block bought. Mark unchanged; position blocked for a human to reconcile the row.", e)
        w.flag("X-101", "treatment", Severity.BLOCK,
               f"The row records ${inv:.2f}M paid for shares but no increase in ownership, so there is no block bought to price "
               "the purchase against. One of the two figures is wrong.",
               points=(f"Row records **${inv:.2f}M paid** for shares but **no increase in ownership**.",
                       "There is no block bought to price the purchase against.",
                       "**One of the two figures is wrong.**"),
               suggestions=(
                   Suggest("hold_prior", "Hold the prior mark; correct the activity row and rerun.", ("A purchase with no stake bought cannot be priced.", "Fixing the row is the clean resolution — nothing to book until then."), "prior"),
               ),
               action="Reconcile the activity row: cash was paid but the stake did not grow.",
               hc_investment=inv, ownership_before=before, ownership_after=after)
        w.invested += inv
        return

    w.step("M-031", V, {"ownership_before": before, "ownership_after": after, "ownership_bought": round(bought, 6),
                        "hc_investment": inv, "implied_post_money": implied_post, "last_round_post_money": w.latest_post,
                        "at_last_round": at_last_round, "at_implied_price": at_implied, "detail": e.detail},
           w.proposed_mark, at_last_round + w.note_at_cost,
           formula=(f"{after:.1%} × ${w.latest_post:.1f}M = ${at_last_round:.2f}M at the last round"
                    + (f" · implied ${inv:.2f}M ÷ {bought:.1%} = ${implied_post:.1f}M post" if implied_post else "")),
           rationale=f"Bought {bought:.1%} more of the company for ${inv:.2f}M"
           + (f" (implies ${implied_post:.1f}M post vs ${w.latest_post:.1f}M last round" + (f", {spread:+.1%})" if spread is not None else ")")
              if implied_post else "")
           + f". Whole stake {after:.1%} marked at the last-round price: one buyer taking one block is evidence, not the principal market.", e=e)
    if at_implied is not None:
        w.alternative_marks["at_implied_price"] = at_implied
    w.handled(e, "discount", "premium", "secondary", "block", "spread", "partial", "no new capital")
    if spread is not None and abs(spread) > cfg.exceptions.secondary.spread_tolerance_pct:
        w.flag("X-104", "treatment", Severity.REVIEW,
               f"HC paid a price that implies the company is worth ${implied_post:.1f}M, {spread:+.1%} against the ${w.latest_post:.1f}M "
               "the last round set. Policy marks the whole stake at the round price, so the block just bought is carried "
               f"{'below' if spread > 0 else 'above'} what HC paid for it. On the purchase price the stake would be ${at_implied:.2f}M instead.",
               points=(f"HC paid a price implying **${implied_post:.1f}M**, **{spread:+.1%}** against the ${w.latest_post:.1f}M round.",
                       f"Policy marks the whole stake at the round price, so the new block is carried **{'below' if spread > 0 else 'above'} what HC paid**.",
                       f"On the purchase price the stake would be **${at_implied:.2f}M** instead."),
               suggestions=(
                   Suggest("as_proposed", "Keep the whole stake at the last-round price.", ("Policy: one block is weaker evidence than a priced round.", "The purchase price is recorded as an alternative mark."), "proposed"),
                   Suggest("at_purchase", f"Mark the stake at the price HC just paid ({spread:+.1%}).", ("HC's own transaction is the most recent price in this security.", "Right if the purchase was at arm's length from an informed seller."), "alternative", value="at_implied_price"),
               ),
               action="Decide whether the stake follows the last round or the price HC just paid for the block.",
               spread=round(spread, 4), implied_post_money=implied_post, basis="last_round", direction="purchase")
    else:
        w.flag("X-121", "treatment", Severity.MONITOR,
               f"Bought {bought:.1%} more at the last-round price"
               + (f" (implied ${implied_post:.1f}M vs ${w.latest_post:.1f}M)" if implied_post else "")
               + ". Cost and ownership rise together; nothing to decide.",
               ownership_bought=round(bought, 6), hc_investment=inv, implied_post_money=implied_post)
    w.equity_mark = at_last_round
    w.ownership = after
    w.invested += inv


# --------------------------------------------------------------------------- M-041 (carry side)

@rule(rule_id="M-041", version=V, applies_to=(), severity=Severity.BLOCK, effective_from=EFFECTIVE, tier=8,
      description="Listed carry: a public position with no event re-marks to the measurement-date market cap (Level 1). "
                  "Applied by the orchestrator in place of M-000; blocks when no quote is available.")
def _m041_doc(w, e, cfg, market):  # pragma: no cover - carry-side step applied by run.py via listed_carry
    raise NotImplementedError


# A quote the feed could not observe: the fixture's seed (`stub:`), a listing-day print standing in
# for the close (`ipo_print`), anything labelled seeded. The mark that rests on one is provisional
# (run.py), and a listed carry on one raises X-113 so the missing close is a finding a decision can
# name — found by the synthetic Q4 2026 chain, where the quarter after an IPO blocked with no flag.
STANDIN_PRICE_SOURCES = ("stub:", "seeded", "ipo_print")


def is_standin_price(source: object) -> bool:
    src = str(source or "")
    return src.startswith(STANDIN_PRICE_SOURCES) or "seeded" in src


def price_source_words(source: object, short: bool = False) -> str:
    """The quote's provenance in words a reviewer reads; the machine label stays in the step inputs.
    `short` is for a bullet that already says what stands in."""
    src = str(source or "")
    if src == "stub:seeded_to_ipo_print":
        return "a stand-in, not a close" if short else "a stand-in seeded to the listing price, not an exchange close"
    if src.startswith("stub:seeded_to_ipo_print"):
        return "a drifted stand-in, not a close" if short else "a stand-in drifted from the listing price, not an exchange close"
    if src == "ipo_print":
        return "the listing price"
    if src.startswith("live:"):
        return "the exchange close"
    if src.startswith("stub:"):
        return "illustrative, not an exchange close"
    return src.replace("_", " ") or "unknown"


def listed_carry(w: Working, cfg: RuleConfig, market: MarketData) -> None:
    """A listed position has a daily price; carrying last quarter's number forward is a stale mark,
    not a carry. With a quote: ownership × market cap, Level 1. Without: M-000 and X-113 BLOCK.
    With a stand-in quote (no feed can price a fictional ticker; the fixture seeds the prior close):
    the stand-in is used so the chain shows the arithmetic, and X-113 BLOCK says the close is missing."""
    md = cfg.quarter.measurement_date
    quote = market.quotes.get(w.pos.company)
    w.listed = True
    if quote is None:
        w.step("M-000", V, {"prior_mark": w.pos.prior_mark, "ownership": w.ownership, "latest_post_money": w.latest_post,
                            "listed": True, "quote": None},
               w.proposed_mark, w.proposed_mark,
               f"Listed position with no {md.isoformat()} quote in the market data; prior mark carried unchanged and the position "
               "blocked — a public security carried at last quarter's price is not a fair value.")
        w.flag("X-113", "treatment", Severity.BLOCK,
               f"{w.pos.company} is listed but the market data has no price for it at {md.isoformat()}. The ${w.equity_mark:.2f}M "
               "carried forward is last quarter's number, and a Level 1 security is worth its close, not its history.",
               points=(f"Listed, but the market data has **no price at {md.isoformat()}**.",
                       f"The **${w.equity_mark:.2f}M** carried is **last quarter's number**.",
                       "A **Level 1** security is worth its close, not its history."),
               suggestions=(
                   Suggest("hold_prior", "Hold last quarter's mark until the close is supplied.", ("The only stopgap without a quote; a stale Level 1 mark is still wrong.", "Rerun once the market cap is in the feed."), "prior"),
               ),
               action=f"Supply the {md.strftime('%d %b %Y')} closing market capitalisation and re-run.",
               measurement_date=md, prior_mark=round(w.equity_mark, 6))
        w.fv_level = 1
        return
    cap = quote.market_cap_musd
    new_equity = w.ownership * cap
    w.market_note = quote.note
    w.step("M-041", V, {"measurement_date_market_cap": cap, "price_source": quote.source, "ownership": w.ownership,
                        "prior_market_cap": w.latest_post, "quote_as_of": quote.as_of},
           w.proposed_mark, new_equity + w.note_at_cost,
           f"Listed position, no event. Mark = {w.ownership:.1%} × ${cap:,.0f}M market cap at {md.isoformat()} ({price_source_words(quote.source)})"
           + (f" vs ${w.latest_post:,.0f}M at the prior close" if w.latest_post else "") + ". Level 1.",
           formula=f"{w.ownership:.1%} × ${cap:,.0f}M = ${new_equity:.2f}M" + (f" + note at cost ${w.note_at_cost:.2f}M" if w.note_at_cost else ""))
    w.equity_mark = new_equity
    w.latest_post = cap
    w.staleness_anchor = md
    w.fv_level = 1
    if is_standin_price(quote.source):
        w.flag("X-113", "treatment", Severity.BLOCK,
               f"{w.pos.company} is listed, and the market data has no {md.isoformat()} close for it: the ${cap:,.0f}M market "
               f"cap behind the mark is {price_source_words(quote.source)}. A Level 1 security is worth its close, so "
               "the position cannot be booked until the quarter-end market capitalisation is supplied.",
               points=(f"Listed, but the market data has **no close at {md.isoformat()}**.",
                       f"The **${cap:,.0f}M market cap** in the mark is **{price_source_words(quote.source)}**.",
                       "A **Level 1** security is worth its close; supply it to book the position."),
               suggestions=(
                   Suggest("hold_prior", "Hold last quarter's mark until the close is supplied.", ("The only stopgap without a quote; a stale Level 1 mark is still wrong.", "Rerun once the market cap is in the feed."), "prior"),
               ),
               action=f"Supply the {md.strftime('%d %b %Y')} closing market capitalisation.",
               measurement_date=md, price_source=quote.source, stand_in_market_cap=cap, prior_mark=round(w.pos.prior_mark, 6))


# --------------------------------------------------------------------------- M-051

@rule(rule_id="M-051", version=V, applies_to=(EventType.ACQ_TERMINATED.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=5,
      description="Announced deal terminated: mark reverts to the last-round basis; the pending_acquisition item is dropped.")
def deal_terminated(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    new_equity = w.ownership * w.latest_post
    fee = float(e.proceeds or 0.0)       # a break fee: cash to HC with the stake unchanged, like a distribution
    w.step("M-051", V, {"ownership": w.ownership, "last_round_post_money": w.latest_post, "prior_mark": w.equity_mark,
                        "detail": e.detail, "break_fee": fee},
           w.proposed_mark, new_equity + w.note_at_cost,
           formula=f"{w.ownership:.1%} × ${w.latest_post:.1f}M = ${new_equity:.2f}M" + (f" · ${fee:.2f}M break fee → realized" if fee else ""),
           rationale=f"Announced acquisition terminated ({e.detail}). The deal-based mark no longer has a deal behind it: reverted to "
           f"{w.ownership:.1%} × ${w.latest_post:.1f}M last-round post = ${new_equity:.2f}M. Staleness clock unchanged "
           f"(runs from {w.staleness_anchor.isoformat()})."
           + (f" ${fee:.2f}M received (break fee) goes to realized proceeds; the stake is unchanged." if fee else ""), e=e)
    if fee:
        w.realized_quarter += fee
        w.handled(e, "break fee", "termination fee", "fee", "fees")
    w.flag("X-114", "treatment", Severity.REVIEW,
           f"The announced deal fell through; the mark has gone back to the last round at ${new_equity:.2f}M from ${w.equity_mark:.2f}M. "
           "A failed sale process is information — the round that set this price predates it, and the reason the deal broke "
           "may be a reason the round basis no longer holds.",
           points=(f"Announced deal **fell through**; the mark reverts to the last round: ${w.equity_mark:.2f}M → **${new_equity:.2f}M**.",
                   "A **failed sale process is information** — the round that set this price predates it.",
                   "Why the deal broke may be why the **round basis no longer holds**."),
           suggestions=(
               Suggest("as_proposed", "Revert to the last-round mark as proposed.", ("The signed deal no longer exists; the round is the last real price.", "Policy default when a sale process fails."), "proposed"),
               Suggest("hold_deal", "Hold the deal-based mark for one more quarter.", ("A new buyer may already be engaged; avoids whipsawing the mark.", "Only if a replacement process is under way."), "alternative", value="hold_deal_based"),
           ),
           action="Confirm nothing about the round basis has changed — why the deal broke, and whether the company is still the one the round priced.",
           reverted_to=round(new_equity, 6), from_mark=round(w.equity_mark, 6), last_round_post_money=w.latest_post, break_fee=fee)
    w.alternative_marks["hold_deal_based"] = w.equity_mark
    w.equity_mark = new_equity
    w.fv_level = 3


# --------------------------------------------------------------------------- M-061

@rule(rule_id="M-061", version=V, applies_to=(EventType.NOTE_REPAID.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=4,
      description="Note repaid in cash rather than converted: proceeds realized; the note leg carried at cost is reduced by the principal; equity unchanged.")
def note_repaid(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    proceeds = float(e.proceeds or 0.0)
    principal = float(e.hc_investment) if e.hc_investment is not None else proceeds
    note_before = w.note_at_cost
    note_after = max(0.0, note_before - principal)
    unmatched = principal - (note_before - note_after)   # principal the note leg did not hold (it sat inside the prior mark)
    w.step("M-061", V, {"proceeds": proceeds, "principal": principal, "note_at_cost_before": note_before,
                        "note_at_cost_after": note_after, "principal_not_in_note_leg": round(unmatched, 6), "detail": e.detail},
           w.proposed_mark, w.equity_mark + note_after,
           f"Note repaid ({e.detail}): ${proceeds:.2f}M received. Note leg ${note_before:.2f}M → ${note_after:.2f}M after "
           f"${principal:.2f}M principal; equity mark unchanged at ${w.equity_mark:.2f}M."
           + (f" ${unmatched:.2f}M of principal was not in the note leg — if it sits inside the prior mark, that basis is overstated." if unmatched > 1e-9 else ""), e)
    w.realized_quarter += proceeds
    w.note_at_cost = note_after
    w.open_items = [i for i in w.open_items if i.kind != OpenItemKind.CONVERTIBLE_NOTE]   # repaid, not outstanding
    if w.terminal or w.equity_mark <= 1e-9:
        return          # nothing is carried that the principal could sit inside: cash in, nothing to decide
    w.flag("X-115", "treatment", Severity.REVIEW,
           f"The bridge note was repaid in cash (${proceeds:.2f}M) rather than converting. The engine has reduced the note leg by "
           f"${principal - unmatched:.2f}M; " + (f"the remaining ${unmatched:.2f}M of principal was not carried as a separate leg, "
                                                  "so if it sat inside the prior mark the carrying basis is now overstated by that amount."
                                                  if unmatched > 1e-9 else "the equity mark is untouched."),
           points=(f"Bridge note **repaid in cash** (${proceeds:.2f}M) rather than converting.",
                   f"The note leg is reduced by **${principal - unmatched:.2f}M**.",
                   (f"**${unmatched:.2f}M of principal** was not a separate leg — if it sat inside the prior mark the basis is now **overstated**." if unmatched > 1e-9 else "The **equity mark is untouched**.")),
           suggestions=(
               Suggest("as_proposed", "Book the equity mark with the note leg removed, as proposed.", ("The repaid principal was carried as a separate leg.", "Nothing else in the position changed."), "proposed"),
               Suggest("reduce_basis", f"Reduce the carrying basis by the ${unmatched:.2f}M unmatched principal.", ("That principal sat inside the prior mark, not in the note leg.", "Prevents overstating the basis after repayment."), "value", value=max(0.0, w.proposed_mark - unmatched)),
           ),
           action="Confirm where the note sat: if it was inside the prior mark, reduce the carrying basis by the principal.",
           proceeds=proceeds, principal=principal, note_at_cost_before=note_before, note_at_cost_after=note_after,
           principal_not_in_note_leg=round(unmatched, 6))


# --------------------------------------------------------------------------- M-999
UNKNOWN_RULE_ID = "M-999"


@rule(rule_id="M-999", version=V, applies_to=("*",), severity=Severity.BLOCK, effective_from=EFFECTIVE, tier=0,
      description="Unrecognised event type: mark unchanged, position blocked, never a silent carry.")
def unrecognised(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    w.step("M-999", V, {"event_type": e.event_type, "detail": e.detail, "value": e.value},
           w.proposed_mark, w.proposed_mark,
           f"No marking rule covers a {e.event_type!r}. The mark is held and the position is blocked until a person decides: "
           "an event the engine does not understand must never look like an uneventful quarter.", e)
    w.flag("M-999", "treatment", Severity.BLOCK,
           f"No rule covers a {e.event_type!r} ({e.detail}). The mark is unchanged and the position is held, because an event the "
           "engine does not understand must never look like a quarter in which nothing happened.",
           points=(f"**No rule covers** a {e.event_type!r} ({e.detail}).",
                   "The mark is **unchanged** and the position is **held**.",
                   "An event the engine does not understand must **never look like a quiet quarter**."),
           suggestions=(
               Suggest("hold_prior", "Hold the prior mark until a rule covers the event.", ("An event the engine does not understand must not book a number.", "A rule for this event type goes in the policy file, approved and dated, before it can price anything."), "prior"),
           ),
           action=f"Decide how a {e.event_type!r} should be treated, then accept it once or promote it to a rule.",
           event_type=e.event_type, signature=e.signature)


# --------------------------------------------------------------------------- M-080 (post-roll, config-gated)

@rule(rule_id="M-080", version=V, applies_to=(), severity=None, effective_from=EFFECTIVE, tier=9,
      description="Stale-round comps calibration (on; gated to a live comps history): writes an alternative mark only.")
def _m080_doc(w, e, cfg, market):  # pragma: no cover - post-roll step applied by run.py via calibrate_stale
    raise NotImplementedError


def calibrate_stale(w: Working, cfg: RuleConfig, market: MarketData) -> None:
    """Writes an *alternative* mark; never touches equity_mark.

    factor = how the sector's public comps re-rated from the round month to the measurement
    month, bounded ±bound_pct. The re-rating is measured name by name over the same names
    (engine/rerating.py): each constituent priced at both ends contributes its own now ÷ then,
    and the sector's factor is the median of those — never one basket median divided by another,
    which with five-name baskets compares two different companies and moves whenever a name
    enters the basket. Each end is a name's median over ±`anchor_window_months` so one
    month-end print does not set the number. With `require_live_history` (the default) the
    sector's comps must be an observed public history (source `live:*`); the vendor-shaped
    fixture carries no names and never calibrates. When the round month itself has no values
    the nearest month inside `round_month_tolerance` is used, and the month actually used is
    recorded on the step."""
    c = cfg.marking.calibration
    # the same exposure test as the multiple screens and the sensitivity: Level 3, with an ARR above the floor
    if not c.enabled or w.terminal or w.listed or w.pos.arr is None or w.pos.arr < cfg.exceptions.multiple.min_arr:
        return
    # a signed deal or the buyer's shares price the position now; a comps ratio has nothing to calibrate
    if any(i.kind in (OpenItemKind.PENDING_ACQUISITION, OpenItemKind.ACQUIRER_SHARES) for i in w.open_items):
        return
    md = cfg.quarter.measurement_date
    age = months_between(w.staleness_anchor, md)
    if age <= c.min_age_months:            # the same test as X-201: strictly older than the monitor threshold
        return
    hist = market.comp_history.get(w.pos.sector)
    comp = market.comps.get(w.pos.sector)
    if not hist or comp is None:
        return
    if c.require_live_history and not comp.source.startswith("live:"):
        return
    k_now = md.strftime("%Y-%m")
    k_round = w.staleness_anchor.strftime("%Y-%m")
    rr = sector_rerating(market, w.pos.sector, k_round, k_now, window=c.anchor_window_months, min_names=c.min_same_set_names)
    k_then = k_round
    if rr is None:
        k_then = _nearest_month(hist, k_round, c.round_month_tolerance)
        if k_then is None or k_then == k_round:
            return
        rr = sector_rerating(market, w.pos.sector, k_then, k_now, window=c.anchor_window_months, min_names=c.min_same_set_names)
        if rr is None:
            return
    raw = rr.factor
    factor = max(1 - c.bound_pct, min(1 + c.bound_pct, raw))
    bounded = abs(raw - factor) > 1e-9
    counts = market.comp_counts.get(w.pos.sector) or {}
    alt = round(w.equity_mark * factor, 6)
    w.alternative_marks["calibrated_to_comps"] = alt
    below_cost = w.invested > 0 and alt < w.invested
    same_set = rr.method == SAME_SET
    how = (f"median of {rr.n_names} names' own moves ({rr.formula()})" if same_set
           else f"basket median {hist.get(k_then, 0):.2f}× → {hist.get(k_now, 0):.2f}× (no per-name history: {rr.method})")
    priced = market.priced_as_of
    w.step("M-080", V, {"comp_multiple_now": hist.get(k_now), "comp_multiple_at_round": hist.get(k_then), "round_month": k_round,
                        "comp_month_used": k_then, "factor_raw": round(raw, 4), "factor_bounded": round(factor, 4),
                        "bound_hit": bounded, "age_months": age, "sector": w.pos.sector, "comps_source": comp.source,
                        "n_constituents_at_round": counts.get(k_then), "n_constituents_now": counts.get(k_now),
                        "method": rr.method, "window_months": rr.window, "n_names": rr.n_names,
                        "names": [{"ticker": n.ticker, "then": n.then, "now": n.now, "ratio": n.ratio} for n in rr.names],
                        "priced_as_of": priced.isoformat() if priced else None,
                        "below_invested_cost": below_cost, "invested": round(w.invested, 6)},
           w.proposed_mark, w.proposed_mark,   # chain invariant compares proposed (equity + note leg), not equity alone
           f"Comps calibration (alternative only): {w.pos.sector} comps re-rated ×{raw:.3f} ({raw - 1:+.1%}) from {k_then} to "
           f"{k_now}, as the {how}; {age} months since the round"
           + (f"; {k_now} priced on {priced.isoformat()}, not a month-end" if priced and priced.strftime("%Y-%m") == k_now and priced != _month_end(md) else "")
           + (f" — CAPPED at {factor - 1:+.0%} by the policy limit of ±{c.bound_pct:.0%} (uncapped it would be ${usd2(w.equity_mark * raw)}M)" if bounded else "")
           + f". Calibrated alternative ${usd2(alt)}M recorded; base mark unchanged"
           + (f"; it sits below invested cost of ${usd2(w.invested)}M" if below_cost else "") + ".",
           formula=(rr.formula() if same_set else f"{hist.get(k_now, 0):.2f}× ÷ {hist.get(k_then, 0):.2f}× = {raw:.3f}")
                   + (f" → cap: policy limit ±{c.bound_pct:.0%}, so {raw:.3f} becomes {factor:.4f} (uncapped ${usd2(w.equity_mark)}M × {raw:.3f} = ${usd2(w.equity_mark * raw)}M)" if bounded else " (within the ±{:.0%} policy limit, no cap)".format(c.bound_pct))
                   + f" · ${usd2(w.equity_mark)}M × {factor:.4f} = ${usd2(alt)}M as an alternative; base mark unchanged")


def usd2(x: float) -> str:
    """$M to the cent, rounded half-up like the labels and the review tool (a binary float's `.2f`
    rounds 32.535 to 32.53 while the card beside it says 32.54)."""
    return f"{Decimal(repr(float(x))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _month_end(d: date) -> date:
    import calendar
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _nearest_month(hist: dict[str, float], key: str, tolerance: int) -> str | None:
    """`key` itself when present, else the closest month within ±tolerance that has a value
    (the earlier month preferred on a tie: the round was priced on the way in)."""
    if key in hist:
        return key
    y, m = int(key[:4]), int(key[5:7])
    idx = y * 12 + (m - 1)
    for d in range(1, tolerance + 1):
        for cand in (idx - d, idx + d):
            k = f"{cand // 12:04d}-{cand % 12 + 1:02d}"
            if k in hist and hist[k]:
                return k
    return None
