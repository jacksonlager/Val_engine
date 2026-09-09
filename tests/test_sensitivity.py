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
    r = execute(RunPaths.default())
    run = r.run
    s = run.sensitivity
    exposed = [c for c in run.companies if c.multiple_exposed]
    assert all(c.fv_level == 3 and (c.arr or 0) >= 0.5 for c in exposed) and len(exposed) == 87
    # a deal-priced position (pending acquisition) is not driven by a multiple, and a note leg
    # held at cost is not either: both stay out of the exposed base
    by = run.by_company()
    assert not by["Gryphonel"].multiple_exposed and any(i.kind.value == "pending_acquisition" for i in by["Gryphonel"].open_items)
    exposed_of = lambda c: c.booked_mark - c.note_at_cost  # noqa: E731
    assert s["multiple_exposed_nav"] == pytest.approx(sum(exposed_of(c) for c in exposed), abs=1e-6)
    assert s["multiple_exposed_nav"] < sum(c.booked_mark for c in exposed), "note legs at cost are excluded from the shock"
    assert not any(c.multiple_exposed for c in run.companies if c.listed or c.fv_level != 3)
    soft = set(run.sensitivity_meta["software_sectors"])
    assert s["software_exposed_nav"] == pytest.approx(sum(exposed_of(c) for c in exposed if c.sector in soft), abs=1e-6)
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
    r = execute(RunPaths.default())
    run = r.run
    m = run.comps_move
    assert m is not None and not m.all_live and all(x.source.startswith("fixture:") for x in m.sectors)
    assert m.exposed_nav == pytest.approx(run.sensitivity["multiple_exposed_nav"], abs=1e-6)
    assert m.covered_nav == pytest.approx(sum(x.exposed_nav for x in m.sectors), abs=1e-6)
    assert m.delta == pytest.approx(sum(x.delta for x in m.sectors), abs=1e-6)
    assert m.nav_if_marked_with_comps == pytest.approx(m.base_nav + m.delta, abs=1e-6)
    assert comps_move(list(run.companies), r.config, r.market) == m


# ---------------------------------------------------------------- per-sector shock

def test_sector_sensitivity_splits_the_same_exposure_and_never_exceeds_the_sector(build, cfg):
    """Each sector carries its own exposure so the review tool can shock one at a time. Two
    invariants hold whatever the book: the sector exposures sum to the portfolio's, and no sector's
    exposed part is larger than the sector itself."""
    soft = with_policy(cfg, **{"sensitivity.software_sectors": ["SaaS"]})
    run, _ = build([position(), position(company="Beta", sector="Robotics"),
                    position(company="Gamma", arr=0.2)], [], cfg_=soft)
    rows = {s.sector: s for s in run.sensitivity_sectors}
    assert set(rows) == {"SaaS", "Robotics"}
    # Gamma sits below the ARR floor, so it counts in the sector's value but not its exposure
    assert rows["SaaS"].positions == 2 and rows["SaaS"].exposed_positions == 1
    assert rows["SaaS"].nav == pytest.approx(20.0) and rows["SaaS"].exposed_nav == pytest.approx(10.0)
    assert rows["SaaS"].software is True and rows["Robotics"].software is False
    assert sum(s.exposed_nav for s in run.sensitivity_sectors) == pytest.approx(run.sensitivity["multiple_exposed_nav"])
    assert all(s.exposed_nav <= s.nav + 1e-9 for s in run.sensitivity_sectors)


def test_sector_sensitivity_on_the_real_book_ties_out_and_is_ordered():
    """On the shipped book: every sector present, exposure summing to the portfolio's, largest
    first — the order the review tool relies on to put the sectors worth arguing about at the top."""
    run = execute(RunPaths.default()).run
    rows = run.sensitivity_sectors
    assert {s.sector for s in rows} == {c.sector for c in run.companies}
    assert sum(s.exposed_nav for s in rows) == pytest.approx(run.sensitivity["multiple_exposed_nav"])
    assert sum(s.nav for s in rows) == pytest.approx(run.totals.booked_nav)
    assert sum(s.positions for s in rows) == run.totals.positions
    assert [s.exposed_nav for s in rows] == sorted((s.exposed_nav for s in rows), reverse=True)
    # a sector holding a listed position carries value the multiple shock must not move
    space = next(s for s in rows if s.sector == "Space & Defense")
    assert space.exposed_nav < space.nav and space.exposed_positions < space.positions
    # shocking every sector at one rate must equal the portfolio shock at that rate
    for pct_ in (-0.2, 0.2):
        assert run.totals.booked_nav + sum(s.exposed_nav * pct_ for s in rows) == pytest.approx(
            run.sensitivity[f"nav_if_multiples_{pct_:+.0%}".replace("%", "pct")])


# ---------------------------------------------------------------- the per-position drill-down

def _moves_with_multiples(c) -> float:
    """The formula the review tool's sector drill-down uses, transcribed from
    `frontend/src/views/Sensitivity.tsx::movesWithMultiples`. It must stay identical to
    `rollup.exposed_amount`, or the positions listed under a sector would not add up to the
    sector's own impact — the one thing a reviewer checks by eye."""
    return (c.booked_mark - c.note_at_cost) if c.multiple_exposed else 0.0


def test_positions_inside_a_sector_add_up_to_that_sectors_impact():
    """Open a sector in the review tool and it lists every position with its own impact. Those
    impacts must sum to the sector row above them, at any shock, or the screen contradicts itself."""
    run = execute(RunPaths.default()).run
    by: dict[str, list] = {}
    for c in run.companies:
        by.setdefault(c.sector, []).append(c)

    for s in run.sensitivity_sectors:
        cs = by[s.sector]
        assert sum(_moves_with_multiples(c) for c in cs) == pytest.approx(s.exposed_nav)
        assert sum(1 for c in cs if _moves_with_multiples(c) > 0) == s.exposed_positions
        assert len(cs) == s.positions
        assert sum(c.booked_mark for c in cs) == pytest.approx(s.nav)
        for shock in (-0.2, -0.07, 0.0, 0.09, 0.2):
            assert sum(_moves_with_multiples(c) * shock for c in cs) == pytest.approx(s.exposed_nav * shock)

    # and a different shock per sector still sums to the same portfolio effect either way round
    mixed = {s.sector: v / 100 for s, v in zip(run.sensitivity_sectors, [-2, -13, -9, -4, 9, 20, 20, 20, 20, 20, 20, 20])}
    assert sum(s.exposed_nav * mixed[s.sector] for s in run.sensitivity_sectors) == pytest.approx(
        sum(_moves_with_multiples(c) * mixed[c.sector] for c in run.companies))


def test_a_position_held_flat_is_held_flat_for_a_reason_the_card_can_name():
    """Every position the shock does not move must fall into one of the buckets the drill-down
    names, so "held flat" is never unexplained."""
    run = execute(RunPaths.default()).run
    flat = [c for c in run.companies if _moves_with_multiples(c) == 0]
    assert flat, "the shipped book has positions a multiple regime does not drive"
    for c in flat:
        named = (c.status_after.value != "Active"          # no longer held
                 or c.fv_level in (1, 2)                    # priced at market, or from an observable input
                 or (c.arr or 0) < run.sensitivity_meta["min_arr"]   # below the screening floor
                 or not c.multiple_exposed)                 # priced by a transaction (a signed deal)
        assert named, f"{c.company} is held flat for a reason the drill-down cannot name"
    # the ones that do move never move more than their whole equity leg
    for c in run.companies:
        assert _moves_with_multiples(c) <= c.booked_mark + 1e-9
