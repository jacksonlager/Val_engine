# Market feed — one live, free data source through the data layer

This is the contract for the live public-comps feed: what it reads, what it computes,
where it is cached, how it degrades, and the exact JSON the review tool renders. The
engine is untouched by any of it — it still receives an already-fetched `MarketData`
value object and never learns where the numbers came from.

## 1. Why this source

The engine's one external input that is *market* data is the sector public-comparable
multiple (`MarketData.comps[sector].ev_to_arr` plus a monthly history). It feeds the
mark-vs-performance screens (X-401/X-402 in `relative_to_comps` mode) and the M-080
calibration alternative. That slot is shaped like a PitchBook "Public Comps" export.

The free source that fills it honestly is two keyless, official-or-stable endpoints — SEC
EDGAR for fundamentals and a pluggable price source (Yahoo Finance's chart API by default):

| Piece | Source | What it gives | Terms |
|---|---|---|---|
| Fundamentals | **SEC EDGAR XBRL API** `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | every reported value of every US-GAAP concept for one filer, with period, fiscal year/period, form and a `frame` (`CY2026Q1`) that de-duplicates restatements | free, no key; requires a `User-Agent` naming the app and a contact e-mail; ≤ 10 requests/s |
| Ticker → CIK | `https://www.sec.gov/files/company_tickers.json` | `{ "0": {"cik_str": 1321655, "ticker": "PLTR", "title": "Palantir Technologies Inc."}, … }` | same |
| Prices (default) | **Yahoo Finance chart API** `https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?range=4y&interval=1d` | JSON: `chart.result[0].timestamp[]` (unix) + `indicators.quote[0].close[]` (null on holidays), `chart.error` on an unknown/delisted symbol. Undocumented but stable for years — it is what `yfinance` reads | free, no key; browser-like `User-Agent`, ≤ 2 requests/s |
| Prices (alternative) | **Stooq** `https://stooq.com/q/d/l/?s=<ticker>.us&i=d` | daily `Date,Open,High,Low,Close,Volume` CSV, full history, no envelope | free, no key. **Currently serves a JavaScript browser-verification page (HTTP 404) to non-browser clients**; the feed detects and reports that, and does not try to bypass it |

Per constituent, per month-end: `EV = close × shares_outstanding − net_cash`,
`EV/Revenue = EV / TTM revenue`. Per sector: the median across the basket. The result
is a real, dated EV/TTM-revenue multiple per portfolio sector with a monthly history —
the same field PitchBook's `evToNtmRevenue.median` carries (NTM vs TTM is noted in the
source label; it is a policy choice, not a code one).

## 2. Files

```
rules/comps_baskets.yaml                 which public names stand for each workbook sector (policy-adjacent, reviewed)
src/hc_valuation/connectors/edgar.py     EDGAR client + fundamentals extraction (pure functions over the JSON)
src/hc_valuation/connectors/prices.py    PriceProvider Protocol, YahooPrices (default), StooqPrices, month-end closes
src/hc_valuation/connectors/stooq.py     thin module keeping the earlier Stooq function names over StooqPrices
src/hc_valuation/connectors/fetch.py     the one HTTP seam: short status errors, browser-challenge detection
src/hc_valuation/connectors/live.py      PublicCompsProvider: baskets × fundamentals × prices -> SectorComp + history
src/hc_valuation/connectors/cache.py     on-disk cache under data/market_cache/<as_of>/
data/market_cache/<as_of>/               trimmed extracts, small enough to commit (see §5)
tests/fixtures/market/                   recorded samples used by the offline tests
```

### 2.1 `rules/comps_baskets.yaml`

```yaml
version: 1
note: >
  Public companies whose EV/revenue multiple stands in for each workbook Sector. Chosen for
  business-model similarity, US filers (10-K/10-Q, so EDGAR carries their facts), and a
  liquid US listing the price source can quote. Changing a basket is a policy change: record
  why in the commit message — including a ticker swap forced by the market rather than by
  policy (a delisting, a take-private, a rename such as SQ -> XYZ).
defaults:
  months_of_history: 36
  min_constituents: 3          # fewer than this with data -> sector falls back to the fixture
  price_source: yahoo          # yahoo | stooq  (--price-source / HC_PRICE_SOURCE override per run)
  price_max_per_s: 2           # polite request rate against the price source
sectors:
  "AI/ML":            [PLTR, AI, SOUN, BBAI, NVDA]
  "Developer Tools":  [GTLB, DDOG, MDB, NET, TEAM]
  "Enterprise SaaS":  [CRM, NOW, WDAY, HUBS, ADBE]
  "Fintech":          [XYZ, PYPL, AFRM, TOST, SOFI]
  "Cybersecurity":    [CRWD, PANW, ZS, FTNT, OKTA]
  "Data & Analytics": [SNOW, TDC, ESTC, DDOG, PLTR]
  "Infrastructure":   [DOCN, NTNX, ANET, SMCI, NET]
  "Healthcare":       [VEEV, DOCS, TDOC, HIMS, ISRG]
  "Robotics":         [SYM, ISRG, TER, KTOS, AVAV]
  "Climate & Energy": [ENPH, FSLR, TSLA, RUN, BE]
  "Space & Defense":  [RKLB, PL, IRDM, KTOS, AVAV]
  "Consumer":         [ABNB, DASH, UBER, DUOL, SPOT]
overrides: {}                  # optional per-ticker fixes, e.g. T: { cik: 123, name: "..." }
```

