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
| Fundamentals | **SEC EDGAR XBRL API** `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | every reported value of every US-GAAP concept for one filer, with period (`start`/`end`), fiscal year/period, form and filing date; the calendar `frame` SEC adds is not used here | free, no key; requires a `User-Agent` naming the app and a contact e-mail; ≤ 10 requests/s |
| Ticker → CIK | `https://www.sec.gov/files/company_tickers.json` | `{ "0": {"cik_str": 1321655, "ticker": "PLTR", "title": "Palantir Technologies Inc."}, … }` | same |
| Prices (default) | **Yahoo Finance chart API** `https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?range=10y&interval=1d&events=split` | JSON: `chart.result[0].timestamp[]` (unix) + `indicators.quote[0].close[]` (null on holidays), `events.splits` (the split history the closes are adjusted for), `chart.error` on an unknown/delisted symbol. Undocumented but stable for years — it is what `yfinance` reads | free, no key; browser-like `User-Agent`, ≤ 2 requests/s |
| Prices (alternative) | **Stooq** `https://stooq.com/q/d/l/?s=<ticker>.us&i=d` | daily `Date,Open,High,Low,Close,Volume` CSV, full history, no envelope | free, no key. **Currently serves a JavaScript browser-verification page (HTTP 404) to non-browser clients**; the feed detects and reports that, and does not try to bypass it |

Per constituent, per month-end: `EV = close × shares_outstanding − net_cash`,
`EV/Revenue = EV / TTM revenue`, with the share count first carried onto the close's split
basis (§2.3). Per sector: the median across the basket, over the constituent-months whose
multiple is positive (§2.4). The result is a real, dated EV/TTM-revenue multiple per
portfolio sector with a monthly history — the same field PitchBook's
`evToNtmRevenue.median` carries (NTM vs TTM is noted in the source label; it is a policy
choice, not a code one).

Three inputs are refused rather than used when they cannot be trusted, and each refusal is
counted on the constituent and given a reason: a share count the filer stopped reporting
more than 450 days before the date being valued (§2.2), a month whose close and share count
sit on different sides of a split with no split history on file to reconcile them (§2.3),
and a month whose enterprise value is negative (§2.4). A constituent left unpriced with a
stated reason is a better answer than a market cap built on a count from a capital structure
that no longer exists.

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
  months_of_history: 96         # 8 years: reaches the round months of the book's stale positions (M-080)
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
  "Consumer":         [ABNB, DASH, UBER, DUOL, RBLX]   # RBLX replaced SPOT: Spotify files 20-F under IFRS
