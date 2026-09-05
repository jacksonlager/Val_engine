"""The three sensitivities the brief asks about, and the exposure test they share:

* `sensitivity` — the ±X% multiple shock on every multiple-exposed mark and on the software
  sectors alone (rollup.sensitivity), the two ends of the review tool's slider;
* `comps_move` — the observed counterpart: each sector's public-comps move this quarter applied
  to the marks it drives (rollup.comps_move);
* `multiple_exposed` — Level 3 with ARR at or above the screening floor, the one flag the shock,
  the observed move and M-080 all key off.
"""
from __future__ import annotations

from datetime import date

import pytest
from conftest import only, position, with_policy

from hc_valuation.engine.models import MarketData, SectorComp
from hc_valuation.engine.rollup import comps_move, is_multiple_exposed, sensitivity
from hc_valuation.pipeline import RunPaths, execute

MD = date(2026, 9, 30)


def _market(hist: dict[str, dict[str, float]], counts: dict[str, dict[str, int]] | None = None,
            source: str = "live:edgar+yahoo@2026-09") -> MarketData:
    comps = {s: SectorComp(sector=s, ev_to_arr=h["2026-09"], as_of=MD, source=source) for s, h in hist.items() if "2026-09" in h}
    return MarketData(comps=comps, comp_history=hist, comp_counts=counts or {}, as_of=MD)


# ---------------------------------------------------------------- exposure

def test_multiple_exposed_is_level_3_with_arr_at_or_above_the_floor(build, cfg):
    run, _ = build([position(), position(company="Beta", arr=0.3), position(company="Gamma", arr=None, arr_growth=None),
                    position(company="Delta", arr=0.5)], [])
    by = run.by_company()
    assert by["Alpha"].multiple_exposed and by["Delta"].multiple_exposed          # 10.0 and exactly the 0.5 floor
    assert not by["Beta"].multiple_exposed and not by["Gamma"].multiple_exposed
    assert is_multiple_exposed(1, 10.0, cfg) is False and is_multiple_exposed(3, 0.49, cfg) is False
    assert is_multiple_exposed(3, 0.5, cfg) is True and is_multiple_exposed(None, 10.0, cfg) is False


# ---------------------------------------------------------------- the ±X% shock

def test_shock_moves_only_exposed_marks_and_reports_both_scopes(build, cfg):
    soft = with_policy(cfg, **{"sensitivity.software_sectors": ["SaaS"]})
    run, _ = build([position(), position(company="Beta", sector="Robotics"), position(company="Gamma", arr=0.2)], [], cfg_=soft)
    s = run.sensitivity
    base = run.totals.booked_nav
    assert s["base_nav"] == pytest.approx(base) and base == pytest.approx(30.0)
    assert s["multiple_exposed_nav"] == pytest.approx(20.0) and s["software_exposed_nav"] == pytest.approx(10.0)
    assert s["nav_if_multiples_+20pct"] == pytest.approx(30.0 + 20.0 * 0.2)
    assert s["nav_if_multiples_-20pct"] == pytest.approx(30.0 - 20.0 * 0.2)
    assert s["nav_if_software_multiples_+20pct"] == pytest.approx(30.0 + 10.0 * 0.2)
    assert s["nav_if_software_multiples_-20pct"] == pytest.approx(30.0 - 10.0 * 0.2)
    assert run.sensitivity_meta == {"shock_pct": [-0.2, 0.2], "min_arr": 0.5, "software_sectors": ["SaaS"]}
    # the shock points follow the policy list
    custom = with_policy(soft, **{"sensitivity.multiple_shock_pct": [-0.1, 0.3]})
    run, _ = build([position()], [], cfg_=custom)
    assert set(k for k in run.sensitivity if k.startswith("nav_if")) == {
        "nav_if_multiples_-10pct", "nav_if_multiples_+30pct", "nav_if_software_multiples_-10pct", "nav_if_software_multiples_+30pct"}
    assert run.sensitivity["nav_if_multiples_+30pct"] == pytest.approx(13.0)


