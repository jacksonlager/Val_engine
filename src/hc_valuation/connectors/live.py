"""The live public-comps feed: EDGAR fundamentals × daily closes (Yahoo by default, Stooq as
the alternative — `prices.py`) → a sector EV/TTM-revenue multiple with a monthly history
(docs/market-feed.md).

Per constituent, per month: `EV = close × shares outstanding − net cash`,
`EV/Revenue = EV / TTM revenue`, every input being the latest filed value at or before the
month end (and never after the measurement date). Per sector: the median across the basket
in `rules/comps_baskets.yaml`. Below `min_constituents` with data the sector keeps the
fixture value and says so.

Degrades by design: every network, parse or arithmetic problem is caught per constituent,
recorded in `report()`, logged once, and never raised past the provider. `reached_live` and
`source` (`live:edgar+<price source>`) tell the assembler which label to write to the
manifest — a live label never sits over fixture numbers. A source-wide outage (every ticker
failing the same way) is collapsed to one finding in the report rather than one per ticker.
Nothing here is imported by `engine/`.
"""
from __future__ import annotations

import calendar
import logging
import re
import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Mapping

from ..engine.models import SectorComp
from .baskets import BASKETS_FILE, Baskets
from .cache import MarketCache
from .edgar import (
    MAX_REQUESTS_PER_S, EdgarClient, ExtractionError, RevenueHistory, extract, net_cash_at, resolve_ciks,
    shares_at, slim, value_at,
)
from .fetch import DEFAULT_TIMEOUT_S, FetchError, FetchText, LiveFeedError
from .prices import PriceProvider, cumulative_split_factor, month_end_closes, price_provider
from .stubs import StubCompsProvider, latest_at_or_before

# what a JSON payload can raise on its way through `slim`/`extract`/`_value_one` when it is not
# shaped like companyfacts or a closes file
_UNREADABLE = (ExtractionError, ValueError, TypeError, KeyError, AttributeError)


