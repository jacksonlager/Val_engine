"""The impure orchestration around the pure engine.

    load policy -> read workbook -> validate -> fetch market data -> load override ledger
    -> run_valuation (pure) -> adjudicate novel cases (E-09, outside the engine)

Everything with I/O lives here or below; nothing in `engine/` imports this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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

    @classmethod
    def default(cls, root: Path | None = None, workbook: Path | None = None, policy: Path | None = None) -> "RunPaths":
        root = root or repo_root()
        workbook = workbook or root / "data" / "HC_Mock_Portfolio_Data.xlsx"
        # The prior quarter's sidecar travels with the workbook `build` emitted it beside; a copy
        # in data/ is the fallback so the documented refresh steps keep working either way.
        beside = workbook.parent / "open_items_carry.yaml"
        carry = beside if beside.exists() else root / "data" / "open_items_carry.yaml"
        return cls(
            root=root,
            policy=policy or default_policy_path(root),
            workbook=workbook,
            overrides=root / "data" / "overrides.yaml",
            proposals_dir=root / "data" / "proposals",
            precedent=root / "data" / "precedent.yaml",
            open_items_carry=carry,
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
        ))
    return OverrideLedger(records=tuple(recs))


def load_prior_open_items(path: Path) -> tuple[OpenItem, ...]:
    if not path.exists():
        return ()
    raw = yaml.safe_load(path.read_text()) or {}
    return tuple(OpenItem.model_validate(i) for i in raw.get("open_items", []) or [])


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


def execute(paths: RunPaths | None = None, *, provider: str | None = None, generated_at: datetime | None = None,
            adjudicate: bool = True, refresh_market: bool = False) -> PipelineResult:
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
        input_sha256=file_sha256(paths.workbook), input_file=paths.workbook.name,
        generated_at=generated_at or datetime.now(timezone.utc).replace(microsecond=0),
        market_data_source=source,
    )

    proposals: list = []
    if adjudicate and cfg.adjudication.enabled:
        from .adjudication import adjudicate_run
        proposals = adjudicate_run(run, feed, cfg, paths)
    return PipelineResult(run=run, config=cfg, paths=paths, market=market, proposals=proposals, market_report=market_report)