def test_shock_on_the_real_book_holds_level_1_and_terminal_flat():
    r = execute(RunPaths.default(), adjudicate=False)
    run = r.run
    s = run.sensitivity
    exposed = [c for c in run.companies if c.multiple_exposed]
    assert all(c.fv_level == 3 and (c.arr or 0) >= 0.5 for c in exposed) and len(exposed) == 88
    assert s["multiple_exposed_nav"] == pytest.approx(sum(c.booked_mark for c in exposed), abs=1e-6)
    assert not any(c.multiple_exposed for c in run.companies if c.listed or c.fv_level != 3)
    soft = set(run.sensitivity_meta["software_sectors"])
    assert s["software_exposed_nav"] == pytest.approx(sum(c.booked_mark for c in exposed if c.sector in soft), abs=1e-6)
    assert 0 < s["software_exposed_nav"] < s["multiple_exposed_nav"] < s["base_nav"]
    assert s["nav_if_multiples_+20pct"] - s["base_nav"] == pytest.approx(0.2 * s["multiple_exposed_nav"], abs=1e-6)
    assert sensitivity(list(run.companies), r.config) == s


# ---------------------------------------------------------------- the observed move

def test_comps_move_applies_each_sectors_quarter_to_its_exposed_marks(build, cfg):
    hist = {"SaaS": {"2026-06": 10.0, "2026-09": 11.0}, "Robotics": {"2026-06": 8.0, "2026-09": 7.6}}
    counts = {"SaaS": {"2026-06": 4, "2026-09": 5}}
    run, _ = build([position(), position(company="Beta", sector="Robotics"), position(company="Gamma", arr=0.2),
                    position(company="Delta", sector="Fintech")], [], market=_market(hist, counts))
    m = run.comps_move
    assert m is not None and m.prior_month == "2026-06" and m.now_month == "2026-09"
    assert m.base_nav == pytest.approx(40.0) and m.exposed_nav == pytest.approx(30.0)
    assert m.covered_nav == pytest.approx(20.0), "Fintech has no history: exposed but not covered"
    by = {x.sector: x for x in m.sectors}
    assert set(by) == {"SaaS", "Robotics"}
    assert by["SaaS"].qoq_pct == pytest.approx(0.1) and by["SaaS"].delta == pytest.approx(1.0) and by["SaaS"].positions == 1
    assert by["SaaS"].n_prior == 4 and by["SaaS"].n_now == 5 and by["Robotics"].n_prior is None
    assert by["Robotics"].qoq_pct == pytest.approx(-0.05) and by["Robotics"].delta == pytest.approx(-0.5)
    assert m.delta == pytest.approx(0.5) and m.nav_if_marked_with_comps == pytest.approx(40.5)
    assert m.all_live and all(x.live and x.source.startswith("live:") for x in m.sectors)
    assert [x.sector for x in m.sectors] == ["SaaS", "Robotics"]                    # largest |delta| first
    # nothing booked moved
    assert run.totals.booked_nav == pytest.approx(40.0) and only(run).booked_mark == pytest.approx(10.0)


def test_comps_move_is_none_without_history_and_labels_the_fixture(build, cfg):
    run, _ = build([position()], [], market=MarketData(as_of=MD))
    assert run.comps_move is None
    run, _ = build([position()], [], market=_market({"SaaS": {"2026-09": 11.0}}))          # no prior month
    assert run.comps_move is None
    fixture = _market({"SaaS": {"2026-06": 10.0, "2026-09": 12.0}}, source="fixture:pitchbook@2026-09")
    run, _ = build([position()], [], cfg_=cfg, market=fixture)
    assert run.comps_move is not None and not run.comps_move.all_live and run.comps_move.sectors[0].live is False
    assert run.comps_move.sectors[0].source == "fixture:pitchbook@2026-09"


def test_comps_move_on_the_real_book_is_the_fixture_and_reconciles():
    r = execute(RunPaths.default(), adjudicate=False)
    run = r.run
    m = run.comps_move
    assert m is not None and not m.all_live and all(x.source.startswith("fixture:") for x in m.sectors)
    assert m.exposed_nav == pytest.approx(run.sensitivity["multiple_exposed_nav"], abs=1e-6)
    assert m.covered_nav == pytest.approx(sum(x.exposed_nav for x in m.sectors), abs=1e-6)
    assert m.delta == pytest.approx(sum(x.delta for x in m.sectors), abs=1e-6)
    assert m.nav_if_marked_with_comps == pytest.approx(m.base_nav + m.delta, abs=1e-6)
    assert comps_move(list(run.companies), r.config, r.market) == m
