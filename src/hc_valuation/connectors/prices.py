"""Daily closes — the pluggable price half of the live comps feed.

A `PriceProvider` turns a SEC ticker into `{YYYY-MM-DD: close}`; `month_end_closes` then
keeps the last available close per month at or before the measurement date. Two providers
ship, both free and keyless:

* **yahoo** (default) — Yahoo Finance's public chart endpoint,
  `https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?range=10y&interval=1d`.
  Undocumented but stable for years (it is what `yfinance` reads). JSON envelope:
  `{"chart": {"result": [{"meta": {...}, "timestamp": [unix, ...],
  "indicators": {"quote": [{"close": [...]}], "adjclose": [...]}}], "error": null}}`.
  Timestamps are converted to ISO dates in UTC; a `null` close (a holiday row) is skipped.
  Yahoo writes `-` where SEC writes `.` in a share class (`BRK.B` -> `BRK-B`).
* **stooq** — `https://stooq.com/q/d/l/?s=<symbol>&i=d`, one `Date,Open,High,Low,Close,Volume`
  CSV per symbol (`<ticker lower>.us`). Kept as an alternative; since September 2026 the
  host answers non-browser clients with a JavaScript browser-verification page, which
  `fetch.py` detects and reports honestly — this code does not try to get around it.

Each provider is rate-limited through `RateLimiter`; the class constant `MAX_PER_S` is the
provider's own polite default and `rules/comps_baskets.yaml` (`defaults.price_max_per_s`)
can lower it. `fetch_text` is the test seam, as everywhere in this package.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Protocol, runtime_checkable

from . import fetch as _fetch
from .fetch import DEFAULT_TIMEOUT_S, FetchError, FetchText, LiveFeedError, RateLimiter

log = logging.getLogger(__name__)

PRICE_SOURCES = ("yahoo", "stooq")
DEFAULT_PRICE_SOURCE = "yahoo"

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=10y&interval=1d"
STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"


@runtime_checkable
class PriceProvider(Protocol):
    """One symbol in, its daily close history out. `name` is what the source label carries
    (`live:edgar+<name>`) and what the cache's `meta.json` records."""

    name: str

    def symbol_for(self, ticker: str) -> str: ...

    def daily_closes(self, ticker: str) -> dict[str, float]: ...


def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("hc-valuation")
    except PackageNotFoundError:   # a checkout without an install
        return "dev"


class _Base:
    name = ""
    URL = ""
    MAX_PER_S = 2.0

    def __init__(self, *, fetch_text: FetchText | None = None, timeout_s: float = DEFAULT_TIMEOUT_S,
                 max_per_s: float | None = None) -> None:
        self._fetch = fetch_text
        self.timeout_s = timeout_s
        self._limiter = RateLimiter(self.MAX_PER_S if max_per_s is None else max_per_s)

    @property
    def headers(self) -> dict[str, str] | None:
        return None

    def url_for(self, ticker: str) -> str:
        return self.URL.format(symbol=self.symbol_for(ticker))

    def symbol_for(self, ticker: str) -> str:  # pragma: no cover — overridden
        raise NotImplementedError

    def _get_text(self, ticker: str) -> str:
        self._limiter.wait()
        url = self.url_for(ticker)
        try:
            # resolved at call time so the module-level seam (`fetch.fetch_text`) can be replaced in tests
            return (self._fetch or _fetch.fetch_text)(url, self.headers, self.timeout_s)
        except FetchError as ex:
            raise LiveFeedError(f"{self.symbol_for(ticker)}: {ex}") from ex


# ---------------------------------------------------------------- Yahoo Finance

def parse_yahoo_chart(payload: Any, symbol: str = "") -> dict[str, float]:
    """`YYYY-MM-DD -> close` from one chart payload. Raises `LiveFeedError` when the envelope
    carries an error, has no result, or yields no close."""
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise LiveFeedError(f"{symbol}: response is not a Yahoo chart payload")
    err = chart.get("error")
    if err:
        desc = err.get("description") if isinstance(err, dict) else str(err)
        raise LiveFeedError(f"{symbol}: Yahoo chart error: {desc or err}")
    results = chart.get("result") or []
    if not results or not isinstance(results[0], dict):
        raise LiveFeedError(f"{symbol}: Yahoo chart carried no result")
    res = results[0]
    stamps = res.get("timestamp") or []
    quotes = ((res.get("indicators") or {}).get("quote") or [{}])
    closes = (quotes[0] or {}).get("close") or []
    out: dict[str, float] = {}
    for ts, px in zip(stamps, closes):
        if px is None or ts is None:
            continue
        try:
            day = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
            out[day] = float(px)
        except (ValueError, OverflowError, OSError):
            continue
    if not out:
        raise LiveFeedError(f"{symbol}: Yahoo chart carried no closes")
    return out


