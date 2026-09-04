"""The hardening corpus as part of `pytest`: one test per scenario in training/scenarios/.

Each test runs the scenario through the same checker as `python training/run_gauntlet.py`
and asserts that no check failed; the assertion message lists every failing line so a red
test reads like the report. Skip-free by design — a missing workbook is a failure (run
`python training/generate.py`), not a reason to skip.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT / "training"
if str(TRAINING) not in sys.path:
    sys.path.insert(0, str(TRAINING))

from run_gauntlet import SCENARIOS, run_scenario  # noqa: E402

SCENARIO_FILES = sorted(SCENARIOS.glob("*.yaml"))


def test_corpus_is_present():
    assert len(SCENARIO_FILES) >= 20, "training/scenarios must hold the SPEC §4.1 corpus"


@pytest.mark.parametrize("scenario", SCENARIO_FILES, ids=[p.stem for p in SCENARIO_FILES])
def test_scenario(scenario: Path):
    rep = run_scenario(scenario)
    lines = [c.line() for c in rep.failures]
    if rep.crashed:
        lines.insert(0, f"crashed: {rep.crashed}")
    assert rep.ok, f"{rep.name}: {len(lines)} failure(s)\n" + "\n".join(lines)
