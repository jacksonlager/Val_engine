"""Every malformed variant of the synthetic Q4 2026 workbook is refused or blocked — and only for its own defect.

The variants live under data/quarters/synthetic/malformed/2026Q4/ (scripts/synthetic_chain.py::write_malformed),
each the clean workbook with exactly one thing wrong. The clean book is the baseline; a variant must add
the named validation issue and block the named position, and must not disturb any other position.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from hc_valuation.config import repo_root
from hc_valuation.pipeline import RunPaths, execute

ROOT = repo_root()
CHAIN = ROOT / "data" / "quarters" / "synthetic"
CLEAN = CHAIN / "2026Q4" / "SYNTHETIC_portfolio_Q4_2026.xlsx"
MALFORMED = CHAIN / "malformed" / "2026Q4"
GENERATED_AT = datetime(2027, 1, 12, tzinfo=timezone.utc)

# variant -> (blocking validation ids it must add, positions it must newly block)
EXPECT = {
    "missing_post_money": ({"X-902"}, {"Emberfold"}),
    "unreadable_cell": ({"X-902"}, {"Emberfold"}),
    "non_usd_currency": ({"X-920"}, {"Emberfold"}),
    "event_after_measurement_date": ({"X-905"}, {"Emberfold"}),
    "duplicate_portfolio_row": ({"X-906"}, {"Aravine"}),
    "duplicate_activity_row": ({"X-906"}, {"Gryphonel"}),
    "duplicate_funded_round_row": ({"X-906"}, {"Duskfern"}),
    "prior_mark_unreconciled": ({"X-904"}, {"Beltrix"}),
    "unknown_event_type": ({"X-909"}, {"Gryphonel"}),
    "financing_after_exit": (set(), {"Gryphonel"}),          # contradicted in the run (X-900), not at ingest
    "activity_sheet_wrong_quarter": ({"X-922"}, set()),       # the whole quarter is refused, no position singled out
}

pytestmark = pytest.mark.skipif(not CLEAN.exists() or not MALFORMED.exists(), reason="synthetic chain not built")


def _run(path: Path):
    paths = RunPaths.default(root=ROOT, workbook=path, policy=ROOT / "rules" / "2026Q4.yaml", ledger_dir=ROOT / "data" / "quarters" / "synthetic" / "ledger")
    return execute(paths, provider="synthetic", generated_at=GENERATED_AT).run


@pytest.fixture(scope="module")
def baseline():
    run = _run(CLEAN)
    return run, {c.company for c in run.companies if c.readiness.value == "Blocked"}


@pytest.mark.parametrize("variant", sorted(EXPECT))
def test_variant_is_caught_for_its_own_defect_only(variant: str, baseline):
    base_run, base_blocked = baseline
    path = MALFORMED / f"SYNTHETIC_MALFORMED_{variant}_Q4_2026.xlsx"
    assert path.exists(), path
    run = _run(path)
    want_ids, want_blocked = EXPECT[variant]
    ids = {v.rule_id for v in run.validation if v.blocking}
    assert want_ids <= ids, (variant, ids)
    blocked = {c.company for c in run.companies if c.readiness.value == "Blocked"}
    assert blocked - base_blocked == want_blocked, (variant, blocked - base_blocked)
    if variant == "activity_sheet_wrong_quarter":
        assert run.blocked
    # the defect never moved a number on any other position
    by = run.by_company()
    for c in base_run.companies:
        if c.company in want_blocked:
            continue
        assert by[c.company].proposed_mark == pytest.approx(c.proposed_mark), c.company
        assert by[c.company].invested_after == pytest.approx(c.invested_after), c.company
        assert by[c.company].realized_quarter == pytest.approx(c.realized_quarter), c.company


def test_duplicated_funded_round_is_not_applied_twice(baseline):
    base_run, _ = baseline
    run = _run(MALFORMED / "SYNTHETIC_MALFORMED_duplicate_funded_round_row_Q4_2026.xlsx")
    dup = next(c for c in run.companies if c.company == "Duskfern")
    base = base_run.by_company()["Duskfern"]
    assert dup.invested_after == pytest.approx(base.invested_before)      # neither copy applied
    assert dup.proposed_mark == pytest.approx(base.prior_mark)
