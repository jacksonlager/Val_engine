"""E-05 — fund-level roll-up and portfolio totals."""
from __future__ import annotations

from ..config import RuleConfig
from .inputs import Status
from .models import CompanyResult, Disposition, FundRollup, PortfolioTotals


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


def sensitivity(results: list[CompanyResult], cfg: RuleConfig) -> dict[str, float]:
    """What the book looks like if revenue multiples move by ±X%. Applies the shock to Level 3
    positions that carry meaningful ARR (their marks are the ones a multiple regime drives);
    Level 1, pre-revenue and terminal positions are held flat."""
    base = sum(c.booked_mark for c in results)
    floor = cfg.exceptions.multiple.min_arr
    exposed = sum(c.booked_mark for c in results if c.fv_level == 3 and (c.arr or 0) >= floor)
    out = {"base_nav": round(base, 6), "multiple_exposed_nav": round(exposed, 6)}
    for s in cfg.sensitivity.multiple_shock_pct:
        out[f"nav_if_multiples_{s:+.0%}".replace("%", "pct")] = round(base + exposed * s, 6)
    return out
