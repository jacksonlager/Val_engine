"""Which workbook is the run reading, and which others could it read.

`--input` has always chosen the workbook on the command line. The dashboard needs the same
choice — a reviewer opening Q4 after Q3 should not have to restart the server — and the choice
has consequences beyond the file: the policy must be the one for that quarter (X-922 blocks
otherwise), the decisions must land in the right ledger, and the market provider must be one
that can price the measurement date.

A *profile* bundles those four things for one workbook. `discover(root, current)` lists every
profile the server could switch to: the book the server was started on, and every `.xlsx`
under `data/quarters/` (the synthetic test quarters, each chain with its own ledger folder).
`profile_for(root, workbook)` builds one for an arbitrary path. Nothing here runs the engine.

The run's identity is not touched: `run_id` derives from the workbook's hash, the policy and
the ledger, so switching produces a different run rather than a mutated one.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import default_policy_path, load_config, repo_root

QUARTERS_DIR = Path("data") / "quarters"
_ACTIVITY_RX = re.compile(r"^\s*Q([1-4])\s+(\d{4})\s+Activity\s*$", re.IGNORECASE)
SYNTHETIC_SHEET = "SYNTHETIC TEST DATA"   # a sheet by this name marks a workbook as invented test data


@dataclass
class WorkbookProfile:
    id: str                    # path relative to the repo root; what the API and the UI pass around
    workbook: str
    quarter: str | None        # "Q4 2026", read from the activity sheet's name
    policy: str | None         # rules/<slug>.yaml when it exists
    ledger_dir: str            # where decisions on this book are recorded
    provider: str | None       # the market provider the run would use with no explicit override
    synthetic: bool            # marked as invented test data (sheet marker, or under data/quarters/)
    usable: bool
    reason: str = ""           # why not usable
    current: bool = False
    activity_rows: int | None = None   # rows on the activity tab; 0 = emitted at the last close, nothing entered yet

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def _rel(root: Path, p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(p).as_posix()


def quarter_of(workbook: Path) -> tuple[str | None, bool]:
    """(quarter label from the activity tab, synthetic marker present). Opens the file read-only
    for its sheet names only; a file openpyxl cannot read yields (None, False)."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(workbook, read_only=True)
        names = list(wb.sheetnames)
        wb.close()
    except Exception:  # noqa: BLE001 — a malformed file is reported as unusable, not raised
        return None, False
    quarter = None
    for n in names:
        m = _ACTIVITY_RX.match(n)
        if m:
            quarter = f"Q{m.group(1)} {m.group(2)}"
            break
    synthetic = any(n.strip().upper() == SYNTHETIC_SHEET for n in names)
    return quarter, synthetic


def activity_rows(workbook: Path) -> int | None:
    """How many rows the activity tab carries (None when the file or the tab cannot be read). A book
    with none has nothing to review yet: it is emitted at the previous close and waits for the
    quarter's events before it is offered in the Workbook select."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(workbook, read_only=True)
        name = next((n for n in wb.sheetnames if _ACTIVITY_RX.match(n)), None)
        if name is None:
            wb.close()
            return None
        # rows after the header, wherever the header sits (a title row or a blank row may precede it)
        n, seen_header = 0, False
        for row in wb[name].iter_rows(values_only=True):
            cells = [str(v).strip().lower() for v in row if v not in (None, "")]
            if not cells:
                continue
            if not seen_header:
                if {"date", "company", "event"} & set(cells) or any(c.startswith(("company", "event", "date")) for c in cells):
                    seen_header = True
                continue
            n += 1
        wb.close()
        return n
    except Exception:  # noqa: BLE001
        return None


def policy_for(root: Path, quarter: str | None) -> Path | None:
    if not quarter:
        return None
    q, y = quarter.split()
    p = Path(root) / "rules" / f"{y}{q}.yaml"
    return p if p.is_file() else None


def is_synthetic(workbook: Path, marked: bool) -> bool:
    """Invented test data declares itself: a `SYNTHETIC TEST DATA` sheet or SYNTHETIC in the file
    name. Location is not the test — a real Q4 dropped under data/quarters/ is a real book."""
    return marked or "SYNTHETIC" in Path(workbook).name.upper()


def ledger_dir_for(root: Path, workbook: Path, synthetic: bool = False) -> Path:
    """A real book records into `data/`, the committee's ledger (records are keyed by quarter, so
    every real quarter shares it). A synthetic workbook under `data/quarters/<chain>/…` records
    into `data/quarters/<chain>/ledger/`, one ledger per chain, so invented decisions never touch
    the committee's file."""
    root, wb = Path(root).resolve(), Path(workbook).resolve()
    quarters = (root / QUARTERS_DIR).resolve()
    if not synthetic:
        return root / "data"
    try:
        rel = wb.relative_to(quarters)
    except ValueError:
        return wb.parent / "ledger"
    chain = rel.parts[0] if len(rel.parts) > 1 else rel.stem
    return quarters / chain / "ledger"


