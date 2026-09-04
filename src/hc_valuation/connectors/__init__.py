"""Data layer: Protocols in `base.py`, vendor-shaped stubs in `stubs.py`, one live free feed in `live.py`.

`assemble_market_data` is the single entry point the pipeline calls. It returns an
already-fetched `MarketData` value object plus a short source label for the manifest —
the engine never holds a client that could call out mid-run.

Provider selection: explicit argument, else the `HC_MARKET_PROVIDER` environment
variable, else `stub`. `live` (alias `stooq`) tries Stooq and falls back to the stub on
any failure; the manifest label then says `stub` rather than pretending.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from ..config import RuleConfig
from ..engine.inputs import ActivityFeed, PortfolioSnapshot
from ..engine.models import MarketData
from .base import CompanyMetricsProvider, CompsProvider, MarketDataProvider, NewsSignalProvider  # noqa: F401
from .stubs import (
    StubCompanyMetricsProvider, StubCompsProvider, StubIndexProvider, StubMarketDataProvider, StubNewsSignalProvider,
)

log = logging.getLogger(__name__)

ENV_VAR = "HC_MARKET_PROVIDER"
PROVIDERS = ("stub", "live")
_ALIASES = {"stooq": "live"}


def resolve_provider(provider: str | None) -> str:
    name = (provider or os.environ.get(ENV_VAR) or "stub").strip().lower()
    name = _ALIASES.get(name, name)
    if name not in PROVIDERS:
        log.warning("unknown market provider %r; using stub", name)
        name = "stub"
    return name


def assemble_market_data(cfg: RuleConfig, root: Path, snapshot: PortfolioSnapshot, feed: ActivityFeed,
                         provider: str | None = None, *, drift_pct: float = 0.0) -> tuple[MarketData, str]:
    """Build the `MarketData` the engine consumes and label where it came from."""
    md = cfg.quarter.measurement_date
    name = resolve_provider(provider)

    quotes_provider = StubMarketDataProvider(feed, drift_pct=drift_pct, snapshot=snapshot)
    stub_comps = StubCompsProvider(root)
    comps: CompsProvider = stub_comps
    label = "stub"

    if name == "live":
        from .live import StooqCompsProvider   # local import: httpx is an optional extra
        live = StooqCompsProvider(stub_comps, StubIndexProvider(root))
        if live.reached_live:
            comps, label = live, "live:stooq"
        else:
            label = "stub"   # honest: the live path was asked for but did not answer

    quotes = {}
    for company in sorted({e.company for e in feed.events} | set(quotes_provider.carried_listings)):
        q = quotes_provider.quote(company, md)
        if q is not None:
            quotes[company] = q

    sector_comps = comps.sector_multiples(md)
    history = {sector: comps.history(sector) for sector in sector_comps}
    return MarketData(quotes=quotes, comps=sector_comps, comp_history=history, as_of=md), label


def company_metrics_provider(root: Path) -> CompanyMetricsProvider:
    return StubCompanyMetricsProvider(root)


def news_signal_provider(root: Path) -> NewsSignalProvider:
    return StubNewsSignalProvider(root)
