"""The prior quarter's flags, reconstructed from the book the run started from.

The engine values one quarter at a time and the flag archive grows from the publish ledger
(`data/published/<slug>.json` carries every flag that was released). The first quarter on
the engine has no published predecessor, so the previous quarter's flags are *reconstructed*:
the Portfolio tab is the book at the prior close (its marks and the operating metrics HC
tracked), and running the same screens against it at the prior measurement date — no
activity, no overrides — gives exactly what the engine would have flagged then. Staleness
is the round's age at that date; growth, runway and the multiple screens read the same
metrics the book carried. Nothing is invented and the point is tagged `reconstructed` so a
reader knows it was not released by anyone.

Once a quarter has been published, its snapshot wins over the reconstruction (see
api/history.py source ranking), so the reconstruction is only ever a bridge for the first
quarter and for backfilled history that predates the engine.
"""
from __future__ import annotations

from typing import Any

from .config import RuleConfig
from .engine.inputs import ActivityFeed, PortfolioSnapshot
from .engine.models import MarketData, OverrideLedger
from .engine.run import run_valuation


def prior_quarter_config(cfg: RuleConfig) -> RuleConfig:
    """The same policy, measured at the prior close: label rolled back one quarter, the window
    the quarter that ended there. Every threshold is unchanged, so the reconstruction is
    the current policy's view of the previous book — not what an earlier policy would have said."""
    from datetime import date, timedelta

    from .api.history import previous_quarter_label   # local: history imports models, not this module
    q = cfg.quarter
    md = q.prior_close
    # the close before that: the last day of the month three months earlier
    y, m = (md.year, md.month - 2) if md.month > 2 else (md.year - 1, md.month + 10)
    prev_close = date(y, m, 1) - timedelta(days=1)
    return cfg.model_copy(update={"quarter": q.model_copy(update={
        "label": previous_quarter_label(q.label), "measurement_date": md, "prior_close": prev_close,
        "window_start": prev_close + timedelta(days=1), "window_end": md})})


def screen_prior_close(snapshot: PortfolioSnapshot, cfg: RuleConfig, market: MarketData) -> dict[str, dict[str, Any]]:
    """`{company: {disposition, flags: [{rule_id, severity, family}], quarter}}` at the prior close."""
    pcfg = prior_quarter_config(cfg)
    feed = ActivityFeed(quarter_label=pcfg.quarter.label, events=(), sheet_name="(reconstructed: no activity)")
    run = run_valuation(snapshot, feed, market, OverrideLedger(), pcfg,
                        input_sha256="", input_file="", market_data_source="reconstruction")
    out: dict[str, dict[str, Any]] = {}
    for c in run.companies:
        out[c.company] = {
            "quarter": pcfg.quarter.label,
            "disposition": c.disposition.value,
            "flags": [{"rule_id": f.rule_id, "severity": f.severity.value, "family": f.family} for f in c.flags],
        }
    return out


def prior_screen_for(result: Any) -> dict[str, dict[str, Any]] | None:
    """The reconstruction for a PipelineResult, computed once and kept on it.

    None — no prior flags in the archive, which the panel reports as "not on record" — unless
    the policy asks for it (`history.reconstruct_prior_flags`), or when the result carries no
    snapshot (a run assembled by hand)."""
    snap = getattr(result, "snapshot", None)
    if snap is None or not result.config.history.reconstruct_prior_flags:
        return None
    cached = getattr(result, "prior_screen", None)
    if cached is None:
        cached = screen_prior_close(snap, result.config, result.market)
        try:
            result.prior_screen = cached
        except Exception:  # noqa: BLE001 — a frozen result just recomputes next time
            pass
    return cached
