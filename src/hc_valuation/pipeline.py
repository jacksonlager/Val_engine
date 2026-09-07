"""The impure orchestration around the pure engine.

    load policy -> read workbook -> validate -> fetch market data -> load override ledger
    -> run_valuation (pure) -> adjudicate novel cases (E-09, outside the engine)

Everything with I/O lives here or below; nothing in `engine/` imports this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .config import RuleConfig, default_policy_path, load_config, repo_root
from .engine.models import MarketData, OpenItem, OverrideLedger, OverrideRecord, ValuationRun
from .engine.run import run_valuation
from .ingest.reader import file_sha256, read_workbook
from .ingest.validate import validate


@dataclass
class RunPaths:
    root: Path
    policy: Path
    workbook: Path
    overrides: Path
    proposals_dir: Path
    precedent: Path
    open_items_carry: Path   # prior quarter's open items, if a previous run exported them
    # Where released snapshots land (`data/published/` by default). Part of the *ledger* — a
    # test chain that records decisions into its own overrides file must publish into its own
    # folder too, or the mark archive (api/history.py) would read invented quarters as real ones.
    published_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.published_dir is None:
            self.published_dir = Path(self.root) / "data" / "published"

    @property
    def ledger_dir(self) -> Path:
        """The folder the decision ledgers share — reported on /api/health so a reviewer can see
        which ledger a decision will be appended to."""
        return Path(self.overrides).parent

    @classmethod
    def default(cls, root: Path | None = None, workbook: Path | None = None, policy: Path | None = None,
                overrides: Path | None = None, ledger_dir: Path | None = None) -> "RunPaths":
        """`ledger_dir` moves every decision record — overrides, proposals, precedent, published
        snapshots — under one folder; `overrides` alone moves just the E-01 file. Neither is set
        for the real book, which keeps `data/`. The market cache is not a ledger and never moves."""
        root = root or repo_root()
        workbook = workbook or root / "data" / "HC_Mock_Portfolio_Data.xlsx"
        # The prior quarter's sidecar travels with the workbook `build` emitted it beside; a copy
        # in data/ is the fallback so the documented refresh steps keep working either way.
        beside = workbook.parent / "open_items_carry.yaml"
        carry = beside if beside.exists() else root / "data" / "open_items_carry.yaml"
        ledger = Path(ledger_dir) if ledger_dir is not None else root / "data"
        return cls(
            root=root,
            policy=policy or default_policy_path(root),
            workbook=workbook,
            overrides=Path(overrides) if overrides is not None else ledger / "overrides.yaml",
            proposals_dir=ledger / "proposals",
            precedent=ledger / "precedent.yaml",
            open_items_carry=carry,
            published_dir=ledger / "published",
        )


def load_overrides(path: Path) -> OverrideLedger:
    if not path.exists():
        return OverrideLedger()
    raw = yaml.safe_load(path.read_text()) or {}
    recs = []
    for r in raw.get("overrides", []) or []:
        recs.append(OverrideRecord(
            company=r["company"], quarter=r["quarter"], proposed=float(r["proposed"]), booked=float(r["booked"]),
            reason=r.get("reason", ""), approver=r.get("approver", ""),
            created_at=r["created_at"] if isinstance(r["created_at"], date) else date.fromisoformat(str(r["created_at"])),
            rule_ids_addressed=tuple(r.get("rule_ids_addressed", []) or []),
            source_proposal=r.get("source_proposal"),
            source_suggestion=r.get("source_suggestion"),
            evidence=dict(r["evidence"]) if isinstance(r.get("evidence"), dict) else None,   # absent on older ledgers
        ))
    return OverrideLedger(records=tuple(recs))


def load_prior_open_items(path: Path) -> tuple[OpenItem, ...]:
    if not path.exists():
        return ()
    raw = yaml.safe_load(path.read_text()) or {}
    return tuple(OpenItem.model_validate(i) for i in raw.get("open_items", []) or [])


def load_staleness_anchors(path: Path) -> dict[str, date]:
    """company -> the price anchor the prior quarter's run kept running (a same-terms extension
    is written to `Latest Round` as its definition asks, and its older anchor lands here)."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    out: dict[str, date] = {}
    for m in raw.get("staleness_anchors", []) or []:
        try:
            out[str(m["company"])] = date.fromisoformat(str(m["anchor"]))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def load_note_legs(path: Path) -> dict[str, float]:
    """company -> the part of its prior mark that is a convertible-note leg at cost (M-060),
    written by the prior quarter's build so the leg is not read as equity (see snapshot.note_legs)."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    out: dict[str, float] = {}
    for m in raw.get("note_legs", []) or []:
        try:
            amount = float(m["amount_musd"])
        except (KeyError, ValueError, TypeError):
            continue
        if amount > 0:
            out[str(m["company"])] = amount
    return out


def load_mark_basis(path: Path) -> dict[str, str]:
    """company -> reason, for prior marks that deliberately depart from last-round pricing."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    return {str(m["company"]): str(m.get("reason", "")) for m in raw.get("mark_basis", []) or []}


