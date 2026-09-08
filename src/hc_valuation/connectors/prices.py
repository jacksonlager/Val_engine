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
import math
from datetime import date, datetime, timezone
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from . import fetch as _fetch
from .fetch import DEFAULT_TIMEOUT_S, FetchError, FetchText, LiveFeedError, RateLimiter, loads_strict

log = logging.getLogger(__name__)

PRICE_SOURCES = ("yahoo", "stooq")
DEFAULT_PRICE_SOURCE = "yahoo"

YAHOO_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
             "?range=10y&interval=1d&events=split")
STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"


@runtime_checkable
class PriceProvider(Protocol):
    """One symbol in, its daily close history out. `name` is what the source label carries
    (`live:edgar+<name>`) and what the cache's `meta.json` records."""

    name: str

    def symbol_for(self, ticker: str) -> str: ...

    def daily_closes(self, ticker: str) -> dict[str, float]: ...

    def splits(self, ticker: str) -> dict[str, float]:
        """`{YYYY-MM-DD: ratio}` — 3-for-1 is 3.0. Empty when the provider reports none.

        Closes come back split-adjusted; share counts from EDGAR are on the basis of the day
        they were filed and are never restated for a later split. Multiplying one by the other
        understates every historical market cap by the splits since — Palo Alto's October 2020
        basket entry came out at 0.85x revenue instead of ~6x, a sixth of the true figure across
        the 3-for-1 of September 2022 and the 2-for-1 of December 2024. The cumulative ratio
        after the *filing* date is what puts the two on the same basis; a provider that cannot
        supply it says so and the months go unverified."""
        return {}


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
        self._payloads: dict[str, str] = {}

    @property
    def headers(self) -> dict[str, str] | None:
        return None

    def url_for(self, ticker: str) -> str:
        return self.URL.format(symbol=self.symbol_for(ticker))

    def symbol_for(self, ticker: str) -> str:  # pragma: no cover — overridden
        raise NotImplementedError

    def _payload_text(self, ticker: str) -> str:
        """One response per ticker per run. Closes and split events come out of the same Yahoo
        payload, so asking for them separately would double every request for no new data."""
        cached = self._payloads.get(ticker)
        if cached is None:
            cached = self._payloads[ticker] = self._get_text(ticker)
        return cached

    def splits(self, ticker: str) -> dict[str, float]:
        """No split events from this provider; historical months stay unverified rather than
        being priced with a share count that may be on the other side of a split."""
        return {}

    def _get_text(self, ticker: str) -> str:
        self._limiter.wait()
        url = self.url_for(ticker)
        try:
            # resolved at call time so the module-level seam (`fetch.fetch_text`) can be replaced in tests
            return (self._fetch or _fetch.fetch_text)(url, self.headers, self.timeout_s)
        except FetchError as ex:
            raise LiveFeedError(f"{self.symbol_for(ticker)}: {ex}") from ex


# ---------------------------------------------------------------- Yahoo Finance

def parse_yahoo_splits(payload: Any, symbol: str = "") -> dict[str, float]:
    """`events.splits` -> `{YYYY-MM-DD: ratio}`. Yahoo gives `numerator`/`denominator`
    (3-for-1 is 3/1) and a `splitRatio` string; the numbers are used, the string ignored."""
    try:
        result = (payload.get("chart") or {}).get("result") or []
        events = (result[0].get("events") or {}) if result else {}
    except AttributeError:
        return {}
    out: dict[str, float] = {}
    for row in (events.get("splits") or {}).values():
        try:
            num, den = float(row["numerator"]), float(row["denominator"])
            when = datetime.fromtimestamp(int(row["date"]), tz=timezone.utc).date().isoformat()
        except (KeyError, TypeError, ValueError):
            continue
        if den > 0 and num > 0:
            out[when] = round(num / den, 6)
    return dict(sorted(out.items()))


def cumulative_split_factor(splits: Mapping[str, float], after: date) -> float:
    """How many of today's shares one share held on `after` has become — the product of every
    split strictly after that date. 1.0 when there have been none.

    `after` is the date the share count's basis belongs to — for an EDGAR fact, the day it was
    filed (`SharesPick.basis_date`), not the month being priced: a count filed before a split
    is pre-split however late the month it is used in."""
    factor = 1.0
    for when, ratio in splits.items():
        if when > after.isoformat():
            factor *= ratio
    return factor


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
    # The payload names what it quotes. A renamed or colliding symbol, or a non-USD listing,
    # multiplied against USD share counts and USD revenue is a wrong number with no error.
    meta = res.get("meta") if isinstance(res.get("meta"), dict) else {}
    got = str(meta.get("symbol") or "").upper()
    if symbol and got and got != symbol.upper():
        raise LiveFeedError(f"{symbol}: Yahoo answered for {got}, not {symbol}")
    currency = str(meta.get("currency") or "").upper()
    if currency and currency != "USD":
        raise LiveFeedError(f"{symbol}: Yahoo quotes it in {currency}; only a USD listing can be priced against SEC filings")
    stamps = res.get("timestamp") or []
    quotes = ((res.get("indicators") or {}).get("quote") or [{}])
    closes = (quotes[0] or {}).get("close") or []
    out: dict[str, float] = {}
    for ts, px in zip(stamps, closes):
        if px is None or ts is None:
            continue
        try:
            day = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
            v = float(px)
            if not math.isfinite(v) or v <= 0:             # a close of 0 is not a price
                continue
            out[day] = v
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
        text = self._payload_text(ticker)
        try:
            payload = loads_strict(text)
        except ValueError as ex:
            raise LiveFeedError(f"{symbol}: response is not JSON ({text[:60]!r}): {ex}") from ex
        return parse_yahoo_chart(payload, symbol)

    def splits(self, ticker: str) -> dict[str, float]:
        """The same payload the closes came from: `&events=split` is already on the URL, so this
        costs no extra request when the response is fetched once per ticker."""
        symbol = self.symbol_for(ticker)
        try:
            return parse_yahoo_splits(loads_strict(self._payload_text(ticker)), symbol)
        except ValueError:
            return {}


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
            v = float(parts[4])
            if not math.isfinite(v) or v <= 0:
                continue
            out[parts[0]] = v
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
