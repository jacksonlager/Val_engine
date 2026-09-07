"""The case catalogue: every kind of thing an activity row's free text can say that the columns
do not carry, and what the engine does about each.

Two consumers read it. The note reader (`notes/reader.py`) hands the list, with definitions, to
the model as the only vocabulary it may answer in; the engine (`engine/notes.py`) uses the
`terms` and `events` of each kind to tell an aspect a rule already took account of from one
nobody has. A kind outside this list does not exist to the model — it answers `other`, with a
sentence, and `other` always reaches a person.

The catalogue is deliberately wide. The costly error is a note that says something material
which nobody is told about; a reviewer dismissing an aspect that turned out to be routine
costs seconds. So the definitions lean towards "when in doubt, it is this kind".
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..engine.inputs import EventType


class AspectKind(str, Enum):
    # financing terms
    NOTE_CONVERSION = "note_conversion"
    BRIDGE_FINANCING = "bridge_financing"
    NON_BINDING = "non_binding"
    WITHDRAWN_OR_TERMINATED = "withdrawn_or_terminated"
    DOWN_ROUND_OR_RECAP = "down_round_or_recap"
    LIQUIDATION_PREFERENCE = "liquidation_preference"
    ANTI_DILUTION_OR_RATCHET = "anti_dilution_or_ratchet"
    OWNERSHIP_RESTATED = "ownership_restated"
    SHARE_STRUCTURE = "share_structure"
    DEBT = "debt"
    INITIAL_INVESTMENT = "initial_investment"
    # exit terms
    ESCROW_OR_HOLDBACK = "escrow_or_holdback"
    EARN_OUT_OR_CONTINGENT = "earn_out_or_contingent"
    STOCK_CONSIDERATION = "stock_consideration"
    FEES_OR_EXPENSES = "fees_or_expenses"
    PARTIAL_EXIT = "partial_exit"
    LOCK_UP = "lock_up"
    TIMING_OR_DATE = "timing_or_date"
    # the company's situation
    METRICS_IN_PROSE = "metrics_in_prose"
    SUPERSEDES_PRIOR_DATA = "supersedes_prior_data"
    DISTRESS_OR_GOING_CONCERN = "distress_or_going_concern"
    LITIGATION_OR_DISPUTE = "litigation_or_dispute"
    MANAGEMENT_CHANGE = "management_change"
    RELATED_PARTY = "related_party"
    # about the valuation itself
    VALUATION_ASSERTION = "valuation_assertion"
    INSTRUCTION_TO_VALUER = "instruction_to_valuer"
    CURRENCY_OR_UNITS = "currency_or_units"
    OTHER = "other"


@dataclass(frozen=True)
class AspectSpec:
    kind: AspectKind
    label: str                      # what the reviewer reads
    definition: str                 # what the model is told it means
    terms: tuple[str, ...]          # note-screen vocabulary the same aspect maps to (X-105, `Working.handled`)
    events: tuple[str, ...] = ()    # event types for which this aspect is the row's own nature, handled by its rule
    handled_by: str = ""            # for the catalogue document: which rule takes account of it, when


_E = EventType
ASPECTS: tuple[AspectSpec, ...] = (
    AspectSpec(AspectKind.NOTE_CONVERSION, "Note conversion",
               "A convertible note or SAFE converting into equity: the cap or discount applied, accrued interest, shares issued, "
               "the note position being removed.",
               ("conversion", "convert", "converts", "converted", "accrued"),
               (_E.CONVERTIBLE_NOTE.value, _E.NOTE_REPAID.value),
               "M-010 / M-040 when a note leg converts (X-124); M-060 for the note itself"),
    AspectSpec(AspectKind.BRIDGE_FINANCING, "Bridge financing",
               "A bridge note, convertible note or SAFE being raised (not converting): principal, cap, discount, interest, who funded it.",
               ("bridge", "note", "safe", "cap"),
               (_E.CONVERTIBLE_NOTE.value,),
               "M-060 (X-107 / X-108)"),
    AspectSpec(AspectKind.NON_BINDING, "Non-binding indication",
               "A term sheet, letter of intent, indicative offer or proposal that is signed or received but has not closed and binds nobody.",
               ("non-binding", "nonbinding", "loi", "letter of intent", "indicative", "proposal"),
               (_E.TERM_SHEET.value, _E.ACQ_ANNOUNCED.value),
               "M-070 (X-109); M-050 holds the prior mark on a non-binding offer"),
    AspectSpec(AspectKind.WITHDRAWN_OR_TERMINATED, "Withdrawn or terminated",
               "A round, term sheet, offer or deal that was withdrawn, cancelled, terminated, rescinded, lapsed or fell through.",
               ("withdrawn", "withdrew", "cancelled", "canceled", "terminated", "rescinded", "lapsed", "fell through"),
               (_E.TERM_SHEET_WITHDRAWN.value, _E.ACQ_TERMINATED.value),
               "M-071 (X-125); M-051"),
    AspectSpec(AspectKind.DOWN_ROUND_OR_RECAP, "Down round or recapitalisation",
               "A round priced below the last one, a recapitalisation, pay-to-play, cram-down or wash-out; prior shares converted or wiped.",
               ("down round", "down-round", "recap", "recapitalization", "recapitalisation", "pay-to-play", "cram", "cram-down", "washout", "wash-out"),
               (),
               "M-010 when the columns show it (X-102), M-012 for a recap; otherwise the reader"),
    AspectSpec(AspectKind.LIQUIDATION_PREFERENCE, "Liquidation preference or waterfall",
               "Liquidation preference, participation, seniority, pari passu or waterfall terms that change what HC's shares receive.",
               ("preference", "participating", "liquidation preference", "waterfall", "seniority", "pari passu", "senior to"),
               (),
               "no rule: always a person"),
    AspectSpec(AspectKind.ANTI_DILUTION_OR_RATCHET, "Anti-dilution, ratchet, warrants or options",
               "Anti-dilution protection, a ratchet, price protection, warrants or options exercised or granted that change HC's stake or price.",
               ("ratchet", "anti-dilution", "antidilution", "warrant", "warrants", "price protection"),
               (_E.OWNERSHIP_ADJUSTMENT.value,),
               "M-013 (X-110) when filed as an ownership adjustment; M-010 raises X-123 when the stake rose without a cheque"),
    AspectSpec(AspectKind.OWNERSHIP_RESTATED, "Ownership restated",
               "The cap table restated or corrected, or a fully diluted stake stated in the text that differs from or qualifies the ownership column.",
               ("restated", "restatement", "cap table", "fully diluted", "true-up"),
               (_E.OWNERSHIP_ADJUSTMENT.value, _E.SHARE_RESTRUCTURE.value),
               "M-013 (X-110); M-015 (X-133)"),
    AspectSpec(AspectKind.SHARE_STRUCTURE, "Share structure change",
               "A split, reverse split, reclassification, conversion of preferred to common or other share class change.",
               ("split", "reclassif", "reclassification", "share class", "converted to common", "common stock"),
               (_E.SHARE_RESTRUCTURE.value,),
               "M-015 (X-133)"),
    AspectSpec(AspectKind.DEBT, "Debt, loans and covenants",
               "Debt, a loan, a credit facility, covenants, a default, a guarantee, a lender's rights; venture debt ahead of the equity.",
               ("debt", "loan", "facility", "covenant", "default", "guarantee", "lender", "mezzanine", "revolver"),
               (_E.DEBT_FACILITY.value, _E.NOTE_REPAID.value),
               "M-062 (X-127)"),
    AspectSpec(AspectKind.INITIAL_INVESTMENT, "Initial investment",
               "HC's first investment in a company, or a company being added to the portfolio.",
               ("initial investment", "first investment", "first check", "first cheque", "new portfolio company"),
               (_E.NEW_INVESTMENT.value,),
               "M-014 (X-918 / X-120)"),
    AspectSpec(AspectKind.ESCROW_OR_HOLDBACK, "Escrow, holdback or deferred consideration",
               "Part of the exit consideration held back: escrow, holdback, indemnity reserve, deferred or delayed payment, subject to claims.",
               ("escrow", "holdback", "indemnification", "indemnity", "indemnities", "deferred", "delayed payment"),
               (_E.DISTRIBUTION.value,),
               "M-020 when proceeds fall short of the implied entitlement (X-101 gap, exit-consideration item); M-022 for the release"),
    AspectSpec(AspectKind.EARN_OUT_OR_CONTINGENT, "Earn-out or contingent consideration",
               "Consideration that depends on milestones, revenue targets or other conditions after closing.",
               ("earn-out", "earnout", "earn out", "milestone", "contingent"),
               (_E.DISTRIBUTION.value,),
               "M-020 gap (X-101); M-022 for the payment"),
    AspectSpec(AspectKind.STOCK_CONSIDERATION, "Consideration in shares",
               "Consideration paid in shares of the buyer or another company, rollover equity, a stock-for-stock merger.",
               ("stock consideration", "shares of the acquirer", "acquirer shares", "rollover", "stock-for-stock", "share exchange", "all-stock"),
               (),
               "M-024 when the columns show it (acquirer-shares item); otherwise the reader"),
    AspectSpec(AspectKind.FEES_OR_EXPENSES, "Fees, expenses or taxes",
               "Transaction fees, expenses, taxes or other amounts netted from proceeds or from the value.",
               ("fees", "expenses", "net of", "transaction costs", "withholding"),
               (),
               "M-020 gap (X-101); otherwise the reader"),
    AspectSpec(AspectKind.PARTIAL_EXIT, "Partial sale or purchase",
               "Only part of the position sold or bought; shares retained; a tender offer HC took part in.",
               ("partial", "retained", "remaining shares", "tender", "secondary"),
               (_E.SECONDARY.value, _E.SECONDARY_PURCHASE.value),
               "M-030 / M-031 (X-104)"),
    AspectSpec(AspectKind.LOCK_UP, "Lock-up or transfer restriction",
               "A lock-up, transfer restriction or trading window on shares HC holds.",
               ("lock-up", "lockup", "lock up", "transfer restriction", "restricted"),
               (_E.IPO.value, _E.DIRECT_LISTING.value, _E.LOCKUP_EXPIRY.value),
               "M-040 (lock-up item); M-042"),
    AspectSpec(AspectKind.TIMING_OR_DATE, "Timing differs from the row",
               "A signing, closing or effective date in the text that differs from the row's date; something that closed earlier or later "
               "than expected; an event that straddles the quarter end.",
               ("closed earlier", "closed later", "expected to close", "effective", "closing date", "signed on", "after quarter end", "post quarter"),
               (),
               "no rule: always a person"),
    AspectSpec(AspectKind.METRICS_IN_PROSE, "Operating figures in the text",
               "Cash, burn, runway, revenue, ARR, growth, margin or headcount stated in the text rather than in the Portfolio tab's columns.",
               ("cash", "burn", "runway", "revenue", "arr", "growth", "margin", "headcount"),
               (_E.OPERATING_UPDATE.value, _E.TERM_SHEET_WITHDRAWN.value),
               "M-071 / M-072 (X-126); otherwise the reader raises X-126"),
    AspectSpec(AspectKind.SUPERSEDES_PRIOR_DATA, "Supersedes earlier figures",
               "The text says a figure supersedes, corrects, replaces or updates something on the Portfolio tab or an earlier row.",
               ("supersede", "supersedes", "superseded", "supercedes", "corrects", "replaces", "updates the", "restates"),
               (),
               "the reader (X-126 / X-130)"),
    AspectSpec(AspectKind.DISTRESS_OR_GOING_CONCERN, "Distress or going concern",
               "Going-concern doubt, insolvency risk, missed payroll, layoffs, a wind-down being planned, a covenant breach, a bridge to survive.",
               ("going concern", "insolvency", "insolvent", "distress", "layoffs", "wind down", "wind-down", "ceased", "missed payroll", "breach"),
               (_E.SHUTDOWN.value, _E.BANKRUPTCY_CH11.value),
               "M-021 / M-025 when filed as such; otherwise the reader"),
    AspectSpec(AspectKind.LITIGATION_OR_DISPUTE, "Litigation, dispute or investigation",
               "Litigation, a dispute with a counterparty, a regulatory action or investigation, alleged fraud.",
               ("litigation", "lawsuit", "dispute", "regulator", "regulatory action", "investigation", "fraud", "subpoena", "arbitration"),
               (),
               "no rule: always a person"),
    AspectSpec(AspectKind.MANAGEMENT_CHANGE, "Management change",
               "A CEO, founder or key-person departure, replacement or interim appointment.",
               ("ceo", "founder", "departure", "resigned", "stepped down", "interim", "replaced as"),
               (_E.OPERATING_UPDATE.value,),
               "M-072 (X-126) when filed as an operating update; otherwise the reader"),
    AspectSpec(AspectKind.RELATED_PARTY, "Related party or side terms",
               "Related-party or insider terms, a side letter, an affiliate transaction, a conflict of interest.",
               ("related party", "related-party", "side letter", "insider", "affiliate", "conflict of interest"),
               (),
               "no rule: always a person"),
    AspectSpec(AspectKind.VALUATION_ASSERTION, "Valuation asserted in the text",
               "The text says what the mark, value or treatment should be: a write-down, impairment, hold, 'value at', 'mark to'.",
               ("impairment", "impaired", "write-down", "writedown", "write-off", "written off", "mark to", "should be valued", "fair value of", "carry at"),
               (_E.VALUATION_ADJUSTMENT.value,),
               "M-091 (X-128) when filed as a valuation adjustment; otherwise the reader"),
    AspectSpec(AspectKind.INSTRUCTION_TO_VALUER, "Instruction about the treatment",
               "An explicit instruction about how to treat the row: do not double count, remove a position, record as realised, assess separately.",
               (),
               (),
               "the reader lists the instructions on the finding"),
    AspectSpec(AspectKind.CURRENCY_OR_UNITS, "Currency or units",
               "An amount in a currency other than US dollars, or in units other than millions.",
               ("eur", "€", "gbp", "£", "chf", "jpy", "thousand", "billion"),
               (),
               "X-920 for a currency cell; the reader for prose"),
    AspectSpec(AspectKind.OTHER, "Something else",
               "Anything material that fits none of the kinds above. Say what it is in the note.",
               (),
               (),
               "always a person"),
)

BY_KIND: dict[AspectKind, AspectSpec] = {a.kind: a for a in ASPECTS}


def kinds_for_terms(terms: set[str]) -> set[AspectKind]:
    """The kinds whose vocabulary overlaps a set of screen terms (X-105 hits, `Working.handled`)."""
    norm = {t.lower().replace("-", "").replace(" ", "") for t in terms}
    out: set[AspectKind] = set()
    for a in ASPECTS:
        for t in a.terms:
            nt = t.lower().replace("-", "").replace(" ", "")
            if any(nt == x or nt.startswith(x) or x.startswith(nt) for x in norm if len(x) >= 3 and len(nt) >= 3):
                out.add(a.kind)
                break
    return out


def vocabulary_for_prompt() -> str:
    return "\n".join(f'- "{a.kind.value}": {a.definition}' for a in ASPECTS)


# The activity tab's structured columns, as the reader may name them in a conflict.
COLUMNS: dict[str, str] = {
    "date": "Date",
    "event": "Event",
    "post_money_or_deal_value": "Post-Money / Deal Value ($M)",
    "hc_investment": "HC Investment ($M)",
    "ownership_after": "HC Ownership After (FD %)",
    "proceeds": "Proceeds to HC ($M)",
}

# Portfolio-tab fields the text can supersede.
TAB_FIELDS: tuple[str, ...] = ("cash", "net_burn", "arr", "arr_growth", "gross_margin", "headcount", "ownership", "status",
                               "latest_post_money", "invested", "other")
