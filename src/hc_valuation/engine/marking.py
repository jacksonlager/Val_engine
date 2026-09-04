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

from ..config import RuleConfig
from .inputs import Event, EventType, Position, Status
from .models import MarketData, OpenItem, OpenItemKind, Severity
from .registry import rule
from .state import Suggest, Working

EFFECTIVE = date(2026, 7, 1)   # policy 2026Q3 in force from the start of the quarter
V = "2026Q3.1"


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


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
_STOCK_TERMS = ("all-stock", "stock-for-stock", "equity consideration", "stock", "shares")

_FUND_RE = re.compile(r"\bFund\s+(III|II|I)\b", flags=re.I)
_STAGE_RE = re.compile(r"\b(Pre-Seed|Seed|Series\s+[A-H](?:\+)?)\b", flags=re.I)


def _text(e: Event) -> str:
    return f"{e.detail} {e.notes}".lower()


def _related_party_flags(w: Working, e: Event, rid: str) -> None:
    """X-117 (REVIEW) when HC led the round: a related-party price is not arm's-length.
    X-118 (MONITOR) when the round was insider-led but not by HC."""
    text = _text(e)
    hc_led = any(t in text for t in _HC_LED_TERMS)
    insider = any(t in text for t in _INSIDER_TERMS)
    if hc_led:
        w.flag("X-117", "treatment", Severity.REVIEW,
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
        w.flag("X-118", "treatment", Severity.MONITOR,
               f"The notes say the round was insider-led ({rid}). Existing investors re-pricing their own position is weaker "
               "evidence than a new lead, though not a related-party price for HC itself.",
               rule=rid, insider_led=True)


def _stage_from_detail(detail: str) -> str | None:
    m = _STAGE_RE.search(detail or "")
    return re.sub(r"\s+", " ", m.group(1)).title() if m else None


def _dilution_check(w: Working, e: Event, cfg: RuleConfig, before: float, after: float) -> None:
    """X-103 — HC did not participate and ownership fell materially. MONITOR: a portfolio
    signal, not a valuation one; the mark comes from a fresh arm's-length round."""
    if before <= 0 or after is None:
        return
    rel = after / before - 1
    funded = bool(e.hc_investment)
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
    w.step("M-000", V, {"prior_mark": w.pos.prior_mark, "ownership": w.ownership, "latest_post_money": w.latest_post},
           w.equity_mark, w.equity_mark,
           f"{reason}; the most recent priced round remains the best evidence of value.")


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
    is_recap = "recap" in detail
    is_down = post < prior_post - 1e-9
    is_flat = (not is_down) and (abs(post - prior_post) < 1e-9 or "extension" in detail or "same terms" in detail)
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
        w.step(rid, V, common, prior, new_equity,
               f"{'Recap' if is_recap else 'Down round'} at ${post:.1f}M post vs ${prior_post:.1f}M prior. Priced mechanically at "
               f"{after:.1%} × ${post:.1f}M; treated as an UPPER BOUND on junior-equity value because the "
               "headline post-money ignores preference and pay-to-play structure the schema cannot see." + conv_txt, e)
        w.flag("X-102", "treatment", Severity.BLOCK,
               f"{'Recap' if is_recap else 'Down round'}: the round priced at ${post:.1f}M against ${prior_post:.1f}M last time. "
               "Ownership × post-money ignores liquidation preference and pay-to-play, which rounds like this almost always "
               "carry, so this figure is a ceiling on what the common equity is worth rather than an estimate of it. "
               "The terms are in the round documents, not the workbook.",
               points=(f"{'Recap' if is_recap else 'Down round'}: priced at **${post:.1f}M** against ${prior_post:.1f}M last round.",
                       "Ownership × post-money **ignores liquidation preference** and pay-to-play.",
                       "So the mark is a **ceiling**, not an estimate — the terms sit in the round documents."),
               suggestions=(
                   Suggest("as_proposed", f"Book the {'recap' if is_recap else 'down-round'} figure as proposed.", ("It is the only priced transaction and reflects the new capital structure.", "The preference stack can only lower it — a ceiling beats a stale higher mark."), "proposed"),
                   Suggest("hold_prior", "Hold the prior mark until the round documents are read.", ("Defers the write-down until the preference terms are known.", "Overstates if the round closed as priced — only if documents arrive before the close."), "prior"),
               ),
               action="Read the round documents and confirm the preference stack before booking this mark.",
               prior_post_money=prior_post, post_money=post, insider_led=("insider" in e.notes.lower()))
        w.staleness_anchor = e.date
    elif is_flat:
        rid = "M-011"
        w.step(rid, V, common, prior, new_equity,
               f"Same-terms extension at ${post:.1f}M post. Ownership {before:.1%} → {after:.1%} reprices the position "
               "mechanically, but no new price discovery occurred: the staleness clock is NOT reset "
               f"(still runs from {w.staleness_anchor.isoformat()})." + conv_txt, e)
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
        w.step(rid, V, common, prior, new_equity,
               f"Priced round at ${post:.1f}M post ({e.detail}). Mark = {after:.1%} × ${post:.1f}M. "
               "An arm's-length transaction in the subject security is the strongest Level 3 input available." + conv_txt, e)
        w.staleness_anchor = e.date

    _dilution_check(w, e, cfg, before, after)
    _related_party_flags(w, e, rid)
    w.equity_mark = new_equity
    w.note_at_cost = 0.0   # converted; cost basis already in `invested`
    w.open_items = [i for i in w.open_items if i.kind != OpenItemKind.CONVERTIBLE_NOTE]   # a note converts at the round
    w.ownership = after
    w.invested += inv
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
    if not e.proceeds and any(t in _text(e) for t in _STOCK_TERMS):
        return stock_exit(w, e, cfg, market)
    proceeds = float(e.proceeds or 0.0)
    implied = w.ownership * float(e.value) if e.value else None
    w.step("M-020", V, {"deal_value": e.value, "proceeds": proceeds, "ownership": w.ownership,
                        "implied_from_deal_value": implied, "detail": e.detail},
           w.proposed_mark, 0.0,
           f"Acquisition closed at ${float(e.value or 0):.1f}M; ${proceeds:.1f}M received against a ${w.equity_mark:.1f}M carrying value. "
           "Position realized; mark to zero.", e)
    if e.proceeds is None:
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
    elif implied is not None and abs(implied - proceeds) > cfg.tolerances.prior_mark_reconciliation_musd * 10:
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
    w.realized_quarter += proceeds
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
           "is not realized — it has changed from one company's stock into another's.", e)
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
    w.step("M-021", V, {"proceeds": proceeds, "prior_mark": w.equity_mark, "detail": e.detail},
           w.proposed_mark, 0.0,
           f"Company ceased operations. ${w.equity_mark:.1f}M written off"
           + (f"; ${proceeds:.1f}M residual cash distributed." if proceeds else "; no recovery expected."), e)
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
    implied_post = proceeds / sold if sold > 1e-12 else None
    basis = cfg.marking.secondary.remainder_basis
    at_last_round = after * w.latest_post
    at_secondary = after * implied_post if implied_post else None
    new_equity = at_secondary if (basis == "secondary_price" and at_secondary is not None) else at_last_round
    spread = (implied_post / w.latest_post - 1) if (implied_post and w.latest_post) else None

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
    w.step("M-030", V, {"ownership_before": before, "ownership_after": after, "ownership_sold": round(sold, 6),
                        "proceeds": proceeds, "implied_post_money": implied_post, "last_round_post_money": w.latest_post,
                        "remainder_basis": basis, "at_last_round": at_last_round, "at_secondary_price": at_secondary},
           w.proposed_mark, new_equity + w.note_at_cost,
           f"Sold {sold/before:.0%} of the position for ${proceeds:.1f}M (implies ${implied_post:.1f}M post vs ${w.latest_post:.1f}M last round"
           + (f", {spread:+.1%})" if spread is not None else ")")
           + f". Remainder {after:.1%} marked on basis '{basis}'.", e)
    if at_secondary is not None:
        w.alternative_marks["at_secondary_price" if basis == "last_round" else "at_last_round"] = (
            at_secondary if basis == "last_round" else at_last_round)
    if spread is not None and abs(spread) > cfg.exceptions.secondary.spread_tolerance_pct:
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
    disc = cfg.marking.ipo.lockup_discount_pct
    new_equity = after * cap * (1 - disc)
    lockup_end = e.date + timedelta(days=cfg.open_items.ipo_lockup_days)
    note_converted = w.note_at_cost
    w.step("M-040", V, {"ipo_market_cap": e.value, "measurement_date_market_cap": cap, "price_source": source,
                        "ownership_before": w.ownership, "ownership_after": after, "lockup_discount_pct": disc,
                        "lockup_end": lockup_end, **({"note_converted": note_converted} if note_converted else {})},
           w.proposed_mark, new_equity,
           f"Listed ({e.detail}). Mark = {after:.1%} × ${cap:,.0f}M market cap at measurement date (source: {source})"
           + (f" less {disc:.0%} lock-up discount" if disc else " with no lock-up discount (ASC 820 disfavors blockage factors for Level 1)")
           + ". Fair value hierarchy: Level 3 → Level 1."
           + (f" HC's ${note_converted:.2f}M note leg converts on listing and is folded into the equity mark." if note_converted else ""), e)
    w.flag("X-101", "treatment", Severity.BLOCK,
           f"The position is now listed, so the mark comes from a market capitalisation rather than a funding round, and it should "
           f"be the closing price on {cfg.quarter.measurement_date.isoformat()} — not the ${float(e.value):,.0f}M the shares priced at "
           f"on listing day. HC also cannot sell until {lockup_end.isoformat()}. ASC 820 disfavors blockage discounts for a Level 1 "
           f"holding, so policy applies {disc:.0%}, but that is a committee call rather than an arithmetic one.",
           points=(f"Now **listed**: the mark is the **{cfg.quarter.measurement_date.isoformat()} close**, not the ${float(e.value):,.0f}M listing-day price.",
                   f"HC **cannot sell until {lockup_end.isoformat()}**.",
                   f"Policy applies a **{disc:.0%}** lock-up discount (ASC 820 disfavors blockage on Level 1) — a committee call, not arithmetic."),
           suggestions=(
               Suggest("as_proposed", f"Book the {cfg.quarter.measurement_date.strftime('%d %b')} close with the {disc:.0%} lock-up discount, as proposed.", ("Level 1: the quoted price is fair value under ASC 820.", "Blockage discounts on quoted prices are disfavored."), "proposed"),
               Suggest("at_ipo_print", "Book at the IPO print instead of the close.", ("Avoids marking to post-listing swings HC cannot trade during the lock-up.", "Conservative if the shares have run up since listing; the reverse if they fell."), "alternative", value="at_ipo_print"),
           ),
           action=f"Confirm the {cfg.quarter.measurement_date.strftime('%d %b')} closing price, then ratify or change the "
                  f"{disc:.0%} lock-up discount.",
           price_source=source, price_source_note=w.market_note, lockup_end=lockup_end,
           ipo_print_mark=round(after * float(e.value), 6))
    w.alternative_marks["at_ipo_print"] = after * float(e.value)
    w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.IPO_LOCKUP, opened=e.date,
                                 opened_quarter=w.quarter_label, expected_resolution=lockup_end,
                                 detail=f"180-day lock-up; {after:.1%} of listed equity"))
    w.equity_mark = new_equity
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