@dataclass
class PipelineResult:
    run: ValuationRun
    config: RuleConfig
    paths: RunPaths
    market: MarketData
    proposals: list  # list[TreatmentProposal] from adjudication, may be empty
    market_report: dict = field(default_factory=dict)   # docs/market-feed.md §3, served at /api/market
    recommender: Any = None                              # the chooser that filled Flag.recommendation (recommend.py)
    snapshot: Any = None                                 # the PortfolioSnapshot the run started from (prior_screen reads it)
    prior_screen: Any = None                             # memo: prior_screen.screen_prior_close, filled on first use


def execute(paths: RunPaths | None = None, *, provider: str | None = None, generated_at: datetime | None = None,
            adjudicate: bool = True, refresh_market: bool = False, recommender: str | None = None,
            refresh_recommendations: bool = False) -> PipelineResult:
    from .connectors import assemble_market_data   # local import: connectors may pull optional deps

    paths = paths or RunPaths.default()
    cfg = load_config(paths.policy)
    snapshot, feed = read_workbook(paths.workbook, cfg)
    issues = validate(snapshot, feed, cfg, explained_departures=load_mark_basis(paths.open_items_carry))
    assembled = assemble_market_data(cfg, paths.root, snapshot, feed, provider=provider, refresh=refresh_market)
    market, source = assembled
    market_report = dict(getattr(assembled, "report", None) or {})
    ledger = load_overrides(paths.overrides)
    prior_items = load_prior_open_items(paths.open_items_carry)

    run = run_valuation(
        snapshot, feed, market, ledger, cfg,
        validation=tuple(issues), prior_open_items=prior_items,
        prior_staleness_anchors=load_staleness_anchors(paths.open_items_carry),
        prior_note_legs=load_note_legs(paths.open_items_carry),
        input_sha256=file_sha256(paths.workbook), input_file=paths.workbook.name,
        generated_at=generated_at or datetime.now(timezone.utc).replace(microsecond=0),
        market_data_source=source,
    )

    proposals: list = []
    if adjudicate and cfg.adjudication.enabled:
        from .adjudication import adjudicate_run
        proposals = adjudicate_run(run, feed, cfg, paths)

    # One recommendation per actionable flag — chosen among the engine's priced suggestions by
    # the policy default or by Claude (recommend.py). Outside the engine, after it, like E-09.
    result = PipelineResult(run=run, config=cfg, paths=paths, market=market, proposals=proposals, market_report=market_report,
                            snapshot=snapshot)
    from .recommend import make_chooser, recommend_run
    chooser = make_chooser(cfg, paths.root, recommender, refresh=refresh_recommendations)
    signals = None
    if getattr(chooser, "name", "") == "claude":
        try:
            from .api.signals import build_signals
            signals = build_signals(result)     # vendor context goes into the brief, never into a number
        except Exception:  # noqa: BLE001
            signals = None
    result.run = recommend_run(run, chooser, signals)
    result.recommender = chooser
    return result
