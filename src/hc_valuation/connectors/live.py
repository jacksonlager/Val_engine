"""One free, keyless live source: Stooq daily CSV.

    https://stooq.com/q/d/l/?s=<symbol>&i=d   ->   Date,Open,High,Low,Close,Volume

A small basket of listed software names is turned into an EV / revenue-style index for
each month: `EV = close × shares − net cash`, `EV/Revenue = EV / NTM revenue`, then the
basket median. Shares, net cash and revenue are a static table in this module and are
APPROXIMATE (mid-2026 order of magnitude, USD millions). Because only the price moves,
the resulting history reflects *price* movement, not fundamentals — it is a proxy for
the level of public software multiples, good enough to re-base the fixture's sector
spreads, and labelled `live:stooq` so nobody mistakes it for PitchBook.

Degrades gracefully by design: any network, parse or arithmetic problem logs one
warning and the fixture-backed provider answers instead. A live failure never breaks a
run and never reaches `engine/`.
"""
from __future__ import annotations

import logging
import statistics
from datetime import date
from typing import Any

from ..engine.models import SectorComp
from .stubs import StubCompsProvider, StubIndexProvider, latest_at_or_before

log = logging.getLogger(__name__)

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
DEFAULT_TIMEOUT_S = 5.0

# symbol: (shares outstanding, millions; net cash, USD millions (negative = net debt); NTM revenue, USD millions)
# Approximate, static, mid-2026. Documented as such; a real deployment would pull these from filings.
BASKET: dict[str, tuple[float, float, float]] = {
    "crm.us": (960.0, 5000.0, 41000.0),    # Salesforce
    "now.us": (207.0, 6000.0, 13000.0),    # ServiceNow
    "adbe.us": (425.0, 1000.0, 23500.0),   # Adobe
    "ddog.us": (345.0, 3000.0, 3300.0),    # Datadog
    "snow.us": (335.0, 3500.0, 4400.0),    # Snowflake
}


class LiveFeedError(RuntimeError):
    """Anything that stops the live path — wrapped so the caller has one thing to catch."""


def fetch_daily_closes(symbol: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, float]:
    """`YYYY-MM-DD -> close` for one Stooq symbol. Raises LiveFeedError on any failure."""
    try:
        import httpx  # optional dependency: the `live` extra
    except ImportError as ex:  # pragma: no cover
        raise LiveFeedError("httpx is not installed (pip install 'hc-valuation[live]')") from ex
    try:
        r = httpx.get(STOOQ_URL.format(symbol=symbol), timeout=timeout_s, follow_redirects=True)
        r.raise_for_status()
    except Exception as ex:  # noqa: BLE001 — every transport failure means "fall back"
        raise LiveFeedError(f"{symbol}: {type(ex).__name__}: {ex}") from ex
    lines = r.text.strip().splitlines()
    if not lines or not lines[0].lower().startswith("date,"):
        raise LiveFeedError(f"{symbol}: response is not a Stooq CSV ({lines[0][:60] if lines else 'empty'!r})")
    out: dict[str, float] = {}
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            out[parts[0]] = float(parts[4])
        except ValueError:
            continue
    if not out:
        raise LiveFeedError(f"{symbol}: CSV carried no closes")
    return out


def month_end_closes(daily: dict[str, float]) -> dict[str, float]:
    """Last available close in each `YYYY-MM`."""
    out: dict[str, float] = {}
    for d in sorted(daily):
        out[d[:7]] = daily[d]
    return out


def ev_to_revenue(close: float, symbol: str) -> float:
    shares, net_cash, revenue = BASKET[symbol]
    return (close * shares - net_cash) / revenue


class StooqCompsProvider:
    """CompsProvider re-basing the fixture's sector spreads on a Stooq-derived software index.

    For month m: `sector(m) = fixture_sector(m) × live_index(m) / fixture_index(m)`. Months the
    live basket cannot cover fall back to the fixture value. `reached_live` tells the
    assembler which label to write to the manifest.
    """

    def __init__(self, fallback: StubCompsProvider, index: StubIndexProvider, timeout_s: float = DEFAULT_TIMEOUT_S,
                 symbols: tuple[str, ...] = tuple(BASKET)) -> None:
        self._fallback = fallback
        self._index = index
        self._timeout = timeout_s
        self._symbols = symbols
        self.reached_live = False
        self.live_index: dict[str, float] = {}
        self.error: str | None = None
        self._load()

    def _load(self) -> None:
        per_symbol: dict[str, dict[str, float]] = {}
        try:
            for sym in self._symbols:
                per_symbol[sym] = month_end_closes(fetch_daily_closes(sym, self._timeout))
        except LiveFeedError as ex:
            self.error = str(ex)
            log.warning("live comps unavailable (%s); falling back to the fixture", ex)
            return
        months = set.intersection(*(set(m) for m in per_symbol.values())) if per_symbol else set()
        for m in sorted(months):
            vals = [ev_to_revenue(per_symbol[s][m], s) for s in per_symbol]
            self.live_index[m] = round(statistics.median(vals), 4)
        self.reached_live = bool(self.live_index)
        if not self.reached_live:
            self.error = "live basket returned no overlapping months"
            log.warning("live comps unavailable (%s); falling back to the fixture", self.error)

    @property
    def source(self) -> str:
        return "live:stooq" if self.reached_live else self._fallback.source

    def _rebase(self, sector: str) -> dict[str, float]:
        base = self._fallback.history(sector)
        if not self.reached_live:
            return base
        out = dict(base)
        for m, v in base.items():
            live = self.live_index.get(m)
            ref = self._index.series.get(m)
            if live and ref:
                out[m] = round(v * live / ref, 4)
        return out

    def history(self, sector: str) -> dict[str, float]:
        return self._rebase(sector)

    def sector_multiples(self, as_of: date) -> dict[str, SectorComp]:
        out: dict[str, SectorComp] = {}
        for sector in self._fallback.sectors:
            obs = latest_at_or_before(self.history(sector), as_of)
            if obs is None:
                continue
            live_month = obs[0] in self.live_index and self.reached_live
            src = f"{'live:stooq' if live_month else self._fallback.source}@{obs[0]}"
            out[sector] = SectorComp(sector=sector, ev_to_arr=obs[1], as_of=as_of, source=src)
        return out

    def diagnostics(self) -> dict[str, Any]:
        return {"reached_live": self.reached_live, "error": self.error, "months": len(self.live_index),
                "basket": list(self._symbols)}