@rule(rule_id="M-050", version=V, applies_to=(EventType.ACQ_ANNOUNCED.value,), severity=Severity.BLOCK,
      effective_from=EFFECTIVE, tier=5,
      description="Announced, unclosed acquisition: probability-weighted deal value by default; always blocks.")
def announced(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    deal = float(e.value)
    p = cfg.marking.announced.close_probability
    treatment = cfg.marking.announced.treatment
    full = w.ownership * deal
    weighted = full * p
    hold = w.equity_mark
    new_equity = {"probability_weighted": weighted, "full_deal_value": full, "hold_prior": hold}[treatment]
    w.step("M-050", V, {"deal_value": deal, "ownership": w.ownership, "treatment": treatment, "close_probability": p,
                        "at_full_deal_value": full, "probability_weighted": weighted, "hold_prior": hold, "detail": e.detail},
           w.proposed_mark, new_equity + w.note_at_cost,
           f"Definitive agreement at ${deal:.0f}M, not closed ({e.notes or 'no closing detail'}). Treatment '{treatment}': "
           f"{w.ownership:.1%} × ${deal:.0f}M" + (f" × {p:.2f}" if treatment == "probability_weighted" else "")
           + f" = ${new_equity:.2f}M. Alternatives: full ${full:.2f}M, hold ${hold:.2f}M.", e)
    w.flag("X-101", "treatment", Severity.BLOCK,
           f"A buyer has signed for ${deal:.0f}M but the deal has not closed and still needs approval. Booking the full deal value "
           "ignores that contingency; holding the old mark ignores a signed agreement. Policy splits the difference at "
           f"{p:.2f}, giving ${weighted:.2f}M against ${full:.2f}M at full value and ${hold:.2f}M if held.",
           points=(f"Buyer signed for **${deal:.0f}M**, but the deal has **not closed** and still needs approval.",
                   f"Policy weights it at **{p:.2f}** → **${weighted:.2f}M**.",
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
           f"${w.equity_mark:.2f}M." + (f" HC's ${inv:.2f}M new money carried at cost as a separate note leg." if inv else " HC did not fund the note."), e)
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


# --------------------------------------------------------------------------- M-070

@rule(rule_id="M-070", version=V, applies_to=(EventType.TERM_SHEET.value,), severity=Severity.MONITOR,
      effective_from=EFFECTIVE, tier=7,
      description="Signed term sheet: non-binding; mark unchanged; disclosed as a pending event.")
def term_sheet(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    indicated = w.ownership * float(e.value) if e.value else None
    w.step("M-070", V, {"indicated_post_money": e.value, "ownership": w.ownership, "indicated_mark": indicated, "detail": e.detail},
           w.proposed_mark, w.proposed_mark,
           f"Term sheet signed ({e.detail}); not closed. No enforceable transaction — mark unchanged"
           + (f"; indicated value ${indicated:.2f}M disclosed, not booked." if indicated else "."), e)
    w.flag("X-109", "treatment", Severity.MONITOR,
           f"A term sheet indicates ~${float(e.value or 0):.1f}M against the ${w.latest_post:.1f}M the mark rests on. It is "
           "non-binding and diligence is open, so nothing is booked from it — this is disclosure only.",
           indicated_post_money=e.value, indicated_mark=indicated)
    if indicated is not None:
        w.alternative_marks["term_sheet_indicated"] = indicated
    w.open_items.append(OpenItem(company=w.pos.company, kind=OpenItemKind.TERM_SHEET, opened=e.date,
                                 opened_quarter=w.quarter_label, amount_musd=e.value, detail=e.notes or e.detail))


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
           + f" The staleness clock still runs from {w.staleness_anchor.isoformat()}.", e)
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
           + (" The company was not in the Portfolio tab; the position was created from this row." if created else ""), e)
    w.flag("X-120", "treatment", Severity.MONITOR,
           f"New position entered at cost: {after:.1%} of a ${post:.1f}M post-money for ${inv:.2f}M. Nothing to decide — "
           "the entry price is the mark.",
           post_money=post, ownership_after=after, hc_investment=inv)
    if created:
        w.flag("X-918", "integrity", Severity.REVIEW,
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
           f"Cash distribution of ${proceeds:.2f}M ({e.detail}); the stake is unchanged, so the mark is unchanged and the cash "
           "goes to realized proceeds."
           + (f" The position was already {w.status.value}; this is money arriving after the exit." if w.terminal else ""), e)
    w.flag("X-111", "treatment", Severity.MONITOR,
           f"Cash distribution of ${proceeds:.2f}M received; stake unchanged. Nothing to decide — realized proceeds rise, "
           "the mark does not move.",
           proceeds=proceeds)
    w.realized_quarter += proceeds


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
    spread = (implied_post / w.latest_post - 1) if (implied_post and w.latest_post) else None

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
           f"Bought {bought:.1%} more of the company for ${inv:.2f}M"
           + (f" (implies ${implied_post:.1f}M post vs ${w.latest_post:.1f}M last round" + (f", {spread:+.1%})" if spread is not None else ")")
              if implied_post else "")
           + f". Whole stake {after:.1%} marked at the last-round price: one buyer taking one block is evidence, not the principal market.", e)
    if at_implied is not None:
        w.alternative_marks["at_implied_price"] = at_implied
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


