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
from typing import Any

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


def policy_for(root: Path, quarter: str | None) -> Path | None:
    if not quarter:
        return None
    q, y = quarter.split()
    p = Path(root) / "rules" / f"{y}{q}.yaml"
    return p if p.is_file() else None


def ledger_dir_for(root: Path, workbook: Path) -> Path:
    """The real book records into `data/`. A workbook under `data/quarters/<chain>/…` records
    into `data/quarters/<chain>/ledger/`, one ledger per chain, so a test quarter's decisions
    never touch the committee's file."""
    root, wb = Path(root).resolve(), Path(workbook).resolve()
    quarters = (root / QUARTERS_DIR).resolve()
    try:
        rel = wb.relative_to(quarters)
    except ValueError:
        return root / "data"
    chain = rel.parts[0] if len(rel.parts) > 1 else rel.stem
    return quarters / chain / "ledger"


def provider_for(root: Path, policy: Path | None, explicit: str | None = None) -> str | None:
    """The market provider a run of this policy would use with no flag: an explicit choice (or
    `HC_MARKET_PROVIDER`) wins; else the synthetic file for the measurement date if one exists;
    else the committed live cache; else None (the fixture). The synthetic file is checked first
    because it exists only for dates no feed can price."""
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
    if synthetic_file(root, md).is_file():
        return "synthetic"
    if MarketCache(root, md).exists():
        return "live"
    return None


def profile_for(root: Path, workbook: Path, *, policy: Path | None = None, ledger_dir: Path | None = None,
                explicit_provider: str | None = None, current: bool = False) -> WorkbookProfile:
    root = Path(root)
    workbook = Path(workbook)
    quarter, marked = quarter_of(workbook)
    under_quarters = _rel(root, workbook).startswith(QUARTERS_DIR.as_posix() + "/")
    pol = policy if policy is not None else policy_for(root, quarter)
    if pol is None and not under_quarters and quarter is None and workbook.exists():
        pol = default_policy_path(root)
    ledger = ledger_dir if ledger_dir is not None else ledger_dir_for(root, workbook)
    usable, reason = True, ""
    if not workbook.is_file():
        usable, reason = False, "file not found"
    elif quarter is None:
        usable, reason = False, "no 'Qn YYYY Activity' sheet"
    elif pol is None:
        usable, reason = False, f"no policy file rules/{quarter.split()[1]}{quarter.split()[0]}.yaml — run `hc-valuation next-policy`"
    return WorkbookProfile(
        id=_rel(root, workbook), workbook=_rel(root, workbook), quarter=quarter,
        policy=_rel(root, pol) if pol else None, ledger_dir=_rel(root, ledger),
        provider=provider_for(root, pol, explicit_provider) if usable else None,
        synthetic=marked or under_quarters, usable=usable, reason=reason, current=current,
    )


def discover(root: Path, current_workbook: Path | None = None, *, explicit_provider: str | None = None,
             current_policy: Path | None = None, current_ledger_dir: Path | None = None) -> list[WorkbookProfile]:
    """Every workbook the dashboard can switch to. The current one first, then `data/quarters/**`
    in path order. Temporary Excel lock files (`~$…`) are skipped."""
    root = Path(root)
    out: list[WorkbookProfile] = []
    seen: set[str] = set()
    if current_workbook is not None:
        cur = profile_for(root, current_workbook, policy=current_policy, ledger_dir=current_ledger_dir,
                          explicit_provider=explicit_provider, current=True)
        out.append(cur)
        seen.add(cur.id)
    default = root / "data" / "HC_Mock_Portfolio_Data.xlsx"
    candidates = [default] if default.is_file() else []
    qdir = root / QUARTERS_DIR
    if qdir.is_dir():
        # not the review workbooks `build` writes (valuation_<quarter>.xlsx has no activity tab)
        candidates += sorted(p for p in qdir.rglob("*.xlsx") if not p.name.startswith(("~$", "valuation_")))
    for wb in candidates:
        prof = profile_for(root, wb, explicit_provider=explicit_provider)
        if prof.id in seen:
            continue
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
