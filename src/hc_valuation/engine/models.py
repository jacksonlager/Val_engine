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

    arr: float | None = None
    arr_growth: float | None = None
    runway_months_aged: float | None = None
    implied_multiple: float | None = None
    moic_after: float | None = None

    steps: tuple[MarkStep, ...]
    flags: tuple[Flag, ...] = ()
    disposition: Disposition = Disposition.CLEAR
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


class ValuationRun(_Frozen):
    manifest: RunManifest
    companies: tuple[CompanyResult, ...]
    rollups: tuple[FundRollup, ...]
    validation: tuple[ValidationIssue, ...]
    totals: PortfolioTotals
    open_items: tuple[OpenItem, ...] = ()
    sensitivity: dict[str, float] = Field(default_factory=dict)

    def by_company(self) -> dict[str, CompanyResult]:
        return {c.company: c for c in self.companies}

    @property
    def blocked(self) -> bool:
        return any(v.blocking for v in self.validation) or any(
            c.disposition == Disposition.BLOCK for c in self.companies
        )
