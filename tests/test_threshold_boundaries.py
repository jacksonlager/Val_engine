"""A workbook figure exactly at a policy threshold is *at* it, not beyond it.

Found by the synthetic Q4 2026 chain (HARDENING_REPORT.md, D-2): a secondary stated at exactly 5.0%
above the round fired X-104 because 1929.795 / 1837.9 − 1 is 0.05000000000000004 in binary. Every
ratio the screens compare now goes through `marking.ratio` / `marking.ratio_change` (six places),
and runway is rounded the same way. These cases sit one unit either side of each line.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.marking import ratio, ratio_change
from tests.conftest import event, make_workbook, position, run_workbook


def _flags(run, company="Alpha") -> set[str]:
    return {f.rule_id for f in run.by_company()[company].flags}


def test_ratio_helpers_land_exactly_on_the_line():
    assert ratio_change(1929.795, 1837.9) == 0.05
    assert ratio(83.04, 103.8) == 0.8
    assert ratio_change(0.108, 0.135) == -0.2
    assert ratio_change(165.0, 150.0) == 0.1


def test_secondary_at_exactly_five_percent_is_inside_tolerance(tmp_path: Path, cfg):
    """Fernwave, Q4 2026: 25% of the stake sold at 1.05 × the Series D post-money."""
    pos = position(company="Alpha", latest_post_money=1837.9, ownership=0.040, prior_mark=73.516, invested=10.3)
    at = event(EventType.SECONDARY, detail="HC sold 25% of its position", value=round(1837.9 * 1.05, 4),
               ownership_after=0.030, proceeds=round(0.010 * 1837.9 * 1.05, 4))
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [at]), cfg)
    c = run.by_company()["Alpha"]
    assert "X-104" not in _flags(run), c.flags
    assert c.proposed_mark == pytest.approx(0.030 * 1837.9)
    # one unit past the line and the screen fires
    beyond = event(EventType.SECONDARY, detail="HC sold 25% of its position", value=round(1837.9 * 1.0501, 4),
                   ownership_after=0.030, proceeds=round(0.010 * 1837.9 * 1.0501, 4))
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [beyond], name="b.xlsx"), cfg)
    assert "X-104" in _flags(run2)


def test_secondary_purchase_at_exactly_the_tolerance_is_inside(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=100.0, ownership=0.050, prior_mark=5.0)
    # 1.05 for 1.0pp: implied 105.0 = +5.0% exactly
    at = event(EventType.SECONDARY_PURCHASE, detail="Bought from an angel", value=105.0, hc_investment=1.05, ownership_after=0.060)
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [at]), cfg)
    assert "X-104" not in _flags(run) and "X-121" in _flags(run)


def test_cheque_price_at_exactly_ten_percent_is_inside(tmp_path: Path, cfg):
    """Solvantra, Q4 2026: 1.65 for +1.0pp at 150 implies 165 = exactly +10%; 1.68 (+12%) is outside."""
    pos = position(company="Alpha", latest_post_money=75.5, ownership=0.118, prior_mark=8.909)
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [event(detail="Series B", value=150.0, hc_investment=1.65, ownership_after=0.128)]), cfg)
    assert "X-119" not in _flags(run)
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [event(detail="Series B", value=150.0, hc_investment=1.68, ownership_after=0.128)], name="b.xlsx"), cfg)
    assert "X-119" in _flags(run2)


def test_term_sheet_at_exactly_eighty_percent_is_review(tmp_path: Path, cfg):
    """Dovelane, Q4 2026: a term sheet at 0.80 × the round is 'at or below' the line -> REVIEW; 80.2% -> MONITOR."""
    pos = position(company="Alpha", latest_post_money=103.8, ownership=0.055, prior_mark=5.709)
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [event(EventType.TERM_SHEET, detail="Series C term sheet", value=83.04)]), cfg)
    f = next(f for f in run.by_company()["Alpha"].flags if f.rule_id == "X-109")
    assert f.severity.value == "REVIEW"
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [event(EventType.TERM_SHEET, detail="Series C term sheet", value=83.3)], name="b.xlsx"), cfg)
    f2 = next(f for f in run2.by_company()["Alpha"].flags if f.rule_id == "X-109")
    assert f2.severity.value == "MONITOR"


def test_dilution_at_exactly_twenty_percent(tmp_path: Path, cfg):
    """Wildebrook, Q4 2026: 0.135 -> 0.108 is a 20.0% relative drop. The policy says '-20% relative';
    the engine's strict reading does not fire at the line and fires one unit past it. Pinned so a
    change is deliberate (see HARDENING_REPORT.md, policy ambiguities)."""
    pos = position(company="Alpha", latest_post_money=54.6, ownership=0.135, prior_mark=7.371)
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [event(detail="Series B", value=120.0, ownership_after=0.108)]), cfg)
    at_line = "X-103" in _flags(run)
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [event(detail="Series B", value=120.0, ownership_after=0.107)], name="b.xlsx"), cfg)
    assert "X-103" in _flags(run2)
    assert at_line is False   # strict: −20.0% is not "beyond" −20%


def test_runway_exactly_seven_months_ages_to_six_and_stays_monitor(tmp_path: Path, cfg):
    """1.4 / 0.2 is 6.999999999999999 in binary; aged one month it must read 6.0, not 5.99…, so the
    REVIEW screen (< 6) does not fire while the MONITOR one (< 12) does."""
    pos = position(company="Alpha", cash=1.4, net_burn=0.2)
    run, _ = run_workbook(make_workbook(tmp_path, [pos], []), cfg)
    c = run.by_company()["Alpha"]
    assert c.runway_months_aged == 6.0
    assert "X-303" in _flags(run) and "X-304" not in _flags(run)
    pos2 = position(company="Alpha", cash=1.398, net_burn=0.2)   # 6.99 -> aged 5.99
    run2, _ = run_workbook(make_workbook(tmp_path, [pos2], [], name="b.xlsx"), cfg)
    assert "X-304" in _flags(run2)


def test_arr_growth_exactly_minus_fifteen_percent_is_monitor(tmp_path: Path, cfg):
    pos = position(company="Alpha", arr_growth=-0.15)
    run, _ = run_workbook(make_workbook(tmp_path, [pos], []), cfg)
    assert "X-301" in _flags(run) and "X-302" not in _flags(run)
    pos2 = position(company="Alpha", arr_growth=-0.1501)
    run2, _ = run_workbook(make_workbook(tmp_path, [pos2], [], name="b.xlsx"), cfg)
    assert "X-302" in _flags(run2)


def test_step_up_at_exactly_three_times_counts(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=4.3, ownership=0.099, prior_mark=0.4257, latest_round=date(2026, 3, 15))
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [event(detail="Series A", value=12.9, ownership_after=0.085,
                                                                 notes="$3.0M insider-led round. No new investor.")]), cfg)
    assert "X-122" in _flags(run)    # 12.9 / 4.3 = 3.0000000000000004 in binary; it is exactly 3×