Tickers may appear in more than one basket. A ticker EDGAR cannot resolve, or whose facts
lack a usable revenue series, is reported as `status: error` on that constituent and the
sector median is taken over the rest; below `min_constituents` the sector keeps the fixture
value and says so. Tickers are SEC symbols (`BRK.B`); each price provider maps them to its
own form. A symbol the market retires (Block: `SQ` → `XYZ` in 2025; Confluent taken private)
is swapped in the baskets file, with the reason in the commit message — an override can pin
a CIK for EDGAR, but no price source answers for a ticker that no longer trades.

### 2.2 Fundamentals extraction (`edgar.py`, pure functions, fully unit-tested on recorded JSON)

* **Revenue, quarterly**: the first concept, in order, that yields at least one quarterly
  value (a concept that is present but carries only annual frames is skipped) —
  `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet`,
  `RevenueFromContractWithCustomerIncludingAssessedTax`. Take `units.USD` entries whose
  `frame` matches `CY\d{4}Q[1-4]` (quarterly, de-duplicated by SEC). A calendar Q4 that has
  no quarterly frame is derived as annual frame `CY\d{4}` minus the three quarterly frames
  of that year when all three exist. **TTM at a quarter end** = sum of the last four
  quarterly values; undefined (constituent `status: error`) if any of the four is missing.
* **Shares outstanding**: `dei.EntityCommonStockSharesOutstanding` (`units.shares`), the
  latest entry whose `end` ≤ the month being valued; fallback
  `us-gaap.CommonStockSharesOutstanding`, then `WeightedAverageNumberOfDilutedSharesOutstanding`.
  Multi-class filers report several rows with the same `end` — sum rows that share an `end`
  and `fy/fp` (Alphabet-style); document this in the module.
* **Net cash** = (`CashAndCashEquivalentsAtCarryingValue` + `ShortTermInvestments` if present,
  else `MarketableSecuritiesCurrent` if present) − (`LongTermDebt` if present, else
  `LongTermDebtNoncurrent` + `LongTermDebtCurrent`, each 0 when absent). Latest `end` ≤ month.
  Approximation, labelled as such.
* Everything is USD millions once extracted (EDGAR reports raw USD). Round to 3 dp.

### 2.3 Prices (`prices.py`)

```python
class PriceProvider(Protocol):
    name: str                                            # "yahoo" | "stooq" — the label and the cache key
    def symbol_for(self, ticker: str) -> str: ...        # SEC ticker -> the provider's symbol
    def daily_closes(self, ticker: str) -> dict[str, float]: ...   # YYYY-MM-DD -> close; LiveFeedError on failure

price_provider(name, *, fetch_text=None, timeout_s=8.0, max_per_s=None) -> PriceProvider
```

* **`YahooPrices`** (default): `GET .../v8/finance/chart/<symbol>?range=4y&interval=1d` with
  `User-Agent: Mozilla/5.0 (compatible; hc-valuation/<version>)` and `Accept: application/json`.
  Reads `chart.result[0]`: `timestamp[i]` (unix, converted to an ISO date in UTC — Yahoo
  stamps the session open, so the UTC date is the trading date for a US listing) paired with
  `indicators.quote[0].close[i]`; a `null` close (a holiday row) is skipped. `chart.error`
  non-null or an empty result is a `LiveFeedError` naming the symbol and the error's
  `description` (`"No data found, symbol may be delisted"`). Symbol: `BRK.B` → `BRK-B`.
* **`StooqPrices`**: the CSV endpoint as before; symbol `<ticker lower>.us`. Retained as
  `--price-source stooq`, but the host currently answers non-browser clients with a
  browser-verification page (see §2.7).
* Each provider is rate-limited (`MAX_PER_S = 2` on the class; `defaults.price_max_per_s`
  in the baskets file overrides it). `fetch_text` is the test seam, as everywhere.

`month_end_closes(daily, as_of)` → `{YYYY-MM: close}`. A month is valued at its **last
available close**. The measurement-date month uses the last close ≤ the measurement date (a
run for 2026-09-30 executed on 2026-10-15 must not read October prices — filter by `as_of`
before taking the month end).

