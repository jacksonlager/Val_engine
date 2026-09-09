"""Policy configuration: rules/<quarter>.yaml -> RuleConfig.

Every threshold the engine uses is declared here and validated strictly. An unknown
key is an error, not a warning — a typo in a threshold name must not silently
become "the default".
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QuarterCfg(_Strict):
    label: str
    measurement_date: date
    prior_close: date
    window_start: date
    window_end: date


class MetricsCfg(_Strict):
    reporting_lag_months: int = 0

    @model_validator(mode="after")
    def _sane(self) -> "MetricsCfg":
        if self.reporting_lag_months < 0:
            raise ValueError("metrics.reporting_lag_months cannot be negative")
        return self


class HistoryCfg(_Strict):
    """What the per-company archive is allowed to show for quarters the engine did not run.

    The archive grows from the publish ledger: every released quarter contributes the flags it
    actually carried. Before the first release there is nothing, and the honest answer is "not
    on record" — so `reconstruct_prior_flags` is off. Turned on, `prior_screen.py` re-screens
    the prior-close book under the current policy and the points are labelled `reconstructed`,
    which is a defensible bridge but is not what any committee saw.
    """
    reconstruct_prior_flags: bool = False


class SecondaryCfg(_Strict):
    remainder_basis: Literal["last_round", "secondary_price"] = "last_round"


class IpoCfg(_Strict):
    price_source: Literal["market_close", "ipo_print"] = "market_close"
    lockup_discount_pct: float = 0.0

    @model_validator(mode="after")
    def _sane(self) -> "IpoCfg":
        if not 0.0 <= self.lockup_discount_pct < 1.0:
            raise ValueError("marking.ipo.lockup_discount_pct must be in [0, 1)")
        return self


class AnnouncedCfg(_Strict):
    treatment: Literal["probability_weighted", "full_deal_value", "hold_prior"] = "probability_weighted"
    close_probability: float = 0.90

    @model_validator(mode="after")
    def _sane(self) -> "AnnouncedCfg":
        if not 0.0 <= self.close_probability <= 1.0:
            raise ValueError("marking.announced.close_probability must be in [0, 1]")
        return self


class ConvertibleCfg(_Strict):
    new_money_basis: Literal["cost"] = "cost"


class CalibrationCfg(_Strict):
    enabled: bool = False
    min_age_months: int = 24
    bound_pct: float = 0.35
    require_live_history: bool = True   # calibrate only from an observed comps history (live:*), never the fixture
    round_month_tolerance: int = 3      # months either side of the round month the history may be read at

    @model_validator(mode="after")
    def _sane(self) -> "CalibrationCfg":
        if self.min_age_months < 0 or self.round_month_tolerance < 0:
            raise ValueError("marking.calibration months cannot be negative")
        if not 0.0 < self.bound_pct <= 1.0:
            raise ValueError("marking.calibration.bound_pct must be in (0, 1]")
        return self


class DownRoundCfg(_Strict):
    """M-012: ownership × post-money on a down round or recap is a ceiling — the preference
    stack and pay-to-play the schema cannot see only lower it. The haircut is a policy
    placeholder for that structure, offered as a priced option beside the ceiling; the round
    documents replace it with a waterfall when they are read."""
    structure_haircut_pct: float = 0.25

    @model_validator(mode="after")
    def _sane(self) -> "DownRoundCfg":
        if not 0.0 <= self.structure_haircut_pct < 1.0:
            raise ValueError("marking.down_round.structure_haircut_pct must be in [0, 1)")
        return self


class MarkingCfg(_Strict):
    secondary: SecondaryCfg = SecondaryCfg()
    ipo: IpoCfg = IpoCfg()
    announced: AnnouncedCfg = AnnouncedCfg()
    convertible: ConvertibleCfg = ConvertibleCfg()
    calibration: CalibrationCfg = CalibrationCfg()
    down_round: DownRoundCfg = DownRoundCfg()


class StalenessCfg(_Strict):
    monitor_months: int
    review_months: int

    @model_validator(mode="after")
    def _sane(self) -> "StalenessCfg":
        if self.monitor_months < 0 or self.review_months < self.monitor_months:
            raise ValueError("exceptions.staleness: months cannot be negative and review_months must be at least monitor_months")
        return self


class ArrGrowthCfg(_Strict):
    monitor_below: float
    review_below: float

    @model_validator(mode="after")
    def _sane(self) -> "ArrGrowthCfg":
        if self.review_below > self.monitor_below:
            raise ValueError("exceptions.arr_growth: review_below must be at or below monitor_below")
        return self


class RunwayCfg(_Strict):
    monitor_below_mo: float
    review_below_mo: float

    @model_validator(mode="after")
    def _sane(self) -> "RunwayCfg":
        if self.review_below_mo < 0 or self.monitor_below_mo < self.review_below_mo:
            raise ValueError("exceptions.runway: months cannot be negative and monitor_below_mo must be at least review_below_mo")
        return self


class DilutionCfg(_Strict):
    monitor_relative_drop: float

    @model_validator(mode="after")
    def _sane(self) -> "DilutionCfg":
        if self.monitor_relative_drop < 0:
            raise ValueError("exceptions.dilution.monitor_relative_drop cannot be negative")
        return self


class SecondaryXCfg(_Strict):
    spread_tolerance_pct: float

    @model_validator(mode="after")
    def _sane(self) -> "SecondaryXCfg":
        if self.spread_tolerance_pct < 0:
            raise ValueError("exceptions.secondary.spread_tolerance_pct cannot be negative")
        return self


class MultipleCfg(_Strict):
    mode: Literal["absolute", "relative_to_comps"] = "absolute"
    absolute_high: float
    absolute_low: float
    high_x_comp: float = 2.0
    low_x_comp: float = 0.5
    min_arr: float
    # in relative mode, screen against a sector multiple only when it is an observed public history
    # (source live:*); a sector whose comps are the fixture, or has none, falls back to the absolute bounds
    require_live_comps: bool = True

    @model_validator(mode="after")
    def _sane(self) -> "MultipleCfg":
        if not (self.absolute_high > self.absolute_low > 0) or not (self.high_x_comp > self.low_x_comp > 0) or self.min_arr < 0:
            raise ValueError("exceptions.multiple: high bounds must exceed low bounds, both positive; min_arr cannot be negative")
        return self


class MoicCfg(_Strict):
    monitor_above: float

    @model_validator(mode="after")
    def _sane(self) -> "MoicCfg":
        if self.monitor_above <= 0:
            raise ValueError("exceptions.moic.monitor_above must be positive")
        return self


class PerformanceGapCfg(_Strict):
    """X-405: a stale price that a live performance screen disagrees with is a REVIEW on its
    own, even though each half is only MONITOR. Off = the halves stay separate."""
    enabled: bool = True


class EscalationCfg(_Strict):
    review_rules_to_block: int = 2

    @model_validator(mode="after")
    def _sane(self) -> "EscalationCfg":
        if self.review_rules_to_block < 1:
            raise ValueError("exceptions.escalation.review_rules_to_block must be at least 1")
        return self


class IndicationsCfg(_Strict):
    """Non-binding or related-party prices that are context (MONITOR) until they move far enough
    from the carried price that a reviewer could change the number (REVIEW)."""
    term_sheet_review_below: float = 0.80      # indicated post ≤ this × last round -> X-109 REVIEW
    note_cap_review_below: float = 0.80        # bridge cap ≤ this × last round -> X-107/X-108 REVIEW: a company
                                               # bridging below its own last round is evidence the mark is high
    insider_round_review_step_up: float = 2.0  # insider-led round post ≥ this × prior post -> X-118 REVIEW
    step_up_review_at: float = 3.0             # any round ≥ this × prior post: X-122 REVIEW unless an outside investor is named
    cheque_price_tolerance: float = 0.10       # hc_investment ÷ Δownership vs the stated post beyond this -> X-119 REVIEW
    cheque_check_min_ownership_delta: float = 0.01   # ... only when the stake bought is ≥ 1.0%: below that the round's own dilution swamps the cheque
    ownership_rounding: float = 0.0005               # half a unit of the 3-dp ownership column: the cheque check allows ± one unit each side
    cheque_ownership_tolerance: float = 0.015        # with a round size on the row: the stake may differ from the round arithmetic by this much
                                                     # (an option-pool top-up or a small note conversion) before X-119 asks about it
    restructure_ownership_tolerance: float = 0.0005  # a Share Restructure row whose ownership moves more than this -> X-133 REVIEW

    @model_validator(mode="after")
    def _sane(self) -> "IndicationsCfg":
        if not (0.0 < self.term_sheet_review_below <= 1.0 and 0.0 < self.note_cap_review_below <= 1.0):
            raise ValueError("exceptions.indications: *_review_below must be in (0, 1]")
        if self.insider_round_review_step_up < 1.0 or self.step_up_review_at < 1.0:
            raise ValueError("exceptions.indications: step-up thresholds must be at least 1x")
        if min(self.cheque_price_tolerance, self.cheque_check_min_ownership_delta, self.ownership_rounding, self.cheque_ownership_tolerance, self.restructure_ownership_tolerance) < 0:
            raise ValueError("exceptions.indications: tolerances cannot be negative")
        return self


class ExceptionsCfg(_Strict):
    indications: IndicationsCfg = IndicationsCfg()
    staleness: StalenessCfg
    arr_growth: ArrGrowthCfg
    runway: RunwayCfg
    dilution: DilutionCfg
    secondary: SecondaryXCfg
    multiple: MultipleCfg
    moic: MoicCfg
    performance_gap: PerformanceGapCfg = PerformanceGapCfg()
    escalation: EscalationCfg = EscalationCfg()


class TolerancesCfg(_Strict):
    prior_mark_reconciliation_musd: float = 0.05
    # An activity row dated before the window is applied (X-905 REVIEW: missed at the last close)
    # only when it falls within this many days before window_start; older rows, and any row dated
    # after the measurement date, are refused (X-905 BLOCK). 91 days = the previous quarter.
    late_event_grace_days: int = 91


class SensitivityCfg(_Strict):
    multiple_shock_pct: list[float] = Field(default_factory=lambda: [-0.20, 0.20])
    # the sectors "software multiples" means in the brief; the shock is also reported on every
    # multiple-exposed position so the reader sees both scopes
    software_sectors: list[str] = Field(default_factory=list)


class SchemaCfg(_Strict):
    activity_sheet_pattern: str = r"^Q[1-4] \d{4} Activity$"
    portfolio_sheet_name: str = "Portfolio"
    unknown_event_type: Literal["block"] = "block"
    unknown_column: Literal["record_and_warn", "fail"] = "record_and_warn"
    missing_required_column: Literal["fail"] = "fail"
    unknown_sector: Literal["absolute_thresholds_and_flag"] = "absolute_thresholds_and_flag"


class NormalizationCfg(_Strict):
    """Ingest tolerances (training/SPEC.md §1.2, §2). Every number the normalizer compares
    against lives here so that "how wrong may a cell be before we refuse to read it" is a
    policy decision, not a code constant."""
    event_type_max_distance: int = 2      # Damerau-Levenshtein budget for an event-type typo
    company_max_distance: int = 1         # ... for a company name
    header_max_distance: int = 2          # ... for a column header
    min_length_for_fuzzy: int = 6         # shorter tokens are never typo-matched (event types, headers)
    company_min_length_for_fuzzy: int = 8 # SPEC §2.3: typo <= 1 only on names >= 8 chars
    unit_suspect_musd_above: float = 100000.0  # a $M cell above this was almost certainly typed in dollars
    percent_points_above: float = 1.0     # a percent field above this was typed in points (55 for 55%)
    percent_block_above: float = 100.0    # ... and above this it is neither a fraction nor points: block
    header_scan_rows: int = 10            # rows searched for the header before giving up
    header_min_known_columns: int = 3     # cells that must resolve to known columns for a row to be the header


class NoteScreenCfg(_Strict):
    enabled: bool = True
    terms: list[str] = Field(default_factory=list)
    # event type -> terms its own rule already handles, so the screen does not re-raise them
    # ("lock-up" on an IPO row is M-040's open item; "warrant" on an Ownership Adjustment is M-013)
    exempt: dict[str, list[str]] = Field(default_factory=dict)


class OpenItemsCfg(_Strict):
    announced_deal_stale_quarters: int = 2
    term_sheet_stale_quarters: int = 1
    note_unconverted_quarters: int = 3
    ipo_lockup_days: int = 180
    unconfirmed_exit_stale_quarters: int = 1   # an exit closed with no cash recorded escalates every quarter it stays open


class DeclarativeCfg(_Strict):
    """The whitelist a `custom_rules` formula is parsed against (engine/dsl.py). A rule for an
    event type the engine does not yet handle is written here, in the policy file, by a person:
    only these fields and operators may appear in it, so a policy edit can never become code."""
    allowed_fields: list[str] = Field(default_factory=list)
    allowed_operators: list[str] = Field(default_factory=list)


class NoteReaderCfg(_Strict):
    """Who reads the free text on each activity row against the case catalogue (notes/catalogue.py).
    `claude` asks the model what the text says that the columns do not — quoted, classified into
    the catalogue's kinds, never a number — and the engine turns that into review findings (X-130,
    X-131, X-126, X-132) that only ever add to what a reviewer sees. Answers are cached under
    data/note_reads/ so reruns are deterministic and offline. Without an API key the reader is off,
    the manifest says so, and the keyword screen (X-105) is the only reading of the notes."""
    provider: Literal["off", "claude"] = "claude"
    model: str = "claude-sonnet-4-5"
    cache: bool = True


class RecommendationCfg(_Strict):
    """Who picks the one resolution shown first for each BLOCK/REVIEW flag. `policy` takes the
    rule's own default (the first suggestion). `claude` asks the model to choose among the
    engine's priced suggestions — never to invent a number — and caches every answer under
    data/recommendations/ so reruns are deterministic and offline; without an API key or a
    cached answer it falls back to `policy` and says so on the recommendation."""
    provider: Literal["policy", "claude"] = "policy"
    model: str = "claude-sonnet-4-5"
    cache: bool = True


class CustomRuleSpec(_Strict):
    """A rule for a new event type, written into the policy file. Formula is DSL, never code."""
    rule_id: str
    version: str = "1"
    event_type: str
    formula: str
    severity: Literal["BLOCK", "REVIEW", "MONITOR"] = "REVIEW"
    rationale: str
    approver: str
    effective_from: date
    fv_level: int = 3
    terminal: bool = False


class PublishCfg(_Strict):
    """Four eyes on the release: the person publishing may not be the approver on any override
    recorded this quarter. Segregation of duties at the one place a number leaves the back office."""
    require_second_approver: bool = True


class RuleConfig(_Strict):
    policy_version: str
    inherits: str | None = None
    quarter: QuarterCfg
    metrics: MetricsCfg = MetricsCfg()
    marking: MarkingCfg = MarkingCfg()
    exceptions: ExceptionsCfg
    tolerances: TolerancesCfg = TolerancesCfg()
    sensitivity: SensitivityCfg = SensitivityCfg()
    schema_: SchemaCfg = Field(default=SchemaCfg(), alias="schema")
    note_screen: NoteScreenCfg = NoteScreenCfg()
    normalization: NormalizationCfg = NormalizationCfg()
    open_items: OpenItemsCfg = OpenItemsCfg()
    declarative: DeclarativeCfg = DeclarativeCfg()
    recommendation: RecommendationCfg = RecommendationCfg()
    note_reader: NoteReaderCfg = NoteReaderCfg()
    publish: PublishCfg = PublishCfg()
    history: HistoryCfg = HistoryCfg()
    custom_rules: list[CustomRuleSpec] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def _check_window(self) -> "RuleConfig":
        q = self.quarter
        if not (q.window_start <= q.window_end == q.measurement_date):
            raise ValueError("quarter.window_end must equal measurement_date and follow window_start")
        if q.prior_close >= q.window_start:
            raise ValueError("quarter.prior_close must precede window_start")
        return self


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_raw(path: Path, _seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    if path in _seen:
        raise ValueError(f"circular policy inheritance: {' -> '.join(str(p) for p in _seen + (path,))}")
    raw = yaml.safe_load(path.read_text()) or {}
    parent = raw.get("inherits")
    if parent:
        parent_path = (path.parent / parent).with_suffix(".yaml") if not str(parent).endswith(".yaml") else path.parent / parent
        base = _load_raw(parent_path, _seen + (path,))
        base.pop("inherits", None)
        raw = _deep_merge(base, {k: v for k, v in raw.items() if k != "inherits"})
        raw["inherits"] = parent
    return raw


def load_config(path: str | Path) -> RuleConfig:
    """Load a policy file, resolving `inherits` chains. Raises on unknown keys."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"policy file not found: {p}")
    return RuleConfig.model_validate(_load_raw(p))