def listed_carry(w: Working, cfg: RuleConfig, market: MarketData) -> None:
    """A listed position has a daily price; carrying last quarter's number forward is a stale mark,
    not a carry. With a quote: ownership × market cap, Level 1. Without: M-000 and X-113 BLOCK."""
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
           f"Listed position, no event. Mark = {w.ownership:.1%} × ${cap:,.0f}M market cap at {md.isoformat()} (source: {quote.source})"
           + (f" vs ${w.latest_post:,.0f}M at the prior close" if w.latest_post else "") + ". Level 1.")
    w.equity_mark = new_equity
    w.latest_post = cap
    w.staleness_anchor = md
    w.fv_level = 1


# --------------------------------------------------------------------------- M-051

@rule(rule_id="M-051", version=V, applies_to=(EventType.ACQ_TERMINATED.value,), severity=Severity.REVIEW,
      effective_from=EFFECTIVE, tier=5,
      description="Announced deal terminated: mark reverts to the last-round basis; the pending_acquisition item is dropped.")
def deal_terminated(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    new_equity = w.ownership * w.latest_post
    w.step("M-051", V, {"ownership": w.ownership, "last_round_post_money": w.latest_post, "prior_mark": w.equity_mark,
                        "detail": e.detail},
           w.proposed_mark, new_equity + w.note_at_cost,
           f"Announced acquisition terminated ({e.detail}). The deal-based mark no longer has a deal behind it: reverted to "
           f"{w.ownership:.1%} × ${w.latest_post:.1f}M last-round post = ${new_equity:.2f}M. Staleness clock unchanged "
           f"(runs from {w.staleness_anchor.isoformat()}).", e)
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
           reverted_to=round(new_equity, 6), from_mark=round(w.equity_mark, 6), last_round_post_money=w.latest_post)
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
    w.realized_quarter += proceeds
    w.note_at_cost = note_after
    w.open_items = [i for i in w.open_items if i.kind != OpenItemKind.CONVERTIBLE_NOTE]   # repaid, not outstanding


