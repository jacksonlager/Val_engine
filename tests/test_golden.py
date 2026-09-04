"""E-06 — golden-file test on the real Q3 2026 workbook.

The fixture is compared structurally (both sides parsed to dicts) so a mismatch reads as
"which company, which field, old → new" rather than a wall of JSON. The headline numbers
from docs/CONTEXT.md are asserted explicitly as well, so a regenerated fixture that
quietly encodes a wrong total still fails.
"""
from __future__ import annotations

import json

import pytest

from conftest import GOLDEN_PATH, canonical, diff_runs
from hc_valuation.engine.models import Disposition

EXPECTED_BLOCK = {"Drayvenn", "Gryphonel", "Oakenvale", "Tarnwick Aerospace", "Duskfern", "Birchhollow", "Pellagrin"}

# (company, rule, prior, proposed, realized in quarter)
EVENT_TABLE = [
    ("Fernwave", "M-010", 38.5, 73.52, 0.0),
    ("Drayvenn", "M-040", 80.3, 110.07, 0.0),
    ("Cindral", "M-020", 18.2, 0.0, 28.2),
    ("Ironquill Security", "M-010", 15.8, 29.04, 0.0),
    ("Larkspell", "M-021", 11.4, 0.0, 0.4),
    ("Islewind", "M-021", 10.0, 0.0, 0.0),
    ("Aravine", "M-010", 6.9, 13.88, 0.0),
    ("Marrowick Bio", "M-030", 12.9, 8.77, 3.9),
    ("Oakenvale", "M-012", 5.7, 2.33, 0.0),
    ("Jettamar", "M-010", 2.9, 4.77, 0.0),
    ("Nimbrel", "M-010", 1.2, 3.07, 0.0),
    ("Dovelane Systems", "M-010", 4.1, 5.71, 0.0),
    ("Pellagrin", "M-011", 13.0, 13.93, 0.0),
    ("Tarnwick Aerospace", "M-012", 2.0, 1.14, 0.0),
    ("Gryphonel", "M-050", 3.5, 4.31, 0.0),
    ("Duskfern", "M-060", 6.1, 6.60, 0.0),
    ("Emberfold", "M-060", 1.8, 1.80, 0.0),
    ("Halcyra", "M-070", 2.7, 2.70, 0.0),
]


@pytest.fixture(scope="module")
def golden() -> dict:
    assert GOLDEN_PATH.exists(), "run scripts/regen_golden.py first"
    return json.loads(GOLDEN_PATH.read_text())


def test_matches_golden_fixture(run_real, golden):
    current = canonical(run_real)
    diff = diff_runs(golden, current)
    assert not diff, "run differs from golden fixture:\n  " + "\n  ".join(diff)


def test_headline_totals(run_real):
    t = run_real.totals
    assert t.positions == 100
    assert t.prior_nav == pytest.approx(1139.3, abs=0.05)
    assert t.proposed_nav == pytest.approx(1183.9, abs=0.05)
    assert t.net_movement == pytest.approx(44.6, abs=0.05)
    assert t.realized_quarter == pytest.approx(32.5, abs=0.005)
    assert t.realized_cumulative == pytest.approx(49.6, abs=0.005)
    assert t.written_off == pytest.approx(21.4, abs=0.005)            # Larkspell 11.4 + Islewind 10.0 (shutdowns)
    assert t.exited_at_prior_mark == pytest.approx(18.2, abs=0.005)   # Cindral: sold, not written off
    assert t.level1_positions == 1
    assert t.dispositions == {"BLOCK": 7, "REVIEW": 20, "MONITOR": 39, "CLEAR": 34}
    assert not run_real.validation


def test_blocked_names(run_real):
    blocked = {c.company for c in run_real.companies if c.disposition == Disposition.BLOCK}
    assert blocked == EXPECTED_BLOCK


@pytest.mark.parametrize("company,rule,prior,proposed,realized", EVENT_TABLE, ids=[r[0] for r in EVENT_TABLE])
def test_event_table(run_real, company, rule, prior, proposed, realized):
    c = run_real.by_company()[company]
    assert c.prior_mark == pytest.approx(prior, abs=0.005)
    assert round(c.proposed_mark, 2) == pytest.approx(proposed, abs=0.005)
    assert c.realized_quarter == pytest.approx(realized, abs=0.005)
    assert rule in [s.rule_id for s in c.steps], f"{company}: expected {rule} in chain {[s.rule_id for s in c.steps]}"
    assert any(s.evidence is not None for s in c.steps), "an event-driven step must cite its activity row"


def test_every_company_has_a_chain_and_the_invariant_holds(run_real):
    for c in run_real.companies:
        assert c.steps, c.company
        assert c.proposed_mark == pytest.approx(c.steps[-1].new_value, abs=1e-9), c.company


def test_companies_without_events_carry(run_real):
    with_events = {r[0] for r in EVENT_TABLE}
    for c in run_real.companies:
        if c.company in with_events:
            continue
        assert [s.rule_id for s in c.steps] == ["M-000"], c.company
        assert c.proposed_mark == pytest.approx(c.prior_mark), c.company


def test_manifest_is_pinned(run_real, golden):
    m = run_real.manifest
    assert m.generated_at.isoformat() == "2026-09-30T00:00:00"
    assert m.policy_version == golden["manifest"]["policy_version"]
    assert m.input_sha256 == golden["manifest"]["input_sha256"]
