"""Clear the workspace back to "nothing uploaded yet".

What a reset removes is everything a quarter's work produces: the uploaded workbooks (and the next
quarter's input a close emitted beside them), the committee ledger's decisions, the published
snapshots, the carried open items, the precedents, and the cached model
recommendations. What it keeps is everything that is *not* the work: the market cache, the vendor
fixtures, the policy files, the repository's own fixture workbook, the synthetic test chain, and
the assessment source. The ledger reset is written to the ledger the app is actually using
(`RunPaths`), so a chain run with --ledger-dir clears its own folder, never data/.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .fsutil import write_atomically
from .pipeline import RunPaths

EMPTY_LEDGER = """# Committee override ledger (E-01). One record per decision, appended by the review tool
# (POST /api/overrides) or by hand; never edited in place. Each record names the company,
# the quarter, the proposed and booked marks, the approver, the reason and the flag(s) the
# decision resolves (rule_ids_addressed). Committed with the quarter's close so the booked
# number always travels with the decision behind it. Empty: no override has been booked yet.
overrides: []
"""

KEPT = ("data/market_cache/", "data/mock_responses/", "data/HC_Mock_Portfolio_Data.xlsx", "data/quarters/",
        "data/synthetic_market/", "rules/", "Assignment context/")


def _rel(root: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def reset_workspace(paths: RunPaths) -> dict[str, Any]:
    """Remove the work; keep the inputs. Returns what was removed and what was kept, by path."""
    root = Path(paths.root)
    removed: list[str] = []
    files = 0

    def rm_tree(p: Path) -> None:
        nonlocal files
        if p.is_dir():
            files += sum(1 for q in p.rglob("*") if q.is_file())
            shutil.rmtree(p)
            removed.append(_rel(root, p) + "/")

    def rm_file(p: Path) -> None:
        nonlocal files
        if p.is_file():
            p.unlink()
            files += 1
            removed.append(_rel(root, p))

    rm_tree(root / "data" / "uploads")
    rm_tree(Path(paths.published_dir))
    rm_tree(root / "data" / "recommendations")
    rm_file(Path(paths.precedent))
    rm_file(root / "data" / "open_items_carry.yaml")
    ledger = Path(paths.overrides)
    had_records = False
    if ledger.exists():
        try:
            import yaml
            had_records = bool((yaml.safe_load(ledger.read_text()) or {}).get("overrides"))
        except Exception:  # noqa: BLE001
            had_records = True
    ledger.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(ledger, EMPTY_LEDGER)
    if had_records:
        removed.append(_rel(root, ledger) + " (decisions cleared)")
    return {"removed": removed, "files": files, "ledger": _rel(root, ledger), "kept": list(KEPT)}
