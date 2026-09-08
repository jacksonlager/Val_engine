"""Output and auxiliary-input models for the valuation engine.

The audit chain (`MarkStep`) is the primary structure. A company's proposed mark is
*derived* from its chain, never stored independently of it — see the invariant on
`CompanyResult`.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .inputs import Status  # noqa: F401  (re-exported for convenience)


class Severity(str, Enum):
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"
    MONITOR = "MONITOR"


class Disposition(str, Enum):
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"
    MONITOR = "MONITOR"
    CLEAR = "CLEAR"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------- auxiliary inputs

class MarketQuote(_Frozen):
    """A public-market observation at the measurement date."""
    company: str
    market_cap_musd: float
    as_of: date
    source: str
    note: str = ""


class SectorComp(_Frozen):
    sector: str
    ev_to_arr: float
    as_of: date
    source: str


class MarketData(_Frozen):
    """Everything the engine may need from outside the workbook, already fetched."""
    quotes: dict[str, MarketQuote] = Field(default_factory=dict)
    comps: dict[str, SectorComp] = Field(default_factory=dict)
    comp_history: dict[str, dict[str, float]] = Field(default_factory=dict)  # sector -> {YYYY-MM: multiple}
    comp_counts: dict[str, dict[str, int]] = Field(default_factory=dict)     # sector -> {YYYY-MM: constituents priced}
    as_of: date | None = None


class OverrideRecord(_Frozen):
    """E-01: a committee decision that replaces a proposed mark with a booked one."""
    company: str
    quarter: str
    proposed: float
    booked: float
    reason: str
    approver: str
    created_at: date
    rule_ids_addressed: tuple[str, ...] = ()
    source_proposal: str | None = None
    source_suggestion: str | None = None   # "<rule_id>/<suggestion key>" when a suggestion was accepted
    # The input the reviewer supplied when the override fills a gap rather than asserts a number —
    # e.g. the measurement-date closing price the engine had no quote for. Free-shape, keyed by
    # `kind`, so the ledger shows what produced the booked figure, not just the figure.
    evidence: dict[str, Any] | None = None


class OverrideLedger(_Frozen):
    records: tuple[OverrideRecord, ...] = ()

    def for_quarter(self, quarter: str) -> dict[str, OverrideRecord]:
        return {r.company: r for r in self.records if r.quarter == quarter}


class OpenItemKind(str, Enum):
    CONVERTIBLE_NOTE = "convertible_note"
    PENDING_ACQUISITION = "pending_acquisition"
    TERM_SHEET = "term_sheet"
    IPO_LOCKUP = "ipo_lockup"
    ACQUIRER_SHARES = "acquirer_shares"   # M-024: consideration received as shares of the buyer
    UNCONFIRMED_EXIT = "unconfirmed_exit"  # M-020 with no cash recorded: the consideration is still to be confirmed
    DEBT = "debt"                          # M-062: a loan HC made, carried at cost until repaid


class OpenItem(_Frozen):
    """E-07: unfinished business that must survive the quarter boundary."""
    company: str
    kind: OpenItemKind
    opened: date
    opened_quarter: str
    expected_resolution: date | None = None
    amount_musd: float | None = None
    detail: str = ""
    age_quarters: int = 0
    escalated: bool = False


# ---------------------------------------------------------------- audit chain

class EventRef(_Frozen):
    sheet: str
    row_index: int
    event_type: str
    date: date


class MarkStep(_Frozen):
    rule_id: str
    rule_version: str
    sequence: int
    inputs: dict[str, Any]
    prior_value: float
    new_value: float
    rationale: str
    evidence: EventRef | None = None


class Suggestion(_Frozen):
    """One way a reviewer could resolve a flag, with the mark it would book.

    `label` is one sentence in the imperative; `reasons` are two short lines saying why a
    committee might choose it. `booked` is the resulting booked mark in $M — always a real
    number the engine computed (the proposal, the prior mark, an alternative mark, a deal
    figure), never a guess — so accepting a suggestion is a fully specified E-01 override.
    Suggestions never change the proposal; they are the menu, not the decision.
    """
    key: str
    label: str
    reasons: tuple[str, ...]
    booked: float


class Recommendation(_Frozen):
    """The one resolution put forward to the reviewer, chosen from the flag's `suggestions`.

    `key` names the chosen suggestion, so `booked` is always a number the engine computed —
    the chooser (a policy default, or Claude through the recommend module) picks and
    explains; it never prices. `source` says which; `model`, `rationale` and `confidence`
    are filled in when a model made the call. Accepting it records an ordinary E-01
    override, exactly as accepting any suggestion does.
    """
    key: str
    label: str
    reasons: tuple[str, ...]
    booked: float
    source: str                     # "policy" | "claude"
    model: str | None = None
    rationale: str | None = None
    confidence: float | None = None
    note: str | None = None         # why a model was not used, when it was asked for


class PositionRecommendation(_Frozen):
    """The one next step put to the reviewer for the whole position, chosen across every
    finding on it rather than one per flag.

    A position with three findings has three sets of priced resolutions; a reviewer wants one
    thing to do first. `rule_id` names the finding whose resolution leads and `key` the
    suggestion on it, so `booked` is still a number the engine computed — the chooser weighs
    the findings against each other and explains the order; it never prices. `covers` is the
    chooser's read of which findings this step settles: always includes `rule_id`, always a
    subset of the position's actionable findings, and always shown to the reviewer as an
    editable list before anything is recorded. `source` says who chose.
    """
    rule_id: str
    key: str
    label: str
    reasons: tuple[str, ...]
    booked: float
    covers: tuple[str, ...] = ()
    source: str = "policy"          # "policy" | "claude"
    model: str | None = None
    rationale: str | None = None
    confidence: float | None = None
    note: str | None = None         # why a fallback happened, when one did


class Flag(_Frozen):
    """A reason a human should look at a position. Never changes a mark.

    `action` is the imperative: exactly what the reviewer must decide or check. It is
    empty for MONITOR flags by design — a flag with nothing for a person to do is
    information, not a gate, which is the same test that sets its severity.
    `points` is the same reasoning as `message`, cut to two or three scannable lines so a
    reviewer can see why a position stopped without reading a paragraph; `**bold**` marks
    the words that carry the decision. Every BLOCK and REVIEW flag carries them and MONITOR
    never does (state.py enforces both). `message` is the long form, shown on demand.
    `suggestions` are the one or two resolutions the rule can put a number on; a reviewer
    accepting one records an override addressed to this rule id.
    """
    rule_id: str
    family: str
    severity: Severity
    message: str
    action: str = ""
    points: tuple[str, ...] = ()
    suggestions: tuple[Suggestion, ...] = ()
    recommendation: Recommendation | None = None   # set by the recommend module, outside the engine
    evidence: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(_Frozen):
    rule_id: str
    severity: Severity
    message: str
    sheet: str | None = None
    row_index: int | None = None
    company: str | None = None
    blocking: bool = True


# ---------------------------------------------------------------- results

class Readiness(str, Enum):
    """Can this position be booked, and if not, why not — three states, one per position.

    Distinct from `Disposition`, which counts *findings*. A position with four flags has one
    readiness. The line between the two unready states is whether the engine had what it needed:
    BLOCKED means a required input is missing or contradictory, so no supported final mark
    exists at any price; NEEDS_REVIEW means the inputs are there and the treatment is a judgment
    a reviewer must make or confirm."""
    BLOCKED = "Blocked"
    NEEDS_REVIEW = "Needs Review"
    READY = "Ready"


class ValuationAction(str, Enum):
    """What happened to the position this quarter — the accounting shape of the move, which is
    a different question from whether anyone has reviewed it."""
    CARRY = "Carry"
    REVALUE = "Revalue"
    NEW_INVESTMENT = "New investment"
    PARTIAL_EXIT = "Partial exit"
    FULL_EXIT = "Full exit"
    WRITE_OFF = "Write-off"


class Approval(str, Enum):
    """Whether a person has actually signed the number. A proposal is never "booked" until the
    quarter is published, and a mark with a decision recorded against it is still only proposed
    until then."""
    NONE = "Not approved"
    DECIDED = "Decision recorded"
    PUBLISHED = "Approved and published"


class CompanyResult(_Frozen):
    company: str
    fund: str
    sector: str
    stage: str
    status_before: Status
    status_after: Status
    listed: bool = False

    prior_mark: float
    equity_mark: float
    note_at_cost: float = 0.0
    proposed_mark: float          # equity_mark + note_at_cost; engine output, never modified
    booked_mark: float            # after override, if any
    override: OverrideRecord | None = None

    ownership_before: float
    ownership_after: float
    invested_before: float
    invested_after: float
    realized_quarter: float = 0.0
    realized_cumulative: float = 0.0
    latest_post_money: float
    staleness_anchor: date        # date the staleness clock runs from
    fv_level: int | None = None   # 1 | 2 | 3 | None for zero positions
    multiple_exposed: bool = False  # Level 3 with ARR at or above the screening floor: the marks a multiple regime drives

    arr: float | None = None
    arr_growth: float | None = None
    runway_months_aged: float | None = None
    implied_multiple: float | None = None
    moic_after: float | None = None

    # The quarter's movement, split so capital activity never reads as performance:
    #     closing = prior + new investment + valuation gain/loss - realized proceeds
    new_investment_quarter: float = 0.0     # cash HC put in this quarter (rounds, notes, secondaries bought)
    valuation_change_quarter: float = 0.0   # what is left once capital in and cash out are taken off
    # The one next step for this position, chosen across all its findings (recommend.py, outside
    # the engine). None when nothing is actionable, or when the run was not passed through it.
    recommendation: PositionRecommendation | None = None
    provisional: bool = False               # the mark rests on a stand-in for an input that is not on file
    provisional_reason: str | None = None   # what is missing, in the reviewer's words

    steps: tuple[MarkStep, ...]
    flags: tuple[Flag, ...] = ()
    disposition: Disposition = Disposition.CLEAR
    readiness: Readiness = Readiness.READY
    action: ValuationAction = ValuationAction.CARRY
    approval: Approval = Approval.NONE
    monitor: bool = False                   # a watch item rides alongside any readiness, including Ready
    open_items: tuple[OpenItem, ...] = ()
    alternative_marks: dict[str, float] = Field(default_factory=dict)  # e.g. calibrated, secondary_price

    @property
    def delta(self) -> float:
        return self.proposed_mark - self.prior_mark

    @model_validator(mode="after")
    def _chain_invariant(self) -> "CompanyResult":
        if not self.steps:
            raise ValueError(f"{self.company}: every company must carry at least one MarkStep")
        last = self.steps[-1].new_value
        if abs(last - self.proposed_mark) > 1e-9:
            raise ValueError(
                f"{self.company}: proposed_mark {self.proposed_mark} != last step new_value {last}; "
                "the audit chain and the mark have diverged"
            )
        return self


class FundRollup(_Frozen):
    fund: str
    companies: int
    active: int
    invested: float
    prior_nav: float
    proposed_nav: float
    booked_nav: float
    realized_quarter: float
    realized_cumulative: float
    tvpi: float
    dpi: float
    rvpi: float
    top_positions: tuple[tuple[str, float], ...] = ()   # (company, share of booked nav)


class PortfolioTotals(_Frozen):
    positions: int
    active_after: int
    prior_nav: float
    proposed_nav: float
    booked_nav: float
    net_movement: float
    realized_quarter: float
    realized_cumulative: float
    written_off: float            # prior marks of positions that shut down (little or no recovery)
    exited_at_prior_mark: float   # prior marks of positions that were sold; realized cash is separate
    dispositions: dict[str, int]
    level1_positions: int
    top10_concentration: float
    # Defaulted so a snapshot published before these existed still loads: the archive has to keep
    # opening, and an older quarter simply has no readiness breakdown to show.
    new_investment: float = 0.0   # cash HC put into the book this quarter
    valuation_change: float = 0.0 # closing - opening - new investment + realized: performance, not capital activity
    readiness: dict[str, int] = Field(default_factory=dict)   # companies per bucket; `dispositions` counts findings
    monitor_positions: int = 0    # companies carrying a watch item, whatever their readiness


class RunManifest(_Frozen):
    run_id: str
    input_sha256: str
    input_file: str
    policy_version: str
    engine_version: str
    quarter_label: str
    measurement_date: date
    prior_close: date
    generated_at: datetime
    adjudication_enabled: bool
    market_data_source: str
    recommender: str = "policy"     # "policy" | "claude:<model>" — who chose each flag's recommendation
    note_reader: str = "off"        # "off: <reason>" | "claude:<model>" — who read the free text on each row
    note_reader_report: dict[str, Any] = Field(default_factory=dict)   # notes/schema.py ReadingReport, for the footer


class SectorSensitivity(_Frozen):
    """One sector's exposure to a change in revenue multiples, so a reviewer can shock a sector on
    its own rather than the whole book at one rate. `exposed_nav` is the part of the sector's NAV a
    multiple regime drives (the same definition the portfolio shock uses); the rest of the sector's
    NAV does not move with multiples at all, which is exactly what a per-sector view is for."""
    sector: str
    positions: int                 # positions in the sector, whatever their exposure
    exposed_positions: int         # ... of which a multiple regime drives
    nav: float                     # booked marks, the whole sector
    exposed_nav: float             # the part a multiple regime drives
    software: bool                 # in the policy's software list, so it moves with the software shock


class SectorMove(_Frozen):
    """One sector's public-comps move over the quarter, applied to the marks it would drive."""
    sector: str
    multiple_prior: float          # basket EV/revenue three months before the measurement month
    multiple_now: float            # ... in the measurement month
    qoq_pct: float                 # now / prior − 1
    exposed_nav: float             # Level 3 booked marks with ARR above the floor, this sector
    delta: float                   # exposed_nav × qoq_pct
    positions: int
    live: bool                     # an observed history (live:*) or the vendor-shaped fixture
    source: str
    n_prior: int | None = None     # constituents behind each basket value (live only)
    n_now: int | None = None