# --------------------------------------------------------------------------- M-999
UNKNOWN_RULE_ID = "M-999"


@rule(rule_id="M-999", version=V, applies_to=("*",), severity=Severity.BLOCK, effective_from=EFFECTIVE, tier=0,
      description="Unrecognised event type: mark unchanged, position blocked, never a silent carry.")
def unrecognised(w: Working, e: Event, cfg: RuleConfig, market: MarketData) -> None:
    w.step("M-999", V, {"event_type": e.event_type, "detail": e.detail, "value": e.value},
           w.proposed_mark, w.proposed_mark,
           f"Event type {e.event_type!r} has no registered handler. Mark left unchanged and the position is BLOCKED — "
           "an unrecognised event must never look like an uneventful quarter.", e)
    w.flag("M-999", "treatment", Severity.BLOCK,
           f"No rule covers a {e.event_type!r} ({e.detail}). The mark is unchanged and the position is held, because an event the "
           "engine does not understand must never look like a quarter in which nothing happened.",
           points=(f"**No rule covers** a {e.event_type!r} ({e.detail}).",
                   "The mark is **unchanged** and the position is **held**.",
                   "An event the engine does not understand must **never look like a quiet quarter**."),
           suggestions=(
               Suggest("hold_prior", "Hold the prior mark and adjudicate the event.", ("An event the engine does not understand must not book a number.", "The Proposals view offers accept-once or promote-to-rule."), "prior"),
           ),
           action=f"Decide how a {e.event_type!r} should be treated, then accept it once or promote it to a rule.",
           event_type=e.event_type, signature=e.signature)