Selection: the `price_source` constructor kwarg (from `--price-source`), else
`HC_PRICE_SOURCE`, else `defaults.price_source`. An unknown name is an error the assembler
reports and falls back from — it never stops a run.

### 2.4 Provider (`live.py`)

```python
class PublicCompsProvider:          # implements CompsProvider (base.py) — unchanged Protocol
    def __init__(self, baskets: Baskets, fallback: CompsProvider, cache: MarketCache,
                 as_of: date, *, refresh: bool = False, timeout_s: float = 8.0,
                 price_source: str | None = None, price_max_per_s: float | None = None) -> None: ...
    reached_live: bool              # at least one sector computed from live data
    price_source: str               # the provider that answered ("yahoo" | "stooq")
    source: str                     # "live:edgar+<price_source>" or the fallback's label
    def sector_multiples(self, as_of: date) -> dict[str, SectorComp]: ...
    def history(self, sector: str) -> dict[str, float]: ...
    def report(self) -> dict        # the /api/market payload body (§3), built once
```

`SectorComp.source` is `live:edgar+yahoo@YYYY-MM` (or `+stooq`) for a live month and the
fixture label otherwise. The label is computed from the price provider's `name`, never a
constant. `assemble_market_data(..., provider="live", price_source=None)` uses this class;
the manifest label becomes `live:edgar+<price source>` when `reached_live`, else `stub` —
never a live label over fixture numbers. `provider="stooq"` stays an alias of `live` (it
selects the *provider*, not the price source).

Errors are recorded per constituent (`constituents[].error` keeps the full text). In the
report's `errors[]`, ticker lines that share a message — the tail after `TICKER: ` — are
collapsed once **3 or more** tickers carry it: `"55 tickers: price fetch failed (stooq):
stooq.com answered with a browser-verification page; … [PLTR, AI, …]"`, so a source-wide
outage reads as one finding. Sector notes and lone ticker lines pass through unchanged.

### 2.5 Cache (`cache.py`)

`data/market_cache/<as_of ISO date>/` holds **trimmed extracts, not raw payloads**:

```
meta.json                        {"fetched_at": iso, "as_of": "...", "user_agent": "...", "baskets_sha256": "...", "price_source": "yahoo"}
company_tickers.json             ticker -> {cik, title}, only the tickers in the baskets
edgar/<TICKER>.json              {"cik", "name", "revenue_quarterly": {"CY2026Q2": musd, ...}, "shares": [{"end", "value"}], "cash": [...], "debt": [...]}
prices/<TICKER>.json             {"YYYY-MM": close}  (month-end closes only, ≤ as_of; written by meta.price_source)
```

Rules: with a cache present for `as_of`, the live provider reads it and makes **no network
call** (a re-run is deterministic and works offline); `--refresh` refetches and overwrites;
a partial cache (a ticker missing) fetches only what is missing; a ticker SEC does not know
is recorded in `company_tickers.json` as `cik: null`, reported as an error on every run,
and never refetched (nothing can be priced without fundamentals). The price half is keyed by
the provider that wrote it: a run whose price source differs from `meta.price_source` treats
every cached close as missing and refetches **prices only** (the EDGAR half stays a hit);
once the new provider has answered for at least one ticker, whatever the old one wrote is
pruned and `meta.price_source` moves — if it answered for nobody (an outage), the old half
and its label stay untouched and the run reports the failures. The cache directory is small
(tens of KB) and is committed after a real run so a reviewer gets live-shaped data without a
network. `.gitignore` is not changed.

### 2.6 Transport errors and bot challenges (`fetch.py`)