def provider_for(root: Path, policy: Path | None, explicit: str | None = None, *, synthetic: bool = False) -> str | None:
    """The market provider a run of this policy would use with no flag: an explicit choice (or
    `HC_MARKET_PROVIDER`) wins; else, for a *synthetic* workbook only, the synthetic file for its
    measurement date; else the committed live cache; else None (the fixture, labelled illustrative).
    A real book never reads invented multiples because a file happens to exist for its date."""
    from .connectors import ENV_VAR
    from .connectors.cache import MarketCache
    from .connectors.synthetic import synthetic_file

    if explicit is not None or os.environ.get(ENV_VAR):
        return explicit
    if policy is None:
        return None
    try:
        md = load_config(policy).quarter.measurement_date
    except Exception:  # noqa: BLE001 — a bad policy is reported by the run, not here
        return None
    if synthetic and synthetic_file(root, md).is_file():
        return "synthetic"
    if MarketCache(root, md).exists():
        return "live"
    return None


def profile_for(root: Path, workbook: Path, *, policy: Path | None = None, ledger_dir: Path | None = None,
                explicit_provider: str | None = None, current: bool = False) -> WorkbookProfile:
    root = Path(root)
    workbook = Path(workbook)
    quarter, marked = quarter_of(workbook)
    synthetic = is_synthetic(workbook, marked)
    pol = policy if policy is not None else policy_for(root, quarter)
    if pol is None and not synthetic and quarter is None and workbook.exists():
        pol = default_policy_path(root)
    ledger = ledger_dir if ledger_dir is not None else ledger_dir_for(root, workbook, synthetic)
    usable, reason = True, ""
    rows = activity_rows(workbook) if workbook.is_file() else None
    if not workbook.is_file():
        usable, reason = False, "file not found"
    elif quarter is None:
        usable, reason = False, "no 'Qn YYYY Activity' sheet"
    elif pol is None:
        usable, reason = False, f"no policy file rules/{quarter.split()[1]}{quarter.split()[0]}.yaml — run `hc-valuation next-policy`"
    elif rows == 0 and not current:
        usable, reason = False, f"nothing to review yet — no rows on the '{quarter} Activity' tab"
    return WorkbookProfile(
        id=_rel(root, workbook), workbook=_rel(root, workbook), quarter=quarter,
        policy=_rel(root, pol) if pol else None, ledger_dir=_rel(root, ledger),
        provider=provider_for(root, pol, explicit_provider, synthetic=synthetic) if (usable or current) else None,
        synthetic=synthetic, usable=usable, reason=reason, current=current, activity_rows=rows,
    )


def discover(root: Path, current_workbook: Path | None = None, *, explicit_provider: str | None = None,
             current_policy: Path | None = None, current_ledger_dir: Path | None = None,
             also: Iterable[Path] = ()) -> list[WorkbookProfile]:
    """Every workbook the dashboard can switch to: the current one first, then `data/*.xlsx` and
    `data/quarters/**` in path order. Temporary Excel lock files (`~$…`) are skipped.

    Synthetic test data is listed only when the server was started on a synthetic workbook (or
    `HC_INCLUDE_SYNTHETIC=1`): a reviewer on the real book must never be offered invented quarters,
    however clearly labelled. The chain exists to harden the engine, not to sit beside the book."""
    root = Path(root)
    out: list[WorkbookProfile] = []
    seen: set[str] = set()
    include_synthetic = os.environ.get("HC_INCLUDE_SYNTHETIC", "").strip() in ("1", "true", "yes")
    if current_workbook is not None:
        cur = profile_for(root, current_workbook, policy=current_policy, ledger_dir=current_ledger_dir,
                          explicit_provider=explicit_provider, current=True)
        out.append(cur)
        seen.add(cur.id)
        include_synthetic = include_synthetic or cur.synthetic
    # What the dashboard can switch to: uploaded workbooks (and what a close emitted beside them) and real
    # quarters placed under data/quarters/. The repository's own fixture in data/ is the test suite's; it
    # is offered only when the server was started on it (it is then `current`).
    candidates: list[Path] = []
    updir = root / "data" / "uploads"
    if updir.is_dir():
        candidates += sorted(p for p in updir.rglob("*.xlsx") if not p.name.startswith(("~$", "valuation_")) and p.parent.name != "incoming")
    qdir = root / QUARTERS_DIR
    if qdir.is_dir():
        # not the review workbooks `build` writes (valuation_<quarter>.xlsx has no activity tab)
        candidates += sorted(p for p in qdir.rglob("*.xlsx") if not p.name.startswith(("~$", "valuation_")))
    # every workbook this server has served, and its neighbours (what a close emitted beside it): the book
    # the server was started on stays reachable after a switch away from it
    for known in also:
        known = Path(known)
        if known.is_file():
            candidates += sorted(p for p in known.parent.glob("*.xlsx") if not p.name.startswith(("~$", "valuation_")))
    for wb in candidates:
        prof = profile_for(root, wb, explicit_provider=explicit_provider)
        if prof.id in seen or (prof.synthetic and not include_synthetic):
            continue
        if prof.activity_rows == 0:
            continue        # emitted at the last close and still empty: there is nothing to review yet
        seen.add(prof.id)
        out.append(prof)
    return out


def paths_for(root: Path, profile: WorkbookProfile):
    """A RunPaths for a discovered profile."""
    from .pipeline import RunPaths
    return RunPaths.default(root=root, workbook=root / profile.workbook,
                            policy=(root / profile.policy) if profile.policy else None,
                            ledger_dir=root / profile.ledger_dir)


def default_root() -> Path:
    return repo_root()
