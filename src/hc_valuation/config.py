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


class AnnouncedCfg(_Strict):
    treatment: Literal["probability_weighted", "full_deal_value", "hold_prior"] = "probability_weighted"
    close_probability: float = 0.90


class ConvertibleCfg(_Strict):
    new_money_basis: Literal["cost"] = "cost"


class CalibrationCfg(_Strict):
    enabled: bool = False
    min_age_months: int = 24
    bound_pct: float = 0.35
    require_live_history: bool = True   # calibrate only from an observed comps history (live:*), never the fixture
    round_month_tolerance: int = 3      # months either side of the round month the history may be read at


class DownRoundCfg(_Strict):
    """M-012: ownership × post-money on a down round or recap is a ceiling — the preference
    stack and pay-to-play the schema cannot see only lower it. The haircut is a policy
    placeholder for that structure, offered as a priced option beside the ceiling; the round
    documents replace it with a waterfall when they are read."""
    structure_haircut_pct: float = 0.25


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


class ArrGrowthCfg(_Strict):
    monitor_below: float
    review_below: float


class RunwayCfg(_Strict):
    monitor_below_mo: float
    review_below_mo: float


class DilutionCfg(_Strict):
    monitor_relative_drop: float


class SecondaryXCfg(_Strict):
    spread_tolerance_pct: float


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


class MoicCfg(_Strict):
    monitor_above: float


class PerformanceGapCfg(_Strict):
    """X-405: a stale price that a live performance screen disagrees with is a REVIEW on its
    own, even though each half is only MONITOR. Off = the halves stay separate."""
    enabled: bool = True


class EscalationCfg(_Strict):
    review_rules_to_block: int = 2


class IndicationsCfg(_Strict):
    """Non-binding or related-party prices that are context (MONITOR) until they move far enough
    from the carried price that a reviewer could change the number (REVIEW)."""
    term_sheet_review_below: float = 0.80      # indicated post ≤ this × last round -> X-109 REVIEW
    insider_round_review_step_up: float = 2.0  # insider-led round post ≥ this × prior post -> X-118 REVIEW
    step_up_review_at: float = 3.0             # any round ≥ this × prior post: X-122 REVIEW unless an outside investor is named
    cheque_price_tolerance: float = 0.10       # hc_investment ÷ Δownership vs the stated post beyond this -> X-119 REVIEW
    cheque_check_min_ownership_delta: float = 0.01   # ... only when the stake bought is ≥ 1.0% (3-dp ownership rounding)


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


class AdjudicationCfg(_Strict):
    enabled: bool = True
    provider: Literal["stub", "claude"] = "stub"
    auto_accept: Literal["never"] = "never"
    cache_proposals: bool = True
    promote_after_repeats: int = 3
    allowed_fields: list[str] = Field(default_factory=list)
    allowed_operators: list[str] = Field(default_factory=list)


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
    """A declarative rule promoted from adjudication (E-09). Formula is DSL, never code."""
    rule_id: str
    version: str = "1"
    event_type: str
    formula: str
    severity: Literal["BLOCK", "REVIEW", "MONITOR"] = "REVIEW"
    rationale: str
    approver: str
    effective_from: date
    source_proposal: str | None = None
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
    adjudication: AdjudicationCfg = AdjudicationCfg()
    recommendation: RecommendationCfg = RecommendationCfg()
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


def next_quarter_window(q: QuarterCfg) -> dict[str, Any]:
    """The `quarter:` block for the period after `q`, derived from its label and window —
    'Q4 2026' rolls to 'Q1 2027'. Nothing about a year or a month is hardcoded."""
    import calendar
    import re

    m = re.match(r"^\s*Q([1-4])\s+(\d{4})\s*$", q.label)
    if not m:
        raise ValueError(f"quarter label {q.label!r} is not of the form 'Qn YYYY'")
    n, y = int(m.group(1)), int(m.group(2))
    n, y = (1, y + 1) if n == 4 else (n + 1, y)
    start = date(y, 3 * n - 2, 1)
    end_month = 3 * n
    end = date(y, end_month, calendar.monthrange(y, end_month)[1])
    return {"label": f"Q{n} {y}", "measurement_date": end, "prior_close": q.window_end,
            "window_start": start, "window_end": end}


def write_next_policy(current: Path, out_dir: Path | None = None, note: str = "") -> Path:
    """Write `rules/<next>.yaml` inheriting from `current` with only the quarter window
    changed. Refuses to overwrite: a policy that already exists may carry deliberate
    changes. Returns the path written."""
    cfg = load_config(current)
    window = next_quarter_window(cfg.quarter)
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