overrides: {}                  # optional per-ticker fixes, e.g. T: { cik: 123, name: "..." }
```

Tickers may appear in more than one basket. A ticker EDGAR cannot resolve, or whose facts
lack a usable revenue series or a share count recent enough to price on (§2.2), is
reported as `status: error` on that constituent and the
sector median is taken over the rest; below `min_constituents` the sector keeps the fixture
value and says so. Tickers are SEC symbols (`BRK.B`); each price provider maps them to its
own form. A symbol the market retires (Block: `SQ` → `XYZ` in 2025; Confluent taken private)
is swapped in the baskets file, with the reason in the commit message — an override can pin
a CIK for EDGAR, but no price source answers for a ticker that no longer trades.

### 2.2 Fundamentals extraction (`edgar.py`, pure functions, fully unit-tested on recorded JSON)

* **Revenue periods** (`revenue_periods`): every `units.USD` entry of **every** revenue concept —
  `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet`,
  `RevenueFromContractWithCustomerIncludingAssessedTax` — read by its own `start`/`end`, never
  by SEC's calendar `frame`. Two things the first version got wrong and this one does not:
  (1) filers switch concepts (NVIDIA and SoundHound moved from `Revenues` to the ASC 606 tag
  in 2018–2020), so reading one concept left a history that stopped in 2019 and a 505× multiple;
  the concepts are merged, the one whose history runs latest winning any period both report;
  (2) `frame` is calendar-aligned, so a fiscal year ending in January (NVIDIA, Salesforce,
  Snowflake, CrowdStrike) or April (C3.ai, Elastic, AeroVironment) had quarters mis-assigned or
  dropped, hence "TTM undefined: missing CY2025Q1". Only period lengths that mean something
  are kept (a quarter 80–100 days, a half, nine months, a year); the latest `filed` value per
  period wins (restatements).
* **Point in time.** Every month of the history is valued on what had been *filed* by that month's end: `revenue_periods` keeps one row per distinct value a period was reported at (a restatement is a second row with a later `filed`), the instant series do the same per `end`, and `RevenueHistory(filed_by=…)` / `value_at(filed_by=…)` read the figure as filed. The as-of valuation is the same read at the measurement date. So a round-month multiple is the one the market saw then; a 10-K that restates a quarter changes only the months after it was filed.
* **TTM at a date** (`RevenueHistory.ttm_at`): quarters are the reported quarter-length
  periods plus quarters derived by differencing year-to-date periods that share a start
  (fiscal Q4 = year − nine months). Route 1: the latest quarter ended on or before the date
  with three consecutive predecessors (each 80–100 days apart) → their sum. Route 2, when a
  quarter is missing: latest fiscal year + year-to-date since it − the same year-to-date a year
  earlier (a year with no later filing is the year). `revenue_through` is the period end the
  TTM runs to. Undefined only when neither route can be built.
* **Shares outstanding** (`shares_at`): three concepts are read (`units.shares`), in
  preference order — `dei.EntityCommonStockSharesOutstanding` (basis *outstanding, cover
  page*), `us-gaap.CommonStockSharesOutstanding` (*outstanding, balance sheet*), then
  `us-gaap.WeightedAverageNumberOfDilutedSharesOutstanding` (*diluted weighted average*: a
  period average rather than a count at a date, close to outstanding for these filers — SNOW
  352.8 vs 348.7, RBLX 714.3 vs 715.5, NVDA 24,100 vs 24,312 — and labelled as an
  approximation, so it is the last resort rather than an equal), and finally
  `us-gaap.WeightedAverageNumberOfShareOutstandingBasicAndDiluted` — the same basis, tagged
  that way by a loss-making filer with no dilution to report (C3.ai through fiscal 2022;
  without it the dead 3.5M balance-sheet tag was the only count on file for a year). A cache
  fetched before this concept was read lacks it in `edgar_raw/`, so those months stay as they
  were until `market --provider live --refresh`. The extract keeps the whole
  series of every concept the filer has ever tagged (`shares_by_concept`; `EXTRACT_VERSION` 3,
  an older extract is re-derived from the slim facts), and the choice is made at read time
  for the date being valued: the first concept whose latest fact filed on or before that date
  is **positive** and **no more than `SHARES_MAX_AGE_DAYS` (450 days) old** wins.

  The age test exists because EDGAR keeps a concept's history after the filer stops
  reporting it, and the earlier rule — the first concept with any data — read those abandoned
  tags as current. C3.ai was priced on 3.5M shares last tagged in April 2021 against ~140M
  today, a 40× understatement of its market cap; SoundHound on the 17.5M shares of its
  pre-merger shell against ~439M (~25×); Hims, Datadog and Toast on a final value of zero.
  Nine of the 54 constituents were affected, the stale ones by 4.6 to 7.8 years. Fifteen
  months covers a filer who has missed a quarter, not one who has moved on.

  The absolute limit is not enough on its own: a dropped tag stays inside it for up to
  fifteen months after its last value, and in that window preference order would still take
  it over the concept the filer has moved to. Affirm carried its 59M pre-listing balance-sheet
  count for a year after its IPO against a diluted average of 230–280M; SoundHound its 17.5M
  shell count for ten months against 160–200M; C3.ai's 3.5M made its enterprise value
  negative for thirteen months. So every qualifying concept is also judged against the
  filer's **freshest** concept — the one it is actually keeping up. In step by date (no more
  than `SHARES_LAG_DAYS`, 135 days, behind it) the value must be within `SHARES_RATIO_BAND`
  (0.5×–2×) of the freshest value; behind by more than that it must be within the tighter
  `SHARES_STALE_BAND` (0.9×–1.1×). Outstanding and diluted-average counts differ by percent,
  not multiples, so the wide band separates a different share base from an ordinary one, and
  the tight band separates a concept the filer merely reports annually — behind by date, but
  still agreeing — from a tag nobody updates. Both refusals are recorded like the others
  (*"…: last filed 2021-03-31, 275 days behind WeightedAverageNumberOfDilutedSharesOutstanding
  (2021-12-31) and 0.23x its 258.0M — the filer has moved on"*, *"…: 17.5M is 0.11x the 162.0M
  under … — not the same share base"*).

  The pick is recorded (`SharesPick`): the `basis`, the fact's `end` (`shares_as_of`), its
  age in days at the date valued (`shares_age_days`), and one line per concept passed over
  with the reason (`shares_rejected`: *"CommonStockSharesOutstanding: last filed 2021-04-30,
  5.4 years before the measurement date"*, *"…: last value is 0 (2019-12-31)"*, *"…: nothing
  filed on or before 2020-10-31"*), so a refusal is visible rather than inferred. When no
  concept qualifies the constituent goes **unpriced with that list as its error** — a real
  answer, where a 2026 market cap on a 2021 share count is not. Each historical month makes
  its own pick, so a 2020 market cap uses the count a reader had in 2020 and a constituent
  that had not yet begun tagging today's concept is not dropped from the old months M-080
  divides by.

  Multi-class filers report several rows with the same `end`: rows sharing `end`, `fy/fp` and
  `filed` are summed (Alphabet-style), except that a row equal to the sum of the others is the
  filer's own total and is taken as such rather than double-counted.
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
    def splits(self, ticker: str) -> dict[str, float]: ...         # YYYY-MM-DD -> ratio (3-for-1 is 3.0); {} when the provider has none

price_provider(name, *, fetch_text=None, timeout_s=8.0, max_per_s=None) -> PriceProvider
```