# --------------------------------------------------------------------------- M-080 (post-roll, config-gated)

@rule(rule_id="M-080", version=V, applies_to=(), severity=None, effective_from=EFFECTIVE, tier=9,
      description="Stale-round comps calibration (config-gated, off by default): writes an alternative mark only.")
def _m080_doc(w, e, cfg, market):  # pragma: no cover - post-roll step applied by run.py via calibrate_stale
    raise NotImplementedError


def calibrate_stale(w: Working, cfg: RuleConfig, market: MarketData) -> None:
    """Writes an *alternative* mark; never touches equity_mark."""
    c = cfg.marking.calibration
    if not c.enabled or w.terminal or w.listed or w.pos.arr is None:
        return
    md = cfg.quarter.measurement_date
    age = months_between(w.staleness_anchor, md)
    if age < c.min_age_months:
        return
    hist = market.comp_history.get(w.pos.sector)
    if not hist:
        return
    k_now = md.strftime("%Y-%m")
    k_then = w.staleness_anchor.strftime("%Y-%m")
    if k_now not in hist or k_then not in hist or not hist[k_then]:
        return
    factor = hist[k_now] / hist[k_then]
    factor = max(1 - c.bound_pct, min(1 + c.bound_pct, factor))
    w.alternative_marks["calibrated_to_comps"] = round(w.equity_mark * factor, 6)
    w.step("M-080", V, {"comp_multiple_now": hist[k_now], "comp_multiple_at_round": hist[k_then], "factor_bounded": round(factor, 4),
                        "age_months": age, "sector": w.pos.sector},
           w.proposed_mark, w.proposed_mark,   # chain invariant compares proposed (equity + note leg), not equity alone
           f"Comps calibration (alternative only): sector {w.pos.sector} multiple moved {factor - 1:+.1%} since the round "
           f"({age} months). Calibrated alternative ${w.equity_mark * factor:.2f}M recorded; base mark unchanged.")