`fetch_text` is the only place HTTP happens. It raises `FetchError` with one short line:
a transport failure as `ConnectError: …` (httpx's "For more information check:
https://developer.mozilla.org/…" trailer is dropped), a status as `HTTP 404 for <url>`, and
— checked **before** the status, because Stooq serves it with 404 — a body that is HTML
(`<!doctype html` / `<html` in the first 200 characters) and mentions *verify*, *JavaScript*
or *challenge* as `<host> answered with a browser-verification page; this source cannot be
read by an automated client`. That is the honest end of the road for that source: the feed
does not solve proof-of-work pages, replay cookies or spoof a browser beyond a plain
`User-Agent`. Switch price source (`--price-source`) or wait.

### 2.7 Fallback and honesty

Any network, parse, or arithmetic failure is caught **per constituent**, recorded in the
report, and never raised past the provider. If no sector reaches `min_constituents`,
`reached_live` is false, the fixture answers, the manifest says `stub`, and the report
carries the errors. Nothing in `engine/` changes. `pytest` must pass with no network:
every test uses `tests/fixtures/market/` recordings or a temp cache.

## 3. `GET /api/market` — the contract the review tool renders

```jsonc
{
  "provider": "live",                          // "live" | "stub" — what was asked for
  "source": "live:edgar+yahoo",                // what actually answered (manifest label): live:edgar+<price source> | stub
  "reached_live": true,
  "as_of": "2026-09-30",                       // measurement date
  "fetched_at": "2026-09-04T06:12:40Z",        // null when the fixture answered
  "cache": { "dir": "data/market_cache/2026-09-30", "hit": true, "refreshable": true },
  "used_by": { "multiple_mode": "absolute", "calibration_enabled": false,
               "note": "Screens X-401/X-402 use absolute thresholds under this policy; set exceptions.multiple.mode: relative_to_comps to screen against these multiples." },
  "baskets_file": "rules/comps_baskets.yaml",
  "errors": [ "TEAM: EDGAR has no quarterly revenue frames (foreign private issuer?)",
              "3 tickers: price fetch failed (yahoo): HTTP 429 for … [AI, BBAI, SOUN]" ],   // ≥ 3 identical ticker failures collapse
  "sectors": [
    {
      "sector": "AI/ML",
      "positions": 18,                         // portfolio companies in this sector
      "ev_to_revenue": 22.71,                  // the value in force at as_of
      "as_of_month": "2026-09",
      "source": "live:edgar+yahoo@2026-09",    // or "fixture:pitchbook@2026-09"
      "live": true,
      "prior_quarter": 21.10,                  // value three months earlier, null if unknown
      "qoq_pct": 0.076,                        // null if unknown
      "history": { "2023-10": 18.2, "...": 0, "2026-09": 22.71 },   // ≤ 36 months, ascending keys
      "constituents": [
        { "ticker": "PLTR", "name": "Palantir Technologies Inc.", "cik": "0001321655", "status": "ok",
          "price": 41.20, "price_month": "2026-09", "shares_m": 2270.0, "market_cap_musd": 93524.0,
          "net_cash_musd": 4100.0, "ttm_revenue_musd": 3350.0, "revenue_through": "2026-06-30",
          "ev_to_revenue": 26.69, "error": null },
        { "ticker": "TEAM", "name": "Atlassian Corp", "cik": "0001650372", "status": "error",
          "price": null, "price_month": null, "shares_m": null, "market_cap_musd": null,
          "net_cash_musd": null, "ttm_revenue_musd": null, "revenue_through": null,
          "ev_to_revenue": null, "error": "no quarterly revenue frames" }
      ]
    }
  ]
}
```

Sort `sectors` by `positions` descending, then name. In the **stub** case the same shape is
returned with `provider: "stub"`, `reached_live: false`, `fetched_at: null`, `cache: null`,
`live: false` on every sector, `source: "fixture:pitchbook@…"`, and `constituents` taken
from the fixture's `sampleConstituents` (status `"fixture"`, numeric fields null).

Static export (`hc-valuation build`) inlines the same object as `window.__HC_MARKET__`
next to `__HC_RUN__`, so the Market panel works in the exported report.

## 4. CLI

`hc-valuation market [--provider live|stub] [--price-source yahoo|stooq] [--refresh] [--json]`
prints one line per sector (multiple, source, month, constituents ok/total) followed by the
errors block in its collapsed form, and exits 0 even when the fixture answered (the fallback
is a reported condition, not a failure). `--json` dumps the §3 payload. `hc-valuation
run/build --refresh-market` forces a refetch; those commands take the price source from
`HC_PRICE_SOURCE` (else the baskets default).

## 5. Replacing it with PitchBook (or anything else)

A vendor connector is one class implementing `CompsProvider` (`base.py`) and one
`register_comps_provider(name, factory)` call in `connectors/__init__.py` — providers are a
registry of factories keyed by name, and `assemble_market_data` looks the name up rather
than branching on it. `StubCompsProvider` already parses the PitchBook-shaped payload
in `data/mock_responses/pitchbook/comps_software.json`; a real client only has to fetch
that shape with credentials and hand it to the same parser. Registered names are
`stub | live | pitchbook` (the last answering with a clear "not configured" until keys exist).
The report (§3) is provider-agnostic: `constituents[]` may be empty and `source` says
who answered. The engine, the policy file, the golden test and the review tool do not
change.

**Price source is pluggable.** Inside the live provider the price half is its own seam:
`PriceProvider` in `prices.py` (`name`, `symbol_for`, `daily_closes`), chosen by
`--price-source` / `HC_PRICE_SOURCE` / `defaults.price_source`. Adding one is a class with
those three members and an entry in `price_provider()`; the label (`live:edgar+<name>`), the
cache key (`meta.price_source`) and the error text follow from `name`. Yahoo is the default
because it answers automated clients today; Stooq stays selectable so the day it lifts its
browser check nothing but a flag changes.