def quarter_window(label: str) -> dict[str, Any]:
    """The `quarter:` block for any calendar quarter, from its label alone — 'Q2 2026' is 1 Apr to
    30 Jun 2026 against the 31 Mar close. Nothing about a year or a month is hardcoded."""
    import calendar
    import re
    from datetime import timedelta

    m = re.match(r"^\s*Q([1-4])\s+(\d{4})\s*$", label)
    if not m:
        raise ValueError(f"quarter label {label!r} is not of the form 'Qn YYYY'")
    n, y = int(m.group(1)), int(m.group(2))
    start = date(y, 3 * n - 2, 1)
    end_month = 3 * n
    end = date(y, end_month, calendar.monthrange(y, end_month)[1])
    return {"label": f"Q{n} {y}", "measurement_date": end, "prior_close": start - timedelta(days=1),
            "window_start": start, "window_end": end}


def next_quarter_window(q: QuarterCfg) -> dict[str, Any]:
    """The `quarter:` block for the period after `q` — 'Q4 2026' rolls to 'Q1 2027'."""
    import re

    m = re.match(r"^\s*Q([1-4])\s+(\d{4})\s*$", q.label)
    if not m:
        raise ValueError(f"quarter label {q.label!r} is not of the form 'Qn YYYY'")
    n, y = int(m.group(1)), int(m.group(2))
    n, y = (1, y + 1) if n == 4 else (n + 1, y)
    return quarter_window(f"Q{n} {y}")