* **`YahooPrices`** (default): `GET .../v8/finance/chart/<symbol>?range=10y&interval=1d&events=split`
  with `User-Agent: Mozilla/5.0 (compatible; hc-valuation/<version>)` and `Accept: application/json`.
  Reads `chart.result[0]`: `timestamp[i]` (unix, converted to an ISO date in UTC — Yahoo
  stamps the session open, so the UTC date is the trading date for a US listing) paired with
  `indicators.quote[0].close[i]`; a `null` close (a holiday row) is skipped. `chart.error`
  non-null or an empty result is a `LiveFeedError` naming the symbol and the error's
  `description` (`"No data found, symbol may be delisted"`). Symbol: `BRK.B` → `BRK-B`.
  `splits()` reads `events.splits` (`numerator`/`denominator`, `parse_yahoo_splits`) from
  the same payload — one response per ticker per run serves both, so the split history costs
  no extra request.
* **`StooqPrices`**: the CSV endpoint as before; symbol `<ticker lower>.us`. Retained as
  `--price-source stooq`, but the host currently answers non-browser clients with a
  browser-verification page (see §2.7). It carries no split events, so `splits()` is empty
  and every month before the measurement month goes unverified (below).

**Split basis.** The two halves of a market cap come from sources on different bases. A
close from the price source is adjusted for every split since, so the whole series reads in
today's shares; an EDGAR share count is on the basis of the day it was *filed* and is never
restated. Multiply one by the other and every month before a split understates the market
cap by the splits since: Palo Alto entered the October 2020 Cybersecurity basket at 0.85×
revenue against a true ~6×, a sixth of the figure across its 3-for-1 of September 2022 and
2-for-1 of December 2024 — and a five-name basket does not absorb an entry that wrong.
`cumulative_split_factor(splits, basis_date)` is the product of every split ratio dated
strictly after the count's filing date (`SharesPick.basis_date`) — how many of today's shares
one share on that filing's basis has become — and the as-filed count is multiplied by it
before the market cap is formed, month by month. The filing date, not the month being priced,
is what matters: a count filed in May and used for June is still pre-split if the split fell
between them (a filing made after a split already reports post-split shares, SAB Topic 4C).
Applying the factor from the month end instead left NVIDIA at 3.5× revenue for the two months
after its June 2024 10-for-1, until the August 10-Q caught up. The measurement month is not
exempt. A filer with no splits has a factor of 1.0 everywhere.

A month for which no split history is on file is **withheld and counted**
(`months_unverified_splits`), not priced on two bases. The measurement month needs no
history — nothing can have split after it — so it prices in every case; every earlier month
does not. The constituent reports `splits_known` so the reader can tell an empty history
that means "verified, no splits" from one that means "nothing on file". No split history is
the state of a price provider that cannot supply one, and of a cache written before split
capture (§2.5).
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

