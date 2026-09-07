"""Run every variant through the whole stack and print what breaks. Development probe for
tests/test_variant_workbooks.py; not part of the suite."""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from make_variant_workbooks import write_all  # noqa: E402


def probe(name: str, wb: Path) -> None:
    from fastapi.testclient import TestClient
    from hc_valuation.api.app import create_app
    from hc_valuation.api.history import build_history
    from hc_valuation.api.publish import outstanding
    from hc_valuation.api.sources import build_sources
    from hc_valuation.config import load_config
    from hc_valuation.export.snapshot import write_next_quarter_workbook
    from hc_valuation.ingest.reader import read_workbook
    from hc_valuation.ingest.validate import validate
    from hc_valuation.pipeline import RunPaths, execute, load_mark_basis

    tmp = Path(tempfile.mkdtemp(prefix=f"variant-{name}-"))
    print(f"\n===== {name} =====")
    paths = RunPaths.default(root=ROOT, workbook=wb, policy=ROOT / "rules" / "2026Q3.yaml", ledger_dir=tmp / "ledger")
    try:
        r = execute(paths, provider="stub", adjudicate=False)
    except Exception:
        print("EXECUTE CRASHED"); traceback.print_exc(); return
    run = r.run
    t = run.totals
    print(f"positions {t.positions} readiness {t.readiness} prior {t.prior_nav:,.1f} proposed {t.proposed_nav:,.1f} "
          f"realized {t.realized_quarter:.1f} validation {len(run.validation)} ({sum(1 for v in run.validation if v.blocking)} blocking)")
    ids = sorted({v.rule_id for v in run.validation})
    print("validation ids:", ids)
    blocked = [(c.company, [f.rule_id for f in c.flags if f.severity.value == "BLOCK"]) for c in run.companies if c.readiness.value == "Blocked"]
    print("blocked:", blocked[:14])
    # bridge per company
    bad = [c.company for c in run.companies
           if abs((c.booked_mark - c.prior_mark) - (c.new_investment_quarter + c.valuation_change_quarter - c.realized_quarter)) > 1e-6]
    print("bridge breaks:", bad)
    # round trip
    from hc_valuation.engine.models import ValuationRun
    ValuationRun.model_validate(json.loads(run.model_dump_json()))
    try:
        srcs = build_sources(r); print("sources ok", len(srcs.get("companies", srcs.get("rows", {})) or {}))
    except Exception as ex:
        print("SOURCES FAILED", type(ex).__name__, ex)
    try:
        h = build_history(run, ROOT, published=paths.published_dir); print("history ok", h["counts"], h["errors"][:2])
    except Exception as ex:
        print("HISTORY FAILED", type(ex).__name__, ex)
    try:
        out = write_next_quarter_workbook(run, wb, tmp / "next" / "portfolio_Q4_2026.xlsx", r.config)
        from hc_valuation.config import write_next_policy
        import shutil
        (tmp / "rules").mkdir(exist_ok=True)
        shutil.copy(ROOT / "rules" / "2026Q3.yaml", tmp / "rules" / "2026Q3.yaml")
        cfg4 = load_config(write_next_policy(tmp / "rules" / "2026Q3.yaml"))
        snap, feed = read_workbook(out, cfg4)
        issues = validate(snap, feed, cfg4, explained_departures=load_mark_basis(tmp / "next" / "open_items_carry.yaml"))
        blocking = [i for i in issues if i.blocking]
        print("next-quarter reingest:", len(snap.positions), "positions,", len(blocking), "blocking", [(i.rule_id, i.company, i.message[:70]) for i in blocking[:4]])
    except Exception as ex:
        print("NEXT-QUARTER FAILED", type(ex).__name__, ex); traceback.print_exc()
    print("publish outstanding:", len(outstanding(run)))
    try:
        client = TestClient(create_app(paths, provider="stub", static_dir=tmp / "no-static"))
        for route in ("/api/run", "/api/sources", "/api/history", "/api/signals", "/api/market", "/api/workbooks", "/api/rules", "/api/rationale", "/api/publish/readiness", "/api/health"):
            resp = client.get(route)
            if resp.status_code != 200:
                print("ROUTE", route, resp.status_code, resp.text[:200])
        print("api ok")
    except Exception as ex:
        print("API FAILED", type(ex).__name__, ex); traceback.print_exc()


if __name__ == "__main__":
    out = Path(tempfile.mkdtemp(prefix="variants-"))
    only = sys.argv[1:] or None
    for name, path in write_all(out).items():
        if only and name not in only:
            continue
        probe(name, path)
