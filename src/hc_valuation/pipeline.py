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
        for the real book, which keeps `data/`. The market cache is not a ledger and never moves.
        `HC_LEDGER_DIR` / `HC_OVERRIDES` in the environment stand in for the arguments when they are
        not given — the test suite pins an empty ledger that way, so a close recorded in `data/`
        never changes what the tests see."""
        import os
        root = root or repo_root()
        if ledger_dir is None and os.environ.get("HC_LEDGER_DIR"):
            ledger_dir = Path(os.environ["HC_LEDGER_DIR"])
        if overrides is None and os.environ.get("HC_OVERRIDES"):
            overrides = Path(os.environ["HC_OVERRIDES"])
        workbook = workbook or root / "data" / "HC_Mock_Portfolio_Data.xlsx"
        # The prior quarter's sidecar travels with the workbook `build` emitted it beside; a copy
        # in data/ is the fallback so the documented refresh steps keep working either way.
        beside = workbook.parent / "open_items_carry.yaml"
        carry = beside if beside.exists() else root / "data" / "open_items_carry.yaml"
        ledger = Path(ledger_dir) if ledger_dir is not None else root / "data"
        if policy is None:
            # The policy for the workbook's own quarter (rules/<YYYY>Q<n>.yaml, written by `next-policy`)
            # when it exists; the base policy otherwise, and X-922 says so if the quarters disagree.
            from .workbooks import policy_for, quarter_of
            policy = policy_for(root, quarter_of(workbook)[0]) if workbook.is_file() else None
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


_QUARTER_RX = __import__("re").compile(r"^\s*Q([1-4])\s+(\d{4})\s*$")


def previous_quarter_label(label: str) -> str:
    m = _QUARTER_RX.match(label)
    if not m:
        raise ValueError(f"quarter label {label!r} is not of the form 'Qn YYYY'")
    q, y = int(m.group(1)), int(m.group(2))
    return f"Q4 {y - 1}" if q == 1 else f"Q{q - 1} {y}"


def _sidecar_quarter(path: Path) -> str | None:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return None
    q = raw.get("quarter")
    return str(q).strip() if q else None


def sidecar_for(paths: "RunPaths", cfg: RuleConfig) -> Path:
    """The `open_items_carry.yaml` this run may read: the one the *previous* quarter's close emitted.
    A sidecar records the quarter it came from; one from any other quarter — this quarter's own,
    written when it was published and left beside the workbook — is not this run's prior state and
    is ignored, so a book can be re-run after its own close without ageing its own open items.
    Looked for beside the workbook first, then beside every uploaded workbook (`data/uploads/*/`),
    then in `data/`: an uploaded Q4 lives in its own folder while Q3's close wrote the sidecar
    beside Q3."""
    wanted = previous_quarter_label(cfg.quarter.label)
    root = Path(paths.root)
    candidates = [paths.open_items_carry, *sorted((root / "data" / "uploads").glob("*/open_items_carry.yaml")),
                  root / "data" / "open_items_carry.yaml"]
    for cand in candidates:
        if cand.exists():
            q = _sidecar_quarter(cand)
            if q is None or q == wanted:      # an unlabelled sidecar (older tool) is taken as written
                return cand
    return paths.open_items_carry.parent / f"open_items_carry.yaml.not-for-{cfg.quarter.label.replace(' ', '_')}"


def next_quarter_input_name(source_workbook: Path, next_label: str) -> str:
    """`Q4 2026 HC Mock Portfolio Data.xlsx` from `HC_Mock_Portfolio_Data.xlsx`; a stem that already
    starts with a quarter label is re-labelled, so the chain reads Q4 → Q1 2027 → ..."""
    stem = _QUARTER_RX.sub("", source_workbook.stem.replace("_", " ")).strip()
    stem = __import__("re").sub(r"^Q[1-4] \d{4}\s+", "", stem)
    return f"{next_label} {stem}.xlsx"


def emit_next_quarter(result: "PipelineResult") -> Path:
    """After a FINAL publish: next quarter's input workbook — the booked marks as Prior Mark, ownership,
    invested and realized post-activity, an empty activity tab for the new quarter — beside the workbook
    that was just closed, with its `open_items_carry.yaml`. The file appears in the review tool's
    Workbook select; the reviewer fills the activity tab in Excel and switches to it."""
    from .export.snapshot import next_quarter_label, write_next_quarter_workbook
    src = Path(result.paths.workbook)
    out = src.parent / next_quarter_input_name(src, next_quarter_label(result.config.quarter.label))
    return write_next_quarter_workbook(result.run, src, out, result.config)


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
    note_report: Any = None                              # notes/schema.py ReadingReport: what the note reader did


STAGES = ("Reading the workbook", "Checking the data", "Reading the notes on each row", "Fetching market data",
          "Loading the decision ledger", "Valuing every position", "Drafting treatments for unrecognised events",
          "Choosing each next step")


def execute(paths: RunPaths | None = None, *, provider: str | None = None, generated_at: datetime | None = None,
            adjudicate: bool = True, refresh_market: bool = False, recommender: str | None = None,
            refresh_recommendations: bool = False, progress: Any = None, note_reader: str | None = None,
            refresh_notes: bool = False, reader: Any = None) -> PipelineResult:
    """`progress(stage_index, stage_name)` is called as each stage of STAGES begins, for a caller
    that shows the work (the upload dialog); it never changes what is computed."""
    from .connectors import assemble_market_data   # local import: connectors may pull optional deps

    def stage(i: int) -> None:
        if progress is not None:
            progress(i, STAGES[i])

    paths = paths or RunPaths.default()
    cfg = load_config(paths.policy)
    stage(0)
    snapshot, feed = read_workbook(paths.workbook, cfg)
    sidecar = sidecar_for(paths, cfg)
    stage(1)
    issues = validate(snapshot, feed, cfg, explained_departures=load_mark_basis(sidecar))
    stage(2)
    # The note reader (notes/reader.py): what each row's free text says that its columns do not,
    # read outside the engine and handed in as value objects. Findings only, never a number.
    from .notes import make_reader, read_feed
    readings, note_report = read_feed(feed, reader or make_reader(cfg, paths.root, note_reader, refresh=refresh_notes))
    stage(3)
    assembled = assemble_market_data(cfg, paths.root, snapshot, feed, provider=provider, refresh=refresh_market)
    market, source = assembled
    market_report = dict(getattr(assembled, "report", None) or {})
    stage(4)
    ledger = load_overrides(paths.overrides)
    prior_items = load_prior_open_items(sidecar)

    stage(5)
    run = run_valuation(
        snapshot, feed, market, ledger, cfg,
        validation=tuple(issues), prior_open_items=prior_items,
        prior_staleness_anchors=load_staleness_anchors(sidecar),
        prior_note_legs=load_note_legs(sidecar),
        note_readings=readings, note_reader=note_report.label(), note_reader_report=note_report.model_dump(),
        input_sha256=file_sha256(paths.workbook), input_file=paths.workbook.name,
        generated_at=generated_at or datetime.now(timezone.utc).replace(microsecond=0),
        market_data_source=source,
    )

    proposals: list = []
    if adjudicate and cfg.adjudication.enabled:
        stage(6)
        from .adjudication import adjudicate_run
        proposals = adjudicate_run(run, feed, cfg, paths)
    stage(7)

    # One recommendation per actionable flag — chosen among the engine's priced suggestions by
    # the policy default or by Claude (recommend.py). Outside the engine, after it, like E-09.
    result = PipelineResult(run=run, config=cfg, paths=paths, market=market, proposals=proposals, market_report=market_report,
                            snapshot=snapshot, note_report=note_report)
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