Per constituent the provider runs the month loop (§1) and then the measurement-date
valuation, and records on the `Constituent` what it chose and what it refused: `shares_basis`,
`shares_as_of`, `shares_age_days` and `shares_rejected` from the share pick at the measurement
date (§2.2); `months_negative_ev` and `months_unverified_splits`, the historical months
excluded for each reason; and `splits_known`, whether a split history was on file (§2.3). A
month excluded for one constituent is not excluded for the sector — the median is taken over
whoever priced, and `counts` (§3) says how many that was.

**Negative enterprise value.** Net cash above the market cap is a real state and its inputs
are kept — the market cap, the net cash and the revenue are all still reported on the
constituent — but a negative EV/revenue is not a comparable *multiple*. It cannot sit in a
median used to price a private company's revenue, where it drags the basket toward and past
zero. That constituent-month leaves the median and is counted in `months_negative_ev`,
rather than being silently dropped or silently included; in the committed cache 19
historical constituent-months are excluded this way. The same test applies to the
measurement month: the constituent's own `ev_to_revenue` is still reported, negative, but it
does not enter that month's median.

Errors are recorded per constituent (`constituents[].error` keeps the full text). In the
report's `errors[]`, ticker lines that share a message — the tail after `TICKER: ` — are
collapsed once **3 or more** tickers carry it: `"55 tickers: price fetch failed (stooq):
stooq.com answered with a browser-verification page; … [PLTR, AI, …]"`, so a source-wide
outage reads as one finding. Sector notes and lone ticker lines pass through unchanged.

### 2.5 Cache (`cache.py`)

`data/market_cache/<as_of ISO date>/` holds **trimmed extracts, not raw payloads** — plus,
git-ignored, the slim companyfacts each extract was derived from:

```
meta.json                        {"fetched_at": iso, "as_of": "...", "user_agent": "...", "baskets_sha256": "...", "price_source": "yahoo"}
company_tickers.json             ticker -> {cik, title}, only the tickers in the baskets
edgar/<TICKER>.json              {"extract_version": 3, "cik", "name", "revenue_concepts": [...], "revenue_periods": [{"start", "end", "value", "days", "filed"}],
                                  "shares_by_concept": {"dei:EntityCommonStockSharesOutstanding": [{"end", "value", "filed"}], ...}, "cash": [...], "debt": [...]}
                                 (`shares_concept` / `shares` — the v2 single-series fields — are still written so an older reader works)
edgar_raw/<TICKER>.json          `edgar.slim(companyfacts)`: only the concepts read, only the fields read (~100–400 KB; git-ignored).
                                 A changed extraction re-derives edgar/ from here with no SEC call; an extract in the old
                                 frame-keyed shape, or with an older `extract_version`, is treated as missing and re-derived.
prices/<TICKER>.json             {"YYYY-MM": close}  (month-end closes only, ≤ as_of; written by meta.price_source)
splits/<TICKER>.json             {"YYYY-MM-DD": ratio}  (split events from the same provider; {} when it reports none)
```

A cache written before split capture has `prices/` but no `splits/`. `read_splits` returns
None for such a ticker — which is not the same as "this company never split" — and the
provider withholds every historical month for it until `hc-valuation market --provider live
--refresh` refetches closes and splits together; the measurement date still prices. The
extract half is versioned separately (`EXTRACT_VERSION`), so a share-selection change
re-derives from `edgar_raw/` without a network call and without touching prices.

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

### 2.8 Known limitations

With the committed cache all 54 constituents price and 12 of 12 sectors are live (4 of 12
before the three rules above), and the history runs 55 months, 2022-03 to 2026-09. Two
things about that history should be read before it is relied on.

**The baskets are five names deep.** A median of five moves when one name does, and an
early month may rest on as few as `min_constituents` (3). M-080 produces 42 indications
from this history, and 24 of them are set by the ±35% limit rather than by the comps, on
raw ratios between 0.26× and 2.59× (the step shows both, `factor_raw` beside
`factor_bounded`). That is the limit doing what the policy asks of it over a thin basket,
not a defect in the feed — but a wider basket would let the comps speak more often, and the
basket review in the architecture document's next-steps list is the answer. The comps never
touch a mark: against the unfixed feed 20 of the 100 positions change disposition through
the X-401/X-402 screens, and marks and NAV are unchanged.

