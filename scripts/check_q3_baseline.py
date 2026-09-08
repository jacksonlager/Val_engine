"""The Q3 2026 regression check: 1 Blocked / 33 Needs Review / 66 Ready, portfolio fair value 1,184.3.

    python3 scripts/check_q3_baseline.py

Runs the committed workbook under rules/2026Q3.yaml against the committed live market cache with an
empty override ledger (the state the deliverable was published from) and exits non-zero if any of the
three figures moved. Also prints the same run with the stub fixture for reference.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("HC_NOTE_READER", "off")        # the baseline never depends on a model, a key or a cached answer
os.environ.setdefault("HC_RECOMMENDER", "policy")
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hc_valuation.pipeline import RunPaths, execute  # noqa: E402

EXPECTED = {"Blocked": 1, "Needs Review": 33, "Ready": 66}
EXPECTED_FV = 1184.3


def main() -> int:
    # The baseline is defined on an EMPTY committee ledger: the deliverable as published. The working
    # ledger (data/overrides.yaml) fills as the quarter is decided, and that is not a regression.
    paths = RunPaths.default(root=ROOT, overrides=ROOT / "data" / "overrides.baseline-empty.yaml")
    r = execute(paths, provider="live", adjudicate=False)
    run = r.run
    ready = dict(run.totals.readiness)
    fv = round(run.totals.proposed_nav, 1)
    ledger = len(r.run.companies) - sum(1 for c in run.companies if c.override is None)
    live = 0
    try:
        import yaml
        live = len((yaml.safe_load((ROOT / "data" / "overrides.yaml").read_text()) or {}).get("overrides") or [])
    except Exception:  # noqa: BLE001
        pass
    print(f"Q3 2026  provider {run.manifest.market_data_source}  run {run.manifest.run_id}  (working ledger data/overrides.yaml holds {live} decision(s); not read here)")
    print(f"readiness {ready}   proposed fair value {fv:,.1f}   booked {run.totals.booked_nav:,.1f}")
    stub = execute(paths, provider="stub", adjudicate=False).run
    print(f"(stub fixture for reference: readiness {dict(stub.totals.readiness)}, proposed {stub.totals.proposed_nav:,.1f})")
    ok = ready == EXPECTED and fv == EXPECTED_FV and ledger == 0
    print("OK: baseline unchanged" if ok else f"MOVED: expected {EXPECTED} and {EXPECTED_FV} on an empty ledger")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
