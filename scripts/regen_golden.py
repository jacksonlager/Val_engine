"""Regenerate tests/fixtures/golden_q3_2026.json from the real workbook.

Run deliberately, never on a whim: the golden file pins 18 event treatments, the four
queue counts and the portfolio total. Adjudication is off and `generated_at` is fixed so
the fixture is a pure function of (workbook, policy, engine).

    python scripts/regen_golden.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "golden_q3_2026.json"
GENERATED_AT = datetime(2026, 9, 30)


def main() -> int:
    from hc_valuation import pipeline

    paths = pipeline.RunPaths.default(root=ROOT)
    result = pipeline.execute(paths, adjudicate=False, generated_at=GENERATED_AT)
    run = result.run

    # model_dump_json handles dates/enums; the json round-trip gives sorted keys and a stable
    # layout independent of pydantic's serialisation order.
    payload = json.loads(run.model_dump_json())
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")

    t = run.totals
    blocked = sorted(c.company for c in run.companies if c.disposition.value == "BLOCK")
    print(f"wrote {GOLDEN.relative_to(ROOT)}  ({GOLDEN.stat().st_size:,} bytes)")
    print(f"policy {run.manifest.policy_version}  engine {run.manifest.engine_version}  run_id {run.manifest.run_id}")
    print(f"positions {t.positions} (active after {t.active_after})  events {sum(1 for c in run.companies for s in c.steps if s.evidence)}"
          f"  validation issues {len(run.validation)}")
    print(f"prior NAV {t.prior_nav:.1f} → proposed {t.proposed_nav:.1f} (net {t.net_movement:+.1f})")
    print(f"realized in quarter {t.realized_quarter:.1f}  cumulative {t.realized_cumulative:.1f}  written off {t.written_off:.1f}")
    d = t.dispositions
    print(f"dispositions BLOCK {d['BLOCK']} / REVIEW {d['REVIEW']} / MONITOR {d['MONITOR']} / CLEAR {d['CLEAR']}  level-1 {t.level1_positions}")
    print(f"blocked: {', '.join(blocked)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