**Some excluded months are input errors the filter is masking, not real states.** The
negative-EV exclusion is a guard on the median, not a diagnosis. Of the 14 constituent-months
it removes from the committed cache, 13 are C3.ai from June 2021 to June 2022, priced on
its dead 3.5M tag because the cache was fetched before the basic-and-diluted concept was
read (above), and one is Teladoc in April 2025, where the extract carries no debt after
2024 — its convertible notes are not under the debt concepts §2.4 reads — so "net cash"
exceeds a $1.2B market cap by $7M. Neither is a company worth less than its cash. A refresh
resolves the first; the second is a concept gap and is left visible.

**Retrieval preceded the valuation date.** `fetched_at` is 2026-09-07 and the measurement
date is 2026-09-30, so the 2026-09 value is the last close on file at retrieval, 23 days
early, not a quarter-end print; every earlier month is a true month end. A refresh after
the measurement date (`market --provider live --refresh`) replaces it, and the manifest's
`fetched_at` is what says which of the two a run used.

## 3. `GET /api/market` — the contract the review tool renders

```jsonc
{
  "provider": "live",                          // "live" | "stub" — what was asked for
  "source": "live:edgar+yahoo",                // what actually answered (manifest label): live:edgar+<price source> | stub
  "reached_live": true,
  "as_of": "2026-09-30",                       // measurement date
  "fetched_at": "2026-09-04T06:12:40Z",        // null when the fixture answered
  "cache": { "dir": "data/market_cache/2026-09-30", "hit": true, "refreshable": true },
  "used_by": { "multiple_mode": "absolute", "calibration_enabled": true,
               "note": "Screens X-401/X-402 use absolute thresholds under this policy; set exceptions.multiple.mode: relative_to_comps to screen against these multiples." },
  "baskets_file": "rules/comps_baskets.yaml",
  "errors": [ "SPOT: EDGAR has no revenue periods under any known concept (foreign private issuer?)",
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
      "history": { "2023-10": 18.2, "...": 0, "2026-09": 22.71 },   // ≤ 96 months, ascending keys
      "counts":  { "2023-10": 3, "...": 0, "2026-09": 5 },           // constituents behind each month (live sectors only)
      "constituents": [
        { "ticker": "PLTR", "name": "Palantir Technologies Inc.", "cik": "0001321655", "status": "ok",
          "price": 41.20, "price_month": "2026-09", "shares_m": 2270.0,
          "shares_basis": "outstanding, cover page",       // what the count is (§2.2); "diluted weighted average" is an approximation
          "shares_as_of": "2026-07-31",                    // the `end` of the fact used
          "shares_age_days": 61,                           // measurement date minus that end; never above 450
          "shares_rejected": [],                           // one line per concept passed over, with the reason
          "months_negative_ev": 0,                         // historical months excluded: net cash above market cap
          "months_unverified_splits": 0,                   // historical months excluded: no split history on file
          "splits_known": true,                            // split events on file; false ⇒ no history before price_month
          "market_cap_musd": 93524.0,
          "net_cash_musd": 4100.0, "ttm_revenue_musd": 3350.0, "revenue_through": "2026-06-30",
          "ev_to_revenue": 26.69, "error": null },
        { "ticker": "TEAM", "name": "Atlassian Corp", "cik": "0001650372", "status": "error",
          "price": null, "price_month": null, "shares_m": null,
          "shares_basis": null, "shares_as_of": null, "shares_age_days": null, "shares_rejected": [],
          "months_negative_ev": 0, "months_unverified_splits": 0, "splits_known": false,
          "market_cap_musd": null,
          "net_cash_musd": null, "ttm_revenue_musd": null, "revenue_through": null,
          "ev_to_revenue": null, "error": "EDGAR has no revenue periods under any known concept (foreign private issuer?)" }
      ]
    }
  ]
}
```

A constituent refused for its share count is `status: "error"` with `shares_rejected` filled
and `error` reading `no share count close enough to 2026-09-30 to price a market cap — …`
followed by the same lines. The three counters and `splits_known` are always present; on a
fixture row they are zero and false.

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
is a reported condition, not a failure). `--json` dumps the §3 payload. `--refresh` clears
the cache directory and refetches closes and split histories together, which is what
restores the monthly history to a cache written before split capture (§2.5). `hc-valuation
run/build --refresh-market` forces the same refetch; those commands take the price source
from `HC_PRICE_SOURCE` (else the baskets default).

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
