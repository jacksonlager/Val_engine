"""Data layer: Protocols in `base.py`, vendor-shaped stubs in `stubs.py`, one live free feed in
`live.py` (EDGAR fundamentals × daily closes from a pluggable price source — `prices.py`,
Yahoo by default, Stooq as the alternative — cached under `data/market_cache/`).

`assemble_market_data` is the single entry point the pipeline calls. It returns an
already-fetched `MarketData` value object plus a short source label for the manifest —
the engine never holds a client that could call out mid-run — and the market report
(`docs/market-feed.md` §3) the API serves at `/api/market`. The result unpacks as the
historical `(market, label)` pair and also carries `.report`.

Provider selection: explicit argument, else the `HC_MARKET_PROVIDER` environment
variable, else `stub`. `live` (alias `stooq`) reads the cache or fetches, and falls back to
the stub per sector or entirely; the manifest label then says `stub` rather than pretending.
The price source inside `live` is chosen the same way: explicit argument (`--price-source`),
else `HC_PRICE_SOURCE`, else `defaults.price_source` in the baskets file; the live label is
`live:edgar+<price source>`.
`pitchbook` is reserved for the vendor connector and reports "not configured" until one
exists — it never stops a run.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date
from typing import Any, Callable, Iterator

from ..config import RuleConfig, repo_root
from ..engine.inputs import ActivityFeed, PortfolioSnapshot
from ..engine.models import MarketData
from .base import CompanyMetricsProvider, CompsProvider, MarketDataProvider, NewsSignalProvider  # noqa: F401
from .stubs import (  # noqa: F401 — StubIndexProvider stays re-exported for callers of the earlier live path
    StubCompanyMetricsProvider, StubCompsProvider, StubIndexProvider, StubMarketDataProvider, StubNewsSignalProvider,
)

log = logging.getLogger(__name__)

ENV_VAR = "HC_MARKET_PROVIDER"
PRICE_SOURCE_ENV = "HC_PRICE_SOURCE"
_ALIASES = {"stooq": "live"}
LIVE_LABEL_PREFIX = "live:edgar+"
PITCHBOOK_NOT_CONFIGURED = ("pitchbook provider not configured: set PITCHBOOK_API_KEY and implement "
                            "connectors/pitchbook.py; the fixture answered")


def resolve_provider(provider: str | None) -> str:
    name = (provider or os.environ.get(ENV_VAR) or "stub").strip().lower()
    name = _ALIASES.get(name, name)
    if name not in COMPS_PROVIDERS:
        log.warning("unknown market provider %r; using stub", name)
        name = "stub"
    return name


@dataclass
class CompsRequest:
    """Everything a comps-provider factory may need. A new vendor gets one factory function
    registered under its name (`register_comps_provider`) and nothing else changes."""
    cfg: RuleConfig
    root: Path
    measurement_date: date
    fallback: CompsProvider            # the fixture, for a vendor that answers partially or not at all
    positions: dict[str, int]
    used_by: dict[str, Any]
    refresh: bool = False
    price_source: str | None = None


@dataclass
class CompsAnswer:
    """What a factory returns: the provider to use, the manifest label, the `/api/market`
    report (None = build the fixture report), and any errors to surface."""
    comps: CompsProvider
    label: str
    report: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    months_of_history: int | None = None


CompsFactory = Callable[[CompsRequest], CompsAnswer]
COMPS_PROVIDERS: dict[str, CompsFactory] = {}


def register_comps_provider(name: str, factory: CompsFactory) -> None:
    """Drop a vendor in: `register_comps_provider("pitchbook", make_pitchbook)` — selected by
    `--provider pitchbook` / `HC_MARKET_PROVIDER=pitchbook` with no other edit."""
    COMPS_PROVIDERS[name.strip().lower()] = factory


def _stub_factory(req: CompsRequest) -> CompsAnswer:
    return CompsAnswer(comps=req.fallback, label="stub")


def _pitchbook_factory(req: CompsRequest) -> CompsAnswer:
    log.warning("%s", PITCHBOOK_NOT_CONFIGURED)
    return CompsAnswer(comps=req.fallback, label="stub", errors=[PITCHBOOK_NOT_CONFIGURED])


def _live_factory(req: CompsRequest) -> CompsAnswer:
    try:
        from .baskets import load_baskets
        from .cache import MarketCache
        from .live import PublicCompsProvider   # local import: httpx is an optional extra
        baskets = load_baskets(_baskets_path(req.root))
        live = PublicCompsProvider(baskets, req.fallback, MarketCache(Path(req.root), req.measurement_date),
                                   req.measurement_date, refresh=req.refresh,
                                   price_source=resolve_price_source(req.price_source))
        # honest: never a live label over fixture numbers
        return CompsAnswer(comps=live, label=live.source if live.reached_live else "stub",
                           report=live.report(positions=req.positions, used_by=req.used_by, provider="live"),
                           months_of_history=baskets.defaults.months_of_history)
    except Exception as ex:  # noqa: BLE001 — the live path must never stop a run
        msg = f"live provider unavailable: {type(ex).__name__}: {ex}"
        log.warning("%s; falling back to the fixture", msg)
        return CompsAnswer(comps=req.fallback, label="stub", errors=[msg])


register_comps_provider("stub", _stub_factory)
register_comps_provider("live", _live_factory)
register_comps_provider("pitchbook", _pitchbook_factory)
PROVIDERS = tuple(COMPS_PROVIDERS)   # kept for callers that read the tuple


def resolve_price_source(price_source: str | None) -> str | None:
    """Explicit argument, else `HC_PRICE_SOURCE`, else None (the baskets file decides)."""
    name = (price_source or os.environ.get(PRICE_SOURCE_ENV) or "").strip().lower()
    return name or None


def live_label(price_source: str) -> str:
    return f"{LIVE_LABEL_PREFIX}{price_source}"


@dataclass
class MarketAssembly:
    """What the connector layer hands the pipeline. Iterates as `(market, label)` so callers
    written against the earlier two-tuple keep working."""
    market: MarketData
    label: str
    report: dict[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator[Any]:
        yield self.market
        yield self.label


def positions_by_sector(snapshot: PortfolioSnapshot) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in snapshot.positions:
        out[p.sector] = out.get(p.sector, 0) + 1
    return out


def used_by_from_policy(cfg: RuleConfig) -> dict[str, Any]:
    """How this policy consumes the sector multiples — so the Market panel can say whether
    the numbers currently bite."""
    mode = cfg.exceptions.multiple.mode
    cal = cfg.marking.calibration.enabled
    if mode == "relative_to_comps":
        note = "Screens X-401/X-402 compare each mark's implied multiple against these sector multiples (relative_to_comps)."
    else:
        note = ("Screens X-401/X-402 use absolute thresholds under this policy; set exceptions.multiple.mode: "
                "relative_to_comps to screen against these multiples.")
    if cal:
        note += " M-080 calibration reads the monthly history to write the calibrated alternative mark."
    return {"multiple_mode": mode, "calibration_enabled": cal, "note": note}


def _baskets_path(root: Path | None) -> Path:
    from .baskets import default_baskets_path
    for cand in (root, repo_root()):
        if cand is not None and default_baskets_path(Path(cand)).is_file():
            return default_baskets_path(Path(cand))
    return default_baskets_path(repo_root())


def assemble_market_data(cfg: RuleConfig, root: Path, snapshot: PortfolioSnapshot, feed: ActivityFeed,
                         provider: str | None = None, *, drift_pct: float = 0.0,
                         refresh: bool = False, price_source: str | None = None) -> MarketAssembly:
    """Build the `MarketData` the engine consumes, label where it came from, and build the
    market report. `refresh=True` makes the live provider refetch over its cache;
    `price_source` (else `HC_PRICE_SOURCE`, else the baskets default) picks the price half."""
    from .live import stub_market_report

    md = cfg.quarter.measurement_date
    name = resolve_provider(provider)

    quotes_provider: MarketDataProvider = quotes_provider_for(feed, snapshot, drift_pct=drift_pct)
    stub_comps = StubCompsProvider(root)
    positions = positions_by_sector(snapshot)
    used_by = used_by_from_policy(cfg)

    answer = COMPS_PROVIDERS[name](CompsRequest(cfg=cfg, root=Path(root), measurement_date=md, fallback=stub_comps,
                                                positions=positions, used_by=used_by, refresh=refresh,
                                                price_source=price_source))
    comps, label, report, errors = answer.comps, answer.label, answer.report, list(answer.errors)
    months_of_history = answer.months_of_history
    if report is None:
        if months_of_history is None:
            try:
                from .baskets import load_baskets
                months_of_history = load_baskets(_baskets_path(root)).defaults.months_of_history
            except Exception:  # noqa: BLE001 — the stub does not depend on the baskets file
                months_of_history = None
        report = stub_market_report(stub_comps, md, positions=positions, used_by=used_by, provider=name,
                                    errors=errors, months_of_history=months_of_history)

    quotes = {}
    for company in sorted({e.company for e in feed.events} | set(quotes_provider.carried_listings)):
        q = quotes_provider.quote(company, md)
        if q is not None:
            quotes[company] = q

    sector_comps = comps.sector_multiples(md)
    history = {sector: comps.history(sector) for sector in sector_comps}
    market = MarketData(quotes=quotes, comps=sector_comps, comp_history=history, as_of=md)
    return MarketAssembly(market=market, label=label, report=report)


def quotes_provider_for(feed: ActivityFeed, snapshot: PortfolioSnapshot, *, drift_pct: float = 0.0) -> MarketDataProvider:
    """The measurement-date quote source (the S&P / market-cap slot). Only the fixture exists:
    it seeds a new listing to its IPO print and labels the quote so the flag says so. A real
    provider implements `MarketDataProvider.quote()` and is returned from here instead."""
    return StubMarketDataProvider(feed, drift_pct=drift_pct, snapshot=snapshot)


def company_metrics_provider(root: Path) -> CompanyMetricsProvider:
    return StubCompanyMetricsProvider(root)


def news_signal_provider(root: Path) -> NewsSignalProvider:
    return StubNewsSignalProvider(root)