def write_next_policy(current: Path, out_dir: Path | None = None, note: str = "", quarter: str | None = None) -> Path:
    """Write `rules/<next>.yaml` inheriting from `current` with only the quarter window
    changed — or, with `quarter`, the file for that quarter (a back-quarter that arrives after
    the base policy, say). Refuses to overwrite: a policy that already exists may carry
    deliberate changes. Returns the path written."""
    cfg = load_config(current)
    window = quarter_window(quarter) if quarter else next_quarter_window(cfg.quarter)
    slug = window["label"].split()[1] + window["label"].split()[0]        # 'Q4 2026' -> '2026Q4'
    out = (out_dir or current.parent) / f"{slug}.yaml"
    if out.exists():
        raise FileExistsError(f"{out} already exists; edit it rather than regenerating it")
    lines = [
        f"# HC Valuation Engine — policy {slug} (v0.1)",
        f"# Generated from {current.name}: inherits every threshold; override below only what moved,",
        "# bump policy_version, and record why in the commit.",
        f'policy_version: "{slug}-0.1"',
        f"inherits: {current.stem}",
        "",
        "quarter:",
        f'  label: "{window["label"]}"',
        f"  measurement_date: {window['measurement_date'].isoformat()}",
        f"  prior_close: {window['prior_close'].isoformat()}",
        f"  window_start: {window['window_start'].isoformat()}",
        f"  window_end: {window['window_end'].isoformat()}",
    ]
    if note:
        lines.insert(3, f"# {note}")
    out.write_text("\n".join(lines) + "\n")
    load_config(out)   # must round-trip through the strict loader before anyone relies on it
    return out


def default_policy_path(root: Path | None = None) -> Path:
    root = root or repo_root()
    return root / "rules" / "2026Q3.yaml"


def repo_root() -> Path:
    """Locate the repository root from the installed package (editable install) or cwd."""
    here = Path(__file__).resolve()
    for cand in (here.parents[2], Path.cwd()):
        if (cand / "rules").is_dir():
            return cand
    return Path.cwd()
