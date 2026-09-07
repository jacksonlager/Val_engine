"""Write `data/synthetic_market/<as_of>.yaml` — invented sector multiples for a test quarter.

    python3 scripts/make_synthetic_market.py 2026-12-31 2027-03-31 2027-06-30

Seeds from the PitchBook-shaped fixture's value at the seed month and applies a fixed monthly
drift per sector, so the file is reproducible from this script alone. The output is a stage
prop: its first line says so, the provider refuses it without the marker, and the engine never
calibrates to it (`connectors/synthetic.py`).
"""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hc_valuation.connectors.stubs import StubCompsProvider  # noqa: E402
from hc_valuation.connectors.synthetic import SYNTHETIC_NOTICE, synthetic_file  # noqa: E402

SEED_MONTH = "2026-06"      # the last fixture month the invented series starts *after*
# Monthly drift per sector: deliberately varied so a quarter shows re-rating both ways.
DRIFT = {
    "AI/ML": 0.030, "Cybersecurity": 0.010, "Developer Tools": -0.015, "Infrastructure": 0.005,
    "Data & Analytics": 0.000, "Enterprise SaaS": -0.020, "Space & Defense": 0.020, "Fintech": -0.025,
    "Healthcare": -0.010, "Robotics": 0.015, "Climate & Energy": -0.005, "Consumer": -0.030,
}


def _months(start: str, end: str) -> list[str]:
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= end:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def build(as_of: date) -> dict:
    stub = StubCompsProvider(ROOT)
    end = as_of.strftime("%Y-%m")
    sectors = {}
    for sector in stub.sectors:
        seed = stub.history(sector).get(SEED_MONTH)
        if seed is None:
            continue
        drift = DRIFT.get(sector, 0.0)
        series = {}
        for i, month in enumerate(_months("2026-07", end), start=1):
            wobble = 1 + 0.015 * math.sin(i * 1.7 + len(sector))     # a little shape, still deterministic
            series[month] = round(seed * (1 + drift) ** i * wobble, 2)
        sectors[sector] = {"history": series}
    return {
        "synthetic": True,
        "warning": SYNTHETIC_NOTICE,
        "as_of": as_of.isoformat(),
        "generated_by": "scripts/make_synthetic_market.py",
        "seed": f"fixture:pitchbook@{SEED_MONTH} × (1 + drift)^months; every month after {SEED_MONTH} is invented",
        "sectors": sectors,
    }


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for arg in argv:
        as_of = date.fromisoformat(arg)
        out = synthetic_file(ROOT, as_of)
        out.parent.mkdir(parents=True, exist_ok=True)
        head = ("# SYNTHETIC TEST DATA — invented by scripts/make_synthetic_market.py. Not market data. Never observed.\n"
                "# Used only by `--provider synthetic`; the engine never calibrates a mark to these values.\n")
        out.write_text(head + yaml.safe_dump(build(as_of), sort_keys=False, allow_unicode=True))
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
