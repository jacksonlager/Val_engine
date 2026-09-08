"""A policy file with a threshold that cannot mean anything is refused when it is loaded, not
used quietly. Found by a scenario battery: a negative staleness threshold was accepted."""
from __future__ import annotations

import pytest

from conftest import with_policy


@pytest.mark.parametrize("dotted, value", [
    ("exceptions.staleness.monitor_months", -3),
    ("exceptions.staleness.review_months", 12),          # below the 24-month monitor line
    ("exceptions.runway.review_below_mo", 18),           # above the 12-month monitor line
    ("exceptions.arr_growth.review_below", 0.10),        # above the monitor line
    ("exceptions.escalation.review_rules_to_block", 0),
    ("exceptions.indications.term_sheet_review_below", 1.5),
    ("exceptions.indications.step_up_review_at", 0.5),
    ("exceptions.multiple.absolute_low", 40.0),          # above the high bound
    ("exceptions.moic.monitor_above", 0),
    ("marking.calibration.bound_pct", 0),
    ("marking.calibration.min_age_months", -1),
    ("marking.announced.close_probability", 1.2),
    ("marking.ipo.lockup_discount_pct", 1.0),
    ("marking.down_round.structure_haircut_pct", -0.1),
    ("metrics.reporting_lag_months", -1),
])
def test_a_threshold_that_cannot_mean_anything_is_refused(cfg, dotted, value):
    with pytest.raises(Exception):
        with_policy(cfg, **{dotted: value})


def test_the_shipped_policies_still_load():
    from hc_valuation.config import load_config, repo_root
    for p in sorted((repo_root() / "rules").glob("20*Q*.yaml")):     # the quarter policies, not the baskets or the catalogue
        load_config(p)


def test_first_investment_after_the_latest_round_is_a_review(build):
    from datetime import date
    from conftest import position
    _, issues = build([position(first_investment=date(2025, 9, 1), latest_round=date(2025, 6, 15))], [])
    assert [(i.rule_id, i.severity.value) for i in issues] == [("X-926", "REVIEW")]
    _, issues = build([position()], [])
    assert not issues