class CompsMove(_Frozen):
    """What the book would look like had every multiple-exposed mark moved with its sector's
    public comps this quarter — the observed counterpart of the ±20% shock. Alternative
    arithmetic only, like M-080: nothing here touches a proposed or booked mark."""
    prior_month: str
    now_month: str
    base_nav: float
    exposed_nav: float             # the part of NAV a multiple regime drives (same definition as `sensitivity`)
    covered_nav: float             # ... in sectors whose comps have both months
    delta: float
    nav_if_marked_with_comps: float
    sectors: tuple[SectorMove, ...]
    all_live: bool                 # every covered sector read an observed history


class ValuationRun(_Frozen):
    manifest: RunManifest
    companies: tuple[CompanyResult, ...]
    rollups: tuple[FundRollup, ...]
    validation: tuple[ValidationIssue, ...]
    totals: PortfolioTotals
    open_items: tuple[OpenItem, ...] = ()
    sensitivity: dict[str, float] = Field(default_factory=dict)
    # what the sensitivity was computed with: shock_pct (list), min_arr (the exposure floor), software_sectors (list)
    sensitivity_meta: dict[str, Any] = Field(default_factory=dict)
    # the same exposure, split by sector, so each can be shocked at its own rate
    sensitivity_sectors: tuple[SectorSensitivity, ...] = ()
    comps_move: CompsMove | None = None

    def by_company(self) -> dict[str, CompanyResult]:
        return {c.company: c for c in self.companies}

    @property
    def blocked(self) -> bool:
        return any(v.blocking for v in self.validation) or any(
            c.disposition == Disposition.BLOCK for c in self.companies
        )
