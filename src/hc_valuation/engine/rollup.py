"""E-05 — fund-level roll-up and portfolio totals."""
from __future__ import annotations

from ..config import RuleConfig
from .inputs import Status
from .models import CompanyResult, CompsMove, Disposition, FundRollup, MarketData, PortfolioTotals, SectorMove


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def fund_rollups(results: list[CompanyResult]) -> list[FundRollup]:
    out: list[FundRollup] = []
    for fund in sorted({c.fund for c in results}):
        cs = [c for c in results if c.fund == fund]
        invested = sum(c.invested_after for c in cs)
        prior = sum(c.prior_mark for c in cs)
        proposed = sum(c.proposed_mark for c in cs)
        booked = sum(c.booked_mark for c in cs)
        rq = sum(c.realized_quarter for c in cs)
        rc = sum(c.realized_cumulative for c in cs)
        top = sorted(((c.company, _safe_div(c.booked_mark, booked)) for c in cs if c.booked_mark > 0),
                     key=lambda t: -t[1])[:5]
        out.append(FundRollup(
            fund=fund, companies=len(cs), active=sum(1 for c in cs if c.status_after == Status.ACTIVE),
            invested=round(invested, 6), prior_nav=round(prior, 6), proposed_nav=round(proposed, 6), booked_nav=round(booked, 6),
            realized_quarter=round(rq, 6), realized_cumulative=round(rc, 6),
            tvpi=round(_safe_div(booked + rc, invested), 4), dpi=round(_safe_div(rc, invested), 4), rvpi=round(_safe_div(booked, invested), 4),
            top_positions=tuple((n, round(s, 4)) for n, s in top),
        ))
    return out


def portfolio_totals(results: list[CompanyResult]) -> PortfolioTotals:
    prior = sum(c.prior_mark for c in results)
    proposed = sum(c.proposed_mark for c in results)
    booked = sum(c.booked_mark for c in results)
    written_off = sum(c.prior_mark for c in results
                      if c.status_before == Status.ACTIVE and c.status_after == Status.SHUT_DOWN)
    exited = sum(c.prior_mark for c in results
                 if c.status_before == Status.ACTIVE and c.status_after == Status.ACQUIRED)
    disp = {d.value: sum(1 for c in results if c.disposition == d) for d in Disposition}
    top10 = sorted((c.booked_mark for c in results), reverse=True)[:10]
    return PortfolioTotals(
        positions=len(results),
        active_after=sum(1 for c in results if c.status_after == Status.ACTIVE),
        prior_nav=round(prior, 6), proposed_nav=round(proposed, 6), booked_nav=round(booked, 6),
        net_movement=round(proposed - prior, 6),
        realized_quarter=round(sum(c.realized_quarter for c in results), 6),
        realized_cumulative=round(sum(c.realized_cumulative for c in results), 6),
        written_off=round(written_off, 6),
        exited_at_prior_mark=round(exited, 6),
        dispositions=disp,
        level1_positions=sum(1 for c in results if c.fv_level == 1),
        top10_concentration=round(_safe_div(sum(top10), booked), 4),
    )


def is_multiple_exposed(fv_level: int | None, arr: float | None, cfg: RuleConfig) -> bool:
    """The one exposure test shared by the ±X% shock, `comps_move` and M-080: a Level 3 mark with
    an ARR at or above the screening floor. Level 1, pre-revenue and terminal positions are
    held flat under any multiple regime."""
    return fv_level == 3 and (arr or 0) >= cfg.exceptions.multiple.min_arr


def sensitivity(results: list[CompanyResult], cfg: RuleConfig) -> dict[str, float]:
    """What the book looks like if revenue multiples move by ±X%, on every multiple-exposed
    position and on the software sectors alone (the brief's wording). The slider in the review
    tool interpolates any shock from `multiple_exposed_nav` / `software_exposed_nav` and each
    company's `multiple_exposed` flag; the ±X% points here are the ones the policy names."""
    base = sum(c.booked_mark for c in results)
    exposed = sum(c.booked_mark for c in results if c.multiple_exposed)
    software = set(cfg.sensitivity.software_sectors)
    soft = sum(c.booked_mark for c in results if c.multiple_exposed and c.sector in software)
    out = {"base_nav": round(base, 6), "multiple_exposed_nav": round(exposed, 6), "software_exposed_nav": round(soft, 6)}
    for s in cfg.sensitivity.multiple_shock_pct:
        tag = f"{s:+.0%}".replace("%", "pct")
        out[f"nav_if_multiples_{tag}"] = round(base + exposed * s, 6)
        out[f"nav_if_software_multiples_{tag}"] = round(base + soft * s, 6)
    return out


def _shift_month(key: str, delta: int) -> str:
    y, m = int(key[:4]), int(key[5:7])
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def comps_move(results: list[CompanyResult], cfg: RuleConfig, market: MarketData) -> CompsMove | None:
    """The observed sensitivity: each sector's basket multiple in the measurement month against
    three months earlier, applied to that sector's multiple-exposed NAV (the same positions
    the ±X% shock moves). Sectors whose history lacks either month are left out and reported
    as uncovered. None when no sector has a history at all."""
    md = cfg.quarter.measurement_date
    now_key = md.strftime("%Y-%m")
    prior_key = _shift_month(now_key, -3)
    base = sum(c.booked_mark for c in results)
    exposed_all = [c for c in results if c.multiple_exposed]
    by_sector: dict[str, list[CompanyResult]] = {}
    for c in exposed_all:
        by_sector.setdefault(c.sector, []).append(c)
    moves: list[SectorMove] = []
    for sector in sorted(by_sector):
        hist = market.comp_history.get(sector) or {}
        now, prior = hist.get(now_key), hist.get(prior_key)
        if not now or not prior:
            continue
        comp = market.comps.get(sector)
        source = comp.source if comp is not None else "unknown"
        counts = market.comp_counts.get(sector) or {}
        exposed = sum(c.booked_mark for c in by_sector[sector])
        q = now / prior - 1
        moves.append(SectorMove(sector=sector, multiple_prior=round(prior, 2), multiple_now=round(now, 2), qoq_pct=round(q, 4),
                                exposed_nav=round(exposed, 6), delta=round(exposed * q, 6), positions=len(by_sector[sector]),
                                live=source.startswith("live:"), source=source,
                                n_prior=counts.get(prior_key), n_now=counts.get(now_key)))
    if not moves:
        return None
    delta = sum(m.delta for m in moves)
    covered = sum(m.exposed_nav for m in moves)
    return CompsMove(prior_month=prior_key, now_month=now_key, base_nav=round(base, 6),
                     exposed_nav=round(sum(c.booked_mark for c in exposed_all), 6), covered_nav=round(covered, 6),
                     delta=round(delta, 6), nav_if_marked_with_comps=round(base + delta, 6),
                     sectors=tuple(sorted(moves, key=lambda m: -abs(m.delta))), all_live=all(m.live for m in moves))