def _positive(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0

log = logging.getLogger(__name__)

LIVE_SOURCE_PREFIX = "live:edgar+"
FIXTURE_SOURCE_PREFIX = "fixture:pitchbook"
PRICE_SOURCE_ENV = "HC_PRICE_SOURCE"
COLLAPSE_AT = 3                       # ≥ this many tickers with the same message -> one report line
_TICKER_HEAD = re.compile(r"^([A-Z][A-Z0-9.\-]{0,9}): (.+)$", re.S)


def live_source(price_name: str) -> str:
    """The manifest / sector label for a live month: `live:edgar+yahoo`."""
    return f"{LIVE_SOURCE_PREFIX}{price_name}"


def collapse_errors(errors: list[str], at: int = COLLAPSE_AT) -> list[str]:
    """Merge `TICKER: <message>` lines that share a message once `at` or more tickers carry
    it: `"<n> tickers: <message> [T1, T2, ...]"`, placed where the first of them was. Sector
    notes and anything not shaped like a ticker line pass through untouched."""
    groups: dict[str, list[str]] = {}
    for e in errors:
        m = _TICKER_HEAD.match(e)
        if m:
            groups.setdefault(m.group(2), []).append(m.group(1))
    big = {msg for msg, ts in groups.items() if len(ts) >= at}
    out, done = [], set()
    for e in errors:
        m = _TICKER_HEAD.match(e)
        if not m or m.group(2) not in big:
            out.append(e)
            continue
        msg = m.group(2)
        if msg not in done:
            done.add(msg)
            out.append(f"{len(groups[msg])} tickers: {msg} [{', '.join(groups[msg])}]")
    return out


# ---------------------------------------------------------------- calendar helpers

def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def month_end(key: str) -> date:
    y, m = int(key[:4]), int(key[5:7])
    return date(y, m, calendar.monthrange(y, m)[1])


def months_back(as_of: date, n: int) -> list[str]:
    """The `n` `YYYY-MM` keys ending at `as_of`'s month, ascending."""
    y, m = as_of.year, as_of.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def shift_months(key: str, delta: int) -> str:
    y, m = int(key[:4]), int(key[5:7])
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def trim_history(history: Mapping[str, float], as_of: date, n: int | None) -> dict[str, float]:
    """The last `n` months at or before `as_of`, ascending keys."""
    key = month_key(as_of)
    keys = sorted(k for k in history if k <= key)
    if n is not None:
        keys = keys[-n:]
    return {k: float(history[k]) for k in keys}


def qoq(history: Mapping[str, float], month: str) -> tuple[float | None, float | None]:
    """(value three months earlier, quarter-on-quarter change) — both None when unknown."""
    cur, prior = history.get(month), history.get(shift_months(month, -3))
    if cur is None or prior is None or not prior:
        return prior, None
    return prior, round(cur / prior - 1, 3)


# ---------------------------------------------------------------- constituent

@dataclass
class Constituent:
    ticker: str
    name: str | None = None
    cik: str | None = None
    status: str = "error"
    price: float | None = None
    price_month: str | None = None
    shares_m: float | None = None
    shares_basis: str | None = None        # what the count is: outstanding (cover page / balance sheet) or a diluted average
    shares_as_of: str | None = None        # the filing date the count is taken from
    shares_age_days: int | None = None     # measurement date minus that date — a count is evidence about *today*
    shares_rejected: list[str] = field(default_factory=list)   # concepts passed over, and why
    months_negative_ev: int = 0            # months excluded from the basket: net cash above market cap
    months_unverified_splits: int = 0      # months excluded: no split history, so the two inputs may differ in basis
    splits_known: bool = False             # split events are on file for this constituent
    market_cap_musd: float | None = None
    net_cash_musd: float | None = None
    ttm_revenue_musd: float | None = None
    net_cash_basis: str | None = None      # says so when the balance sheet was not read, rather than a silent 0
    revenue_through: str | None = None
    ev_to_revenue: float | None = None
    error: str | None = None
    monthly: dict[str, float] = field(default_factory=dict)   # YYYY-MM -> EV/TTM revenue; not exported

    def as_json(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("monthly")
        return d


def fixture_constituent(ticker: str) -> dict[str, Any]:
    return Constituent(ticker=ticker, status="fixture").as_json()


# ---------------------------------------------------------------- provider

class PublicCompsProvider:
    """Implements `CompsProvider` (base.py) over the baskets, the cache and the two clients."""

    def __init__(self, baskets: Baskets, fallback: StubCompsProvider, cache: MarketCache, as_of: date, *,
                 refresh: bool = False, timeout_s: float = DEFAULT_TIMEOUT_S,
                 fetch_text: FetchText | None = None, contact: str | None = None,
                 max_per_s: float = MAX_REQUESTS_PER_S, price_source: str | None = None,
                 price_max_per_s: float | None = None, valuation_date: date | None = None) -> None:
        self.baskets = baskets
        self._fallback = fallback
        self._cache = cache
        self.as_of = as_of                                   # the day the comps are priced as of (the fetch day)
        self.valuation_date = valuation_date or as_of        # the run's measurement date, for the label only
        self._timeout = timeout_s
        self._fetch = fetch_text
        self._edgar = EdgarClient(contact=contact, timeout_s=timeout_s, fetch_text=fetch_text, max_per_s=max_per_s)
        # the price half is pluggable: the kwarg (CLI flag / env) overrides the baskets default
        rate = baskets.defaults.price_max_per_s if price_max_per_s is None else price_max_per_s
        self._prices: PriceProvider = price_provider(price_source or baskets.defaults.price_source,
                                                     fetch_text=fetch_text, timeout_s=timeout_s, max_per_s=rate)
        self.price_source = self._prices.name
        self.live_source = live_source(self.price_source)
        self._months = months_back(as_of, baskets.defaults.months_of_history)

        self.errors: list[str] = []
        self.cache_hit = False
        self.fetched_at: str | None = None
        self._ticker_errors: dict[str, str] = {}
        self._names: dict[str, dict[str, Any]] = {}
        self._constituents: dict[str, Constituent] = {}
        self._live_history: dict[str, dict[str, float]] = {}
        self._live_counts: dict[str, dict[str, int]] = {}
        self._report: dict[str, Any] | None = None

        self._load(refresh)
        self._value_constituents()
        self._aggregate()
        self.reached_live = bool(self._live_history)
        if not self.reached_live:
            log.warning("live comps unavailable (%s); falling back to the fixture",
                        self.errors[0] if self.errors else "no sector reached min_constituents")

    # ---------------------------------------------------------------- loading
    def _record(self, ticker: str, message: str) -> None:
        self._ticker_errors[ticker] = message
        self.errors.append(f"{ticker}: {message}")

    def _load(self, refresh: bool) -> None:
        cache, baskets = self._cache, self.baskets
        # A refetch is fetched *over* the saved feed, never instead of it: every name is asked for
        # again, and a name whose fetch fails keeps its saved facts and closes with a note. The
        # earlier version cleared the folder first, so a refetch on a machine with no network (or
        # without the `live` extra) wiped the committed feed and left the fixture.
        saved_names = cache.read_tickers()
        self._names = {} if refresh else dict(saved_names)
        self.refreshing = refresh
        fetched = False

        # Resolve CIKs first: a ticker SEC does not know (cached as `cik: null`) is skipped on both
        # sides — it cannot be priced without fundamentals — and does not count as missing.
        # A ticker the cached table does not know, or whose baskets override now names a different
        # CIK than the row was resolved to, is resolved again — the policy file wins over the cache.
        unresolved = [t for t in baskets.tickers if t not in self._names or self._override_moved(t)]
        if unresolved:
            try:
                table = self._edgar.company_tickers()
                fetched = True
                resolved = resolve_ciks(unresolved, table, baskets.overrides)
                self._forget_other_filers(resolved)
                cache.write_tickers(resolved)
                self._names.update(resolved)
            except FetchError as ex:
                self.errors.append(f"company_tickers.json: {ex}")
                log.warning("EDGAR ticker table unavailable (%s)", ex)
                for t in unresolved:                      # an override still resolves without the table
                    ov = baskets.overrides.get(t)
                    if ov is not None and ov.cik is not None:
                        self._forget_other_filers({t: {"cik": ov.cik}})
                        self._names[t] = {"cik": ov.cik, "title": ov.name}
                    elif refresh and t in saved_names:      # the saved resolution stands
                        self._names[t] = saved_names[t]
        for t in baskets.tickers:
            row = self._names.get(t)
            if row is None:
                self._record(t, "EDGAR ticker table unavailable; cannot resolve CIK")
            elif row.get("cik") is None:
                self._record(t, "EDGAR cannot resolve ticker (not in company_tickers.json)")
        fetchable = [t for t in baskets.tickers if t not in self._ticker_errors]

        missing_edgar, missing_prices = cache.missing(fetchable)
        if refresh:
            missing_edgar, missing_prices = list(fetchable), list(fetchable)
        if not cache.exists():
            # per-ticker files with no provenance record (when fetched, by which price source) are
            # not a cache: everything is fetched again rather than served as live from nowhere
            missing_edgar, missing_prices = list(fetchable), list(fetchable)
        stale_prices = not cache.prices_match(self.price_source)
        if stale_prices:                                   # closes written by another provider: the price half is a miss
            log.warning("market cache %s holds %s closes; refetching prices from %s",
                        cache.rel_dir, cache.price_source(), self.price_source)
            missing_prices = list(fetchable)
        self.cache_hit = cache.exists() and not unresolved and not missing_edgar and not missing_prices
        kept: list[str] = []                               # names whose refetch failed and whose saved feed serves instead
        for t in missing_edgar:
            raw = None if refresh else cache.read_edgar_raw(t)
            if raw is not None:                            # the slim companyfacts is still here: re-derive, no call
                try:
                    cache.write_edgar(t, extract(raw))
                except _UNREADABLE as ex:
                    self._record(t, f"cached EDGAR facts unreadable: {ex!r}")
                continue
            try:
                facts = self._edgar.company_facts(int(self._names[t]["cik"]))
                fetched = True
            except FetchError as ex:
                if refresh and cache.read_edgar(t) is not None:
                    kept.append(t)
                    continue
                self._record(t, f"EDGAR fetch failed: {ex}")
                continue
            # A payload that parses as JSON but is not shaped like companyfacts (a list where the
            # units go, a string for a value) is this ticker's failure, not the run's: it is
            # recorded, nothing is written, and the ticker is refetched next time.
            try:
                slimmed, extracted = slim(facts), extract(facts)
            except _UNREADABLE as ex:
                self._record(t, f"EDGAR companyfacts unreadable: {ex!r}")
                continue
            cache.write_edgar_raw(t, slimmed)
            cache.write_edgar(t, extracted)

        priced_now: set[str] = set()
        for t in missing_prices:
            try:
                cache.write_prices(t, month_end_closes(self._prices.daily_closes(t), self.as_of))
                try:
                    cache.write_splits(t, self._prices.splits(t))
                except Exception:  # noqa: BLE001 — a provider without split events is not an error
                    pass
                fetched = True
                priced_now.add(t)
            except LiveFeedError as ex:
                if refresh and cache.read_prices(t) is not None:
                    kept.append(t)
                    continue
                # the line already starts with the ticker: drop the provider's symbol prefix so a
                # source-wide failure reads identically on every ticker and collapses to one finding
                msg, sym = str(ex), self._prices.symbol_for(t)
                if msg.startswith(f"{sym}: "):
                    msg = msg[len(sym) + 2:]
                msg = f"price fetch failed ({self.price_source}): {msg}"
                # do not overwrite an EDGAR-side message for the same ticker; keep the first
                if t not in self._ticker_errors:
                    self._record(t, msg)
                else:
                    self.errors.append(f"{t}: {msg}")

        price_source_written = self.price_source
        if stale_prices:
            if priced_now:                                  # the new source answered: nothing of the old one survives
                cache.prune_prices(priced_now)
            else:                                           # it answered for nobody: the old half stays as it was
                price_source_written = cache.price_source() or self.price_source
        self.fetched_any = fetched
        if kept:
            names = sorted(set(kept))
            self.errors.append(f"{len(names)} of {len(fetchable)} names could not be refetched; their saved feed serves instead "
                               f"[{', '.join(names)}]")
        if fetched:
            meta = cache.write_meta(user_agent=self._edgar.user_agent, baskets_sha256=baskets.sha256,
                                    price_source=price_source_written)
            self.fetched_at = meta["fetched_at"]
        else:
            meta = cache.read_meta()
            self.fetched_at = meta.get("fetched_at") if meta else None

    def _override_moved(self, t: str) -> bool:
        ov = self.baskets.overrides.get(t)
        return ov is not None and ov.cik is not None and (self._names.get(t) or {}).get("cik") != ov.cik

    def _forget_other_filers(self, resolved: Mapping[str, Mapping[str, Any]]) -> None:
        """Drop the cached facts of a ticker whose CIK changed: they are another company's."""
        for t, row in resolved.items():
            ext = self._cache.read_edgar(t)
            cik = row.get("cik")
            if ext is not None and cik is not None and ext.get("cik") != f"{int(cik):010d}":
                self._cache.drop_edgar(t)

    # ---------------------------------------------------------------- per constituent
    def _value_constituents(self) -> None:
        for t in self.baskets.tickers:
            try:
                self._constituents[t] = self._value_one(t)
            except _UNREADABLE as ex:                       # a cache file of the wrong shape fails one name
                self._constituents[t] = self._fail(Constituent(ticker=t), f"cached market data unreadable: {ex!r}")

    def _value_one(self, t: str) -> Constituent:
        ext = self._cache.read_edgar(t)
        closes = self._cache.read_prices(t)
        splits = self._cache.read_splits(t)   # None: the cache predates split capture
        row = self._names.get(t) or {}
        c = Constituent(ticker=t, name=(ext or {}).get("name") or row.get("title"), cik=(ext or {}).get("cik"))
        if t in self._ticker_errors:
            c.error = self._ticker_errors[t]
            return c
        if ext is None:
            c.error = "no EDGAR extract in the cache"
            return c
        if closes is None:
            c.error = f"no closes in the cache ({self.price_source})"
            return c
        periods = ext.get("revenue_periods") or []
        cash, debt = ext.get("cash") or [], ext.get("debt") or []
        # v3 extracts cache every share concept and choose at the measurement date; a v2 extract
        # cached only the winner of a first-with-any-data rule, so fall back to it as one concept.
        by_concept = ext.get("shares_by_concept")
        if not by_concept:
            by_concept = {ext["shares_concept"]: ext["shares"]} if ext.get("shares_concept") and ext.get("shares") else {}
        if not periods:
            return self._fail(c, "EDGAR has no revenue periods under any known concept (foreign private issuer?)")
        if not by_concept:
            return self._fail(c, "EDGAR has no shares-outstanding facts")

        pick = shares_at(by_concept, self.as_of)
        c.shares_basis, c.shares_as_of = pick.basis, pick.as_of
        c.shares_age_days, c.shares_rejected = pick.age_days, list(pick.rejected)
        if pick.value is None:
            why = "; ".join(pick.rejected) or "no usable share count"
            return self._fail(c, f"no share count close enough to {self.as_of.isoformat()} to price a market cap — {why}")

        # Point in time: every month is valued on what had been *filed* by that month's end — the
        # revenue, share count and balance sheet a reader of the market had then — so the multiple
        # in a round month is the one the market saw when the round was priced.
        for m in self._months:
            on = min(month_end(m), self.as_of)
            # The share count is chosen *for that month*, not once for today: a 2020 market cap
            # must use the count a reader had in 2020. Choosing once at the measurement date and
            # looking it up historically silently drops every constituent that had not yet begun
            # tagging today's concept, which thins the basket in exactly the old months M-080
            # divides by — and a thin historical median is what produced 17x calibration factors.
            monthly_pick = shares_at(by_concept, on)
            px, sh = closes.get(m), monthly_pick.value
            if px is None or not sh or not _positive(px) or not _positive(sh):
                continue
            # Closes are split-adjusted to today; the share count is on the basis of the day it
            # was *filed*. Put them on one basis before multiplying — every split after the
            # filing, not after the month: a count filed in May and priced in June is still a
            # pre-split count if the split fell in between (NVDA's 10:1 of June 2024 left two
            # months at 3.5x revenue instead of 38x until the August 10-Q caught up).
            if splits is not None:
                sh *= cumulative_split_factor(splits, monthly_pick.basis_date or on)
            elif m != month_key(self.as_of):
                # No split history on file. An earlier month may sit across a split, and pricing
                # it anyway is what put Palo Alto into the October 2020 basket at 0.85x revenue
                # instead of ~6x (two splits since). Withheld until the history is fetched.
                c.months_unverified_splits += 1
                continue
            try:
                ttm, _through = RevenueHistory(periods, filed_by=on).ttm_at(on)
            except ExtractionError:
                continue
            if ttm <= 0:
                continue
            mult = (px * sh - net_cash_at(cash, debt, on, filed_by=on)) / ttm
            # A negative enterprise value is a real state (net cash above market cap) and is not
            # rejected as an input — but a negative EV/revenue is not a *comparable multiple*, so
            # it cannot sit in a median used to price a private company's revenue. The month is
            # dropped for that constituent and counted, rather than dragging the basket to zero.
            if not math.isfinite(mult):
                continue
            if mult <= 0:
                c.months_negative_ev = getattr(c, "months_negative_ev", 0) + 1
                continue
            c.monthly[m] = round(mult, 4)

        m0 = month_key(self.as_of)
        px = closes.get(m0)
        if px is None:
            return self._fail(c, f"no close in {m0} ({self.price_source})")
        if not _positive(px):
            # a close of 0 is not a price: market cap 0 and any net debt make a small positive
            # multiple that would sit in the median looking real
            return self._fail(c, f"close in {m0} is not a positive price ({px})")
        sh = pick.value
        # The measurement month is not exempt: a count filed before a split that fell earlier in
        # the quarter is still pre-split. With no split history on file it is used as filed and
        # `splits_known` says so.
        if splits is not None:
            sh *= cumulative_split_factor(splits, pick.basis_date or self.as_of)
        try:
            ttm, through = RevenueHistory(periods, filed_by=self.as_of).ttm_at(self.as_of)
        except ExtractionError as ex:
            return self._fail(c, str(ex))
        if ttm <= 0:
            return self._fail(c, f"TTM revenue through {through} is not positive ({ttm})")
        nc = net_cash_at(cash, debt, self.as_of, filed_by=self.as_of)
        c.net_cash_basis = ("cash and borrowings as filed" if (cash or debt)
                            else "no cash or borrowings under the concepts read: net cash taken as 0")
        c.status, c.error = "ok", None
        c.splits_known = splits is not None
        c.price, c.price_month, c.shares_m = px, m0, sh
        c.market_cap_musd = round(px * sh, 3)
        c.net_cash_musd, c.ttm_revenue_musd = nc, ttm
        c.revenue_through = through
        c.ev_to_revenue = round((c.market_cap_musd - nc) / ttm, 2)
        if not all(math.isfinite(v) for v in (sh, nc, ttm, c.ev_to_revenue)):
            # a cache written before values were screened can still hold NaN; it never prices
            return self._fail(c, "market cap, net cash or revenue is not a finite number")
        if c.ev_to_revenue <= 0:
            # net cash above market cap is a real state, but not a comparable multiple: the name
            # keeps its earlier months in the history and is not `ok` at the measurement date
            return self._fail(c, f"EV/revenue at {m0} is not positive ({c.ev_to_revenue}): net cash above market cap")
        return c

    def _fail(self, c: Constituent, message: str) -> Constituent:
        c.status, c.error = "error", message
        self.errors.append(f"{c.ticker}: {message}")
        return c

    # ---------------------------------------------------------------- per sector
    def _aggregate(self) -> None:
        min_c = self.baskets.defaults.min_constituents
        for sector, tickers in self.baskets.sectors.items():
            cons = [self._constituents[t] for t in tickers]
            ok = [c for c in cons if c.status == "ok"]
            if len(ok) < min_c:
                note = (f"{sector}: only {len(ok)} of {len(tickers)} constituents have data "
                        f"(min_constituents {min_c}); fixture value kept")
                self.errors.append(note)
                continue
            history: dict[str, float] = {}
            counts: dict[str, int] = {}
            for m in self._months:
                vals = [c.monthly[m] for c in cons if m in c.monthly and math.isfinite(c.monthly[m])]
                if len(vals) >= min_c:
                    history[m] = round(statistics.median(vals), 2)
                    counts[m] = len(vals)
            if month_key(self.as_of) not in history:   # cannot happen when `ok` all priced as_of; be safe
                self.errors.append(f"{sector}: no basket value for {month_key(self.as_of)}; fixture value kept")
                continue
            self._live_history[sector] = history
            self._live_counts[sector] = counts

    # ---------------------------------------------------------------- CompsProvider
    @property
    def source(self) -> str:
        return self.live_source if self.reached_live else self._fallback.source

    @property
    def sectors(self) -> list[str]:
        return sorted(set(self._fallback.sectors) | set(self.baskets.sectors))

    def is_live(self, sector: str) -> bool:
        return sector in self._live_history

    def history(self, sector: str) -> dict[str, float]:
        if sector in self._live_history:
            return dict(self._live_history[sector])
        return self._fallback.history(sector)

    def counts(self, sector: str) -> dict[str, int]:
        """How many constituents stood behind each month's basket value (empty for a fixture sector)."""
        return dict(self._live_counts.get(sector, {}))

    def constituent_history(self, sector: str) -> dict[str, dict[str, float]]:
        """Each priced name's own monthly EV/TTM revenue, for a live sector — what a re-rating is
        measured on name by name (engine/rerating.py). Empty for a fixture sector."""
        if sector not in self._live_history:
            return {}
        return {t: {m: v for m, v in self._constituents[t].monthly.items() if math.isfinite(v) and v > 0}
                for t in self.baskets.sectors.get(sector, ()) if self._constituents[t].status == "ok"}

    @property
    def priced_as_of(self) -> date | None:
        """The day the measurement month's prices were taken (the fetch date): a month not yet
        ended is priced mid-month, and every comparison with a true month-end must say so."""
        try:
            return date.fromisoformat(str(self.fetched_at or "")[:10])
        except ValueError:
            return None

    def sector_multiples(self, as_of: date) -> dict[str, SectorComp]:
        out: dict[str, SectorComp] = {}
        for sector in self.sectors:
            obs = latest_at_or_before(self.history(sector), as_of)
            if obs is None:
                continue
            src = self.live_source if sector in self._live_history else self._fallback.source
            out[sector] = SectorComp(sector=sector, ev_to_arr=obs[1], as_of=as_of, source=f"{src}@{obs[0]}")
        return out

    # ---------------------------------------------------------------- report
    def _sector_report(self, sector: str) -> dict[str, Any]:
        n = self.baskets.defaults.months_of_history
        live = sector in self._live_history
        history = trim_history(self.history(sector), self.as_of, n)
        obs = latest_at_or_before(history, self.as_of)
        month = obs[0] if obs else None
        prior, change = qoq(history, month) if month else (None, None)
        if sector in self.baskets.sectors:
            cons = [self._constituents[t].as_json() for t in self.baskets.sectors[sector]]
        else:
            cons = [fixture_constituent(t) for t in self._fallback.sample_constituents(sector)]
        src = self.live_source if live else FIXTURE_SOURCE_PREFIX
        return {
            "sector": sector, "positions": 0,
            "ev_to_revenue": obs[1] if obs else None, "as_of_month": month,
            "source": f"{src}@{month}" if month else src, "live": live,
            "prior_quarter": prior, "qoq_pct": change,
            "history": history, "counts": {m: n for m, n in self._live_counts.get(sector, {}).items() if m in history},
            "constituents": cons,
        }

    def report(self, *, positions: Mapping[str, int] | None = None, used_by: Mapping[str, Any] | None = None,
               provider: str = "live") -> dict[str, Any]:
        """The `/api/market` body (docs/market-feed.md §3). The sector detail is built once;
        `positions` (from the snapshot) and `used_by` (from the policy) decorate it."""
        if self._report is None:
            self._report = {
                "provider": provider, "source": self.live_source if self.reached_live else "stub",   # the manifest label
                "reached_live": self.reached_live,
                "as_of": self.as_of.isoformat(), "priced_as_of": self.as_of.isoformat(),
                "valuation_date": self.valuation_date.isoformat(), "fetched_at": self.fetched_at,
                "cache": {"dir": self._cache.rel_dir, "hit": self.cache_hit, "refreshable": True},
                "used_by": dict(used_by or {}), "baskets_file": BASKETS_FILE.as_posix(),
                "errors": collapse_errors(self.errors), "sectors": [self._sector_report(s) for s in self.sectors],
            }
        rep = dict(self._report)
        rep["provider"] = provider
        rep["used_by"] = dict(used_by or rep["used_by"])
        sectors = [dict(s, positions=int((positions or {}).get(s["sector"], 0))) for s in rep["sectors"]]
        rep["sectors"] = sorted(sectors, key=lambda s: (-s["positions"], s["sector"]))
        return rep

    def diagnostics(self) -> dict[str, Any]:
        return {"reached_live": self.reached_live, "cache_hit": self.cache_hit, "errors": list(self.errors),
                "live_sectors": sorted(self._live_history)}


# ---------------------------------------------------------------- the stub-shaped report

def stub_market_report(stub: StubCompsProvider, as_of: date, *, positions: Mapping[str, int] | None = None,
                       used_by: Mapping[str, Any] | None = None, provider: str = "stub",
                       errors: list[str] | None = None, months_of_history: int | None = None) -> dict[str, Any]:
    """The same §3 shape when the fixture answers: `reached_live` false, no cache, every sector
    `live: false` with the fixture's `sampleConstituents` as status-`fixture` rows."""
    sectors = []
    for sector in stub.sectors:
        history = trim_history(stub.history(sector), as_of, months_of_history)
        obs = latest_at_or_before(history, as_of)
        month = obs[0] if obs else None
        prior, change = qoq(history, month) if month else (None, None)
        sectors.append({
            "sector": sector, "positions": int((positions or {}).get(sector, 0)),
            "ev_to_revenue": obs[1] if obs else None, "as_of_month": month,
            "source": f"{FIXTURE_SOURCE_PREFIX}@{month}" if month else FIXTURE_SOURCE_PREFIX, "live": False,
            "prior_quarter": prior, "qoq_pct": change, "history": history, "counts": {},
            "constituents": [fixture_constituent(t) for t in stub.sample_constituents(sector)],
        })
    return {
        "provider": provider, "source": "stub", "reached_live": False, "as_of": as_of.isoformat(),
        "priced_as_of": as_of.isoformat(), "valuation_date": as_of.isoformat(),
        "fetched_at": None, "cache": None, "used_by": dict(used_by or {}), "baskets_file": BASKETS_FILE.as_posix(),
        "errors": list(errors or []), "sectors": sorted(sectors, key=lambda s: (-s["positions"], s["sector"])),
    }


__all__ = ["COLLAPSE_AT", "LIVE_SOURCE_PREFIX", "PRICE_SOURCE_ENV", "LiveFeedError", "PublicCompsProvider",
           "collapse_errors", "live_source", "month_end_closes", "months_back", "stub_market_report", "trim_history"]