class YahooPrices(_Base):
    name = "yahoo"
    URL = YAHOO_URL
    MAX_PER_S = 2.0

    @property
    def headers(self) -> dict[str, str]:
        return {"User-Agent": f"Mozilla/5.0 (compatible; hc-valuation/{_package_version()})",
                "Accept": "application/json"}

    def symbol_for(self, ticker: str) -> str:
        return ticker.strip().upper().replace(".", "-")

    def daily_closes(self, ticker: str) -> dict[str, float]:
        symbol = self.symbol_for(ticker)
        text = self._get_text(ticker)
        try:
            payload = json.loads(text)
        except ValueError as ex:
            raise LiveFeedError(f"{symbol}: response is not JSON ({text[:60]!r})") from ex
        return parse_yahoo_chart(payload, symbol)


# ---------------------------------------------------------------- Stooq

def parse_daily_csv(text: str, symbol: str = "") -> dict[str, float]:
    """`YYYY-MM-DD -> close`. Raises `LiveFeedError` when the body is not a Stooq CSV (an HTML
    page, an empty body, or a header-only file — Stooq answers 200 to unknown symbols)."""
    lines = text.strip().splitlines()
    if not lines or not lines[0].lower().startswith("date,"):
        head = lines[0][:60] if lines else "empty"
        raise LiveFeedError(f"{symbol}: response is not a Stooq CSV ({head!r})")
    out: dict[str, float] = {}
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            date.fromisoformat(parts[0])
            out[parts[0]] = float(parts[4])
        except ValueError:
            continue
    if not out:
        raise LiveFeedError(f"{symbol}: CSV carried no closes")
    return out


class StooqPrices(_Base):
    name = "stooq"
    URL = STOOQ_URL
    MAX_PER_S = 2.0
    SUFFIX = ".us"

    def symbol_for(self, ticker: str) -> str:
        return f"{ticker.strip().lower()}{self.SUFFIX}"

    def daily_closes(self, ticker: str) -> dict[str, float]:
        return parse_daily_csv(self._get_text(ticker), self.symbol_for(ticker))


# ---------------------------------------------------------------- factory / shared

_PROVIDERS: dict[str, type[_Base]] = {YahooPrices.name: YahooPrices, StooqPrices.name: StooqPrices}


def price_provider(name: str | None = None, *, fetch_text: FetchText | None = None,
                   timeout_s: float = DEFAULT_TIMEOUT_S, max_per_s: float | None = None) -> PriceProvider:
    """Build the named provider (`yahoo` | `stooq`). An unknown name is a `ValueError` — the
    caller (the live provider) turns it into a reported, non-fatal condition."""
    key = (name or DEFAULT_PRICE_SOURCE).strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise ValueError(f"unknown price source {name!r}; expected one of {', '.join(PRICE_SOURCES)}")
    return cls(fetch_text=fetch_text, timeout_s=timeout_s, max_per_s=max_per_s)


def month_end_closes(daily: dict[str, float], as_of: date | None = None) -> dict[str, float]:
    """Last available close in each `YYYY-MM`, ignoring rows after `as_of` when given."""
    limit = as_of.isoformat() if as_of is not None else None
    out: dict[str, float] = {}
    for d in sorted(daily):
        if limit is not None and d > limit:
            continue
        out[d[:7]] = daily[d]
    return out


__all__ = ["DEFAULT_PRICE_SOURCE", "PRICE_SOURCES", "STOOQ_URL", "YAHOO_URL", "LiveFeedError", "PriceProvider",
           "StooqPrices", "YahooPrices", "month_end_closes", "parse_daily_csv", "parse_yahoo_chart", "price_provider"]
