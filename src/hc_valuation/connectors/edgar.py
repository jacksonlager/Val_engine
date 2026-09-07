"""SEC EDGAR: the XBRL `companyfacts` API and the ticker → CIK table.

    https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
    https://www.sec.gov/files/company_tickers.json

Both are free and keyless. SEC's fair-access policy asks every client to identify itself
with a `User-Agent` of the form `<app>/<version> (<contact e-mail>)` and to stay under
10 requests per second; `EdgarClient` builds that header from `HC_SEC_CONTACT` (set it to
a real address — the default `valuation@example.com` is a placeholder SEC may block) and
sleeps to stay at or under `MAX_REQUESTS_PER_S`.

Everything below the client is a pure function over the `companyfacts` JSON, unit-tested on
recorded samples under `tests/fixtures/market/`. Values come out in USD millions (shares in
millions), rounded to 3 dp — EDGAR reports raw units.

Conventions of the payload that matter here:

* a *duration* concept (revenue) is read by its own `start`/`end` — never by SEC's calendar
  `frame`, which mis-assigns or drops the quarters of a filer whose year ends in January or
  April — and across every revenue concept a filer has ever used (`RevenueHistory`);
* an *instantaneous* concept (shares, cash, debt) carries frames ending in `I`
  (`CY2026Q2I`), but many entries have none, so instants are keyed by `end` and
  de-duplicated by taking the latest `filed` per `end`;
* a multi-class filer (Alphabet-style) reports `dei.EntityCommonStockSharesOutstanding`
  once per share class with the same `end`, `fy`, `fp` and `filed`; the API carries no class
  dimension, so rows sharing those keys are **summed** to reach total shares outstanding.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from .fetch import DEFAULT_TIMEOUT_S, FetchError, FetchText, RateLimiter, fetch_json

log = logging.getLogger(__name__)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
CONTACT_ENV = "HC_SEC_CONTACT"
DEFAULT_CONTACT = "valuation@example.com"
MAX_REQUESTS_PER_S = 8.0          # SEC's limit is 10/s; stay politely under it

REVENUE_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
# (taxonomy, concept, kind): `instant` rows are summed per end (multi-class); `duration` rows
# are read by quarterly frame only (a 10-Q reports 3- and 9-month averages at the same end).
# Preference order, best evidence first. `basis` is what the number actually counts, which the
# review tool shows: the cover-page and balance-sheet concepts are shares *outstanding* at a
# date; the weighted-average concept is a *diluted average over the period*, close to
# outstanding for these filers (SNOW 352.8 vs 348.7, RBLX 714.3 vs 715.5, NVDA 24,100 vs
# 24,312) but an approximation, and labelled as one.
SHARES_CONCEPTS = (
    ("dei", "EntityCommonStockSharesOutstanding", "instant", "outstanding, cover page"),
    ("us-gaap", "CommonStockSharesOutstanding", "instant", "outstanding, balance sheet"),
    ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "duration", "diluted weighted average"),
    # A loss-making filer has no dilution to report, and many tag the one figure under this
    # concept instead of the two above: C3.ai did so through fiscal 2022, leaving its dead 3.5M
    # balance-sheet tag as the only count on file for a year. Same basis, last in preference.
    ("us-gaap", "WeightedAverageNumberOfShareOutstandingBasicAndDiluted", "duration", "diluted weighted average"),
)
# A share count is evidence about *today's* market cap. Filers abandon a tag without removing
# its history — C3.ai last tagged CommonStockSharesOutstanding in 2021 (3.5M against ~140M
# today), SoundHound's cover-page tag stops at the pre-merger shell (17.5M against ~439M),
# and Hims, Datadog and Toast leave a final value of zero — so a count older than this is not
# used at all. Fifteen months covers a filer who has missed a quarter, not one who has moved on.
SHARES_MAX_AGE_DAYS = 450
# The absolute limit alone is not enough: a tag the filer has dropped stays "fresh" for up to
# fifteen months after its last value, and in that window it beats the concept the filer has
# moved to. Affirm carried its 59M pre-IPO balance-sheet count for a year after listing against
# a 230-280M diluted average; SoundHound its 17.5M shell count for ten months against 160-200M.
# So a concept is also judged against the filer's freshest concept: one that has fallen more
# than a reporting cycle behind it, or whose value cannot be the same share base, is passed over.
SHARES_LAG_DAYS = 135           # one quarter plus a filing lag: two periods behind is "behind"
SHARES_RATIO_BAND = (0.5, 2.0)   # in step by date: outstanding vs diluted average differ by percent, not multiples
SHARES_STALE_BAND = (0.9, 1.1)   # behind by date: only a count that still agrees closely is a slow tag, not a dead one
CASH_CONCEPT = "CashAndCashEquivalentsAtCarryingValue"
INVESTMENT_CONCEPTS = ("ShortTermInvestments", "MarketableSecuritiesCurrent")   # first present
DEBT_TOTAL_CONCEPT = "LongTermDebt"
DEBT_PART_CONCEPTS = ("LongTermDebtNoncurrent", "LongTermDebtCurrent")

MILLION = 1_000_000.0
EXTRACT_VERSION = 3               # bump when the extract's shape or derivation changes; the cache re-derives older ones
_QUARTER_FRAME = re.compile(r"^CY(\d{4})Q([1-4])$")

# Period lengths in days. Fiscal quarters are 13 weeks (91 days) or calendar quarters (89–92);
# a 53-week year makes one quarter 98 days. Everything is matched on length, never on the
# calendar, so a filer whose year ends in January (NVIDIA) or April (C3.ai) reads like any other.
QUARTER_DAYS = (80, 100)
HALF_DAYS = (170, 195)
NINE_MONTH_DAYS = (260, 290)
YEAR_DAYS = (350, 380)
_QUARTER_STEP = (80, 100)         # spacing between consecutive quarter ends
_YEAR_STEP = (355, 375)           # spacing between a period end and its prior-year equivalent


class ExtractionError(ValueError):
    """A fact the arithmetic needs is not in the filing data."""


def musd(raw: float) -> float:
    return round(float(raw) / MILLION, 3)


# ---------------------------------------------------------------- user agent / client

def package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("hc-valuation")
    except PackageNotFoundError:   # a checkout without an install
        return "dev"


def user_agent(contact: str | None = None) -> str:
    """`hc-valuation/<version> (<contact>)` — the form SEC asks for. The contact comes from
    `HC_SEC_CONTACT`; SEC wants a real, monitored address behind it."""
    who = (contact or os.environ.get(CONTACT_ENV) or "").strip()
    if not who:
        log.warning("%s is not set; identifying to SEC as %s. Set it to a real address before relying on live data.",
                    CONTACT_ENV, DEFAULT_CONTACT)
        who = DEFAULT_CONTACT
    return f"hc-valuation/{package_version()} ({who})"


class EdgarClient:
    """Two GETs, rate-limited, with the SEC-required headers. `fetch_text` is the test seam."""

    def __init__(self, *, contact: str | None = None, timeout_s: float = DEFAULT_TIMEOUT_S,
                 fetch_text: FetchText | None = None, max_per_s: float = MAX_REQUESTS_PER_S) -> None:
        self.user_agent = user_agent(contact)
        self.timeout_s = timeout_s
        self._fetch = fetch_text
        self._limiter = RateLimiter(max_per_s)

    @property
    def headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate", "Accept": "application/json"}

    def _get_json(self, url: str) -> Any:
        self._limiter.wait()
        return fetch_json(url, self.headers, self.timeout_s, fetch=self._fetch)

    def company_tickers(self) -> dict[str, dict[str, Any]]:
        """`TICKER -> {"cik": int, "title": str}` from company_tickers.json."""
        raw = self._get_json(COMPANY_TICKERS_URL)
        return parse_company_tickers(raw)

    def company_facts(self, cik: int) -> dict[str, Any]:
        raw = self._get_json(COMPANY_FACTS_URL.format(cik=int(cik)))
        if not isinstance(raw, dict) or "facts" not in raw:
            raise FetchError(f"CIK{int(cik):010d}: companyfacts payload has no `facts`")
        return raw


# ---------------------------------------------------------------- ticker table

def parse_company_tickers(raw: Any) -> dict[str, dict[str, Any]]:
    """The SEC file is `{"0": {"cik_str": 1321655, "ticker": "PLTR", "title": ...}, ...}`."""
    if not isinstance(raw, dict):
        raise FetchError("company_tickers.json is not a JSON object")
    out: dict[str, dict[str, Any]] = {}
    for row in raw.values():
        if not isinstance(row, dict) or "ticker" not in row or "cik_str" not in row:
            continue
        out[str(row["ticker"]).upper()] = {"cik": int(row["cik_str"]), "title": str(row.get("title", ""))}
    if not out:
        raise FetchError("company_tickers.json carried no rows")
    return out


def resolve_ciks(tickers: list[str], table: Mapping[str, Mapping[str, Any]],
                 overrides: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """`ticker -> {"cik": int | None, "title": str | None}`; an override (baskets file) wins,
    an unknown ticker resolves to `cik: None` so the miss is recorded, not retried forever."""
    out: dict[str, dict[str, Any]] = {}
    for t in tickers:
        ov = (overrides or {}).get(t)
        ov_cik = getattr(ov, "cik", None) if ov is not None and not isinstance(ov, Mapping) else (ov or {}).get("cik")
        ov_name = getattr(ov, "name", None) if ov is not None and not isinstance(ov, Mapping) else (ov or {}).get("name")
        row = table.get(t) or {}
        cik = ov_cik if ov_cik is not None else row.get("cik")
        title = ov_name or row.get("title")
        out[t] = {"cik": int(cik) if cik is not None else None, "title": title}
    return out


# ---------------------------------------------------------------- pure extraction

def _entries(facts: Mapping[str, Any], taxonomy: str, concept: str, unit: str) -> list[dict[str, Any]]:
    node = (facts.get("facts") or {}).get(taxonomy, {}).get(concept)
    if not node:
        return []
    return list((node.get("units") or {}).get(unit) or [])


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def _within(days: int, band: tuple[int, int]) -> bool:
    return band[0] <= days <= band[1]


def revenue_periods(facts: Mapping[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """(concepts used, [{start, end, value, days, filed}] ascending by end) — every reported
    revenue period across all `REVENUE_CONCEPTS`, merged.

    Filers switch concepts (NVIDIA and SoundHound moved from `Revenues` to
    `RevenueFromContractWithCustomer…` under ASC 606, and some moved back), so reading one
    concept leaves a history that stops years ago. Here every concept is read; for a period two
    concepts both report, the concept whose history runs latest wins — and on a tie the one
    reporting the larger latest value, a total beating a component (a lender's `Revenues` is
    net interest plus fees; its ASC 606 tag is the fees alone). Only period lengths that mean
    something — a quarter, a half, nine months or a year — are kept.

    A period appears once per *distinct value*, with the earliest filing that reported it, so a
    restatement is a second row with a later `filed`: `RevenueHistory(filed_by=…)` then sees the
    figure the market had on that date, and the latest filing wins when no date is asked."""
    per_concept: dict[str, dict[tuple[str, str], dict[float, str]]] = {}
    for concept in REVENUE_CONCEPTS:
        rows: dict[tuple[str, str], dict[float, str]] = {}   # (start, end) -> {value: earliest filed}
        for e in _entries(facts, "us-gaap", concept, "USD"):
            start, end, val = e.get("start"), e.get("end"), e.get("val")
            if not start or not end or val is None:
                continue
            try:
                days = _days(str(start), str(end))
            except ValueError:
                continue
            if not any(_within(days, b) for b in (QUARTER_DAYS, HALF_DAYS, NINE_MONTH_DAYS, YEAR_DAYS)):
                continue
            filed = str(e.get("filed") or "")
            vals = rows.setdefault((str(start), str(end)), {})
            v = float(val)
            if v not in vals or filed < vals[v]:
                vals[v] = filed
        if rows:
            per_concept[concept] = rows

    def _latest_value(vals: Mapping[float, str]) -> float:
        return max(vals.items(), key=lambda kv: kv[1])[0]

    def _rank(c: str) -> tuple[str, float]:
        latest = max(k[1] for k in per_concept[c])
        return latest, max(_latest_value(v) for (s, e), v in per_concept[c].items() if e == latest)
    order = sorted(per_concept, key=_rank, reverse=True)
    merged: dict[tuple[str, str], dict[float, str]] = {}
    for concept in order:
        for key, vals in per_concept[concept].items():
            merged.setdefault(key, vals)
    out = [{"start": s, "end": e, "value": musd(v), "days": _days(s, e), "filed": filed}
           for (s, e), vals in merged.items() for v, filed in vals.items()]
    out.sort(key=lambda r: (r["end"], r["start"], r["filed"]))
    return order, out


def as_of_filing(rows: list[Mapping[str, Any]], filed_by: date | None) -> list[dict[str, Any]]:
    """One row per period (or per instant `end`): the latest filing on or before `filed_by`, or
    the latest filing of all when no date is given. Rows without a `filed` always count."""
    fkey = filed_by.isoformat() if filed_by is not None else None
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        filed = str(r.get("filed") or "")
        if fkey is not None and filed and filed > fkey:
            continue
        key = (str(r.get("start") or ""), str(r["end"]))
        cur = best.get(key)
        if cur is None or filed >= str(cur.get("filed") or ""):
            best[key] = dict(r)
    return sorted(best.values(), key=lambda r: (r["end"], r.get("start") or ""))


def quarters_from_periods(periods: list[Mapping[str, Any]]) -> dict[str, float]:
    """`{quarter end: revenue}` — quarters as reported, plus quarters derived by differencing
    year-to-date periods that share a start (Q4 = year − nine months, Q2 = half − Q1, …). A
    reported quarter always beats a derived one."""
    direct: dict[str, float] = {}
    by_start: dict[str, list[Mapping[str, Any]]] = {}
    for r in periods:
        if _within(int(r["days"]), QUARTER_DAYS):
            direct[str(r["end"])] = float(r["value"])
        by_start.setdefault(str(r["start"]), []).append(r)
    derived: dict[str, float] = {}
    for start, rows in by_start.items():
        rows = sorted(rows, key=lambda r: r["end"])
        prev_end, prev_val = None, 0.0
        for r in rows:
            if prev_end is not None:
                span = (date.fromisoformat(str(r["end"])) - date.fromisoformat(prev_end)).days
                if _within(span, _QUARTER_STEP):
                    derived[str(r["end"])] = round(float(r["value"]) - prev_val, 3)
            prev_end, prev_val = str(r["end"]), float(r["value"])
    out = dict(derived)
    out.update(direct)
    return dict(sorted(out.items()))


def _prior_end(ends: list[str], end: str, step: tuple[int, int]) -> str | None:
    """The end in `ends` that sits `step` days before `end` (closest when several)."""
    target = date.fromisoformat(end)
    best, best_gap = None, None
    for e in ends:
        gap = (target - date.fromisoformat(e)).days
        if _within(gap, step):
            off = abs(gap - (step[0] + step[1]) // 2)
            if best is None or off < best_gap:
                best, best_gap = e, off
    return best


class RevenueHistory:
    """TTM revenue at any date from a filer's reported periods, whatever its fiscal calendar.

    Two routes, tried in order for the latest period ended on or before the date asked:
    1. four consecutive reported-or-derived quarters (each 80–100 days apart) → their sum;
    2. the latest fiscal year plus the year-to-date since it, less the same year-to-date a
       year earlier (the standard `FY + YTD − prior YTD` construction); a fiscal year with no
       later filing is simply the year.
    `through` is the end date the TTM runs to, so a reader can see how current it is."""

    def __init__(self, periods: list[Mapping[str, Any]], filed_by: date | None = None) -> None:
        """`filed_by` keeps only periods filed on or before that date — the point-in-time view a
        reader of the market had then, used for every month of the comps history."""
        self.periods = as_of_filing(list(periods), filed_by)
        self.quarters = quarters_from_periods(self.periods)
        self._q_ends = sorted(self.quarters)
        self.years = {str(r["end"]): r for r in self.periods if _within(int(r["days"]), YEAR_DAYS)}
        self._ytd = [r for r in self.periods if not _within(int(r["days"]), YEAR_DAYS)]

    def __bool__(self) -> bool:
        return bool(self.periods)

    def latest_end(self, on: date) -> str | None:
        key = on.isoformat()
        ends = [str(r["end"]) for r in self.periods if str(r["end"]) <= key]
        return max(ends) if ends else None

    def _four_quarters(self, through: str) -> float | None:
        ends = [e for e in self._q_ends if e <= through]
        if through not in self.quarters:
            return None
        chain, cur = [through], through
        for _ in range(3):
            prev = _prior_end(ends, cur, _QUARTER_STEP)
            if prev is None:
                return None
            chain.append(prev)
            cur = prev
        return round(sum(self.quarters[e] for e in chain), 3)

    def _year_plus_ytd(self, on: date) -> tuple[float, str] | None:
        key = on.isoformat()
        year_ends = sorted(e for e in self.years if e <= key)
        if not year_ends:
            return None
        fy_end = year_ends[-1]
        fy_val = float(self.years[fy_end]["value"])
        fy_start_next = (date.fromisoformat(fy_end)).toordinal() + 1
        # year-to-date periods that start right after the fiscal year and end by `on`
        after = [r for r in self._ytd
                 if str(r["end"]) <= key and abs(date.fromisoformat(str(r["start"])).toordinal() - fy_start_next) <= 3]
        if not after:
            return fy_val, fy_end
        ytd = max(after, key=lambda r: r["end"])
        prior = [r for r in self._ytd
                 if _within((date.fromisoformat(str(ytd["end"])) - date.fromisoformat(str(r["end"]))).days, _YEAR_STEP)
                 and abs(int(r["days"]) - int(ytd["days"])) <= 10]
        if not prior:
            return None
        # the comparable period is the one that matches the year-to-date's length and calendar best
        best = min(prior, key=lambda r: (abs(int(r["days"]) - int(ytd["days"])),
                                         abs((date.fromisoformat(str(ytd["end"])) - date.fromisoformat(str(r["end"]))).days - 365)))
        return round(fy_val + float(ytd["value"]) - float(best["value"]), 3), str(ytd["end"])

    def ttm_at(self, on: date) -> tuple[float, str]:
        """(TTM revenue in $M, period end it runs through) for the latest period ended on or
        before `on`. Raises ExtractionError when neither route can be built."""
        if not self.periods:
            raise ExtractionError("no revenue periods reported")
        through = self.latest_end(on)
        if through is None:
            raise ExtractionError(f"no revenue period ended on or before {on.isoformat()}")
        # route 1: the latest quarter end at or before `on` with three consecutive predecessors
        q_ends = [e for e in self._q_ends if e <= on.isoformat()]
        if q_ends:
            total = self._four_quarters(q_ends[-1])
            if total is not None:
                return total, q_ends[-1]
        # route 2: fiscal year + YTD − prior YTD
        alt = self._year_plus_ytd(on)
        if alt is not None:
            return alt
        raise ExtractionError(f"TTM through {through} undefined: fewer than four consecutive quarters and no "
                              "fiscal year to build it from")


def ttm_at(periods: list[Mapping[str, Any]] | RevenueHistory, on: date, *, filed_by: date | None = None) -> tuple[float, str]:
    """Convenience over `RevenueHistory` for one-off calls; `filed_by` gives the point-in-time view."""
    if isinstance(periods, RevenueHistory) and filed_by is None:
        return periods.ttm_at(on)
    src = periods.periods if isinstance(periods, RevenueHistory) else list(periods)
    return RevenueHistory(src, filed_by=filed_by).ttm_at(on)


_TOTAL_ROW_TOLERANCE = 0.005   # a row within 0.5% of the sum of the others is the filer's own total


def _class_total(vals: list[float]) -> float:
    """Total shares from the rows one filing reports for one date. Usually one row per class,
    to be summed; some filers also tag the total itself, and summing that in would double
    count — so a row that equals the sum of the others is taken as the total instead."""
    if len(vals) < 2:
        return vals[0] if vals else 0.0
    total = sum(vals)
    for v in vals:
        rest = total - v
        if rest > 0 and abs(v - rest) <= _TOTAL_ROW_TOLERANCE * rest:
            return v
    return total


def summed_instant_series(entries: list[Mapping[str, Any]], scale: float = MILLION) -> list[dict[str, Any]]:
    """Instant rows keyed by `end`: rows sharing (end, fy, fp, filed) are summed — a multi-class
    filer reports one row per class — and per `end` the latest `filed` wins."""
    rows: dict[tuple[str, Any, Any, str], list[float]] = {}
    for e in entries:
        end, val = e.get("end"), e.get("val")
        if not end or val is None:
            continue
        key = (str(end), e.get("fy"), e.get("fp"), str(e.get("filed") or ""))
        rows.setdefault(key, []).append(float(val))
    groups = {key: _class_total(vals) for key, vals in rows.items()}
    per_end: dict[str, dict[float, str]] = {}
    for (end, _fy, _fp, filed), total in groups.items():
        vals = per_end.setdefault(end, {})
        if total not in vals or filed < vals[total]:
            vals[total] = filed
    return _series_rows(per_end, scale)


def _series_rows(per_end: Mapping[str, Mapping[float, str]], scale: float) -> list[dict[str, Any]]:
    """`[{end, value, filed}]` — one row per distinct value an `end` was ever reported at, with
    the earliest filing of that value, so `value_at(filed_by=…)` can read the figure as filed."""
    out = [{"end": end, "value": round(v / scale, 3), "filed": f} for end, vals in per_end.items() for v, f in vals.items()]
    return sorted(out, key=lambda r: (r["end"], r["filed"]))


def instant_series(entries: list[Mapping[str, Any]], scale: float = MILLION) -> list[dict[str, Any]]:
    """Instant rows keyed by `end`, latest `filed` per `end` (no summation)."""
    per_end: dict[str, dict[float, str]] = {}
    for e in entries:
        end, val = e.get("end"), e.get("val")
        if not end or val is None:
            continue
        filed = str(e.get("filed") or "")
        vals = per_end.setdefault(str(end), {})
        v = float(val)
        if v not in vals or filed < vals[v]:
            vals[v] = filed
    return _series_rows(per_end, scale)


def duration_series(entries: list[Mapping[str, Any]], scale: float = MILLION) -> list[dict[str, Any]]:
    """Duration rows of quarter length only (a 10-Q also reports the year-to-date average at
    the same end), keyed by period end; latest `filed` per end."""
    per_end: dict[str, dict[float, str]] = {}
    for e in entries:
        start, end, val = e.get("start"), e.get("end"), e.get("val")
        if not start or not end or val is None:
            continue
        try:
            if not _within(_days(str(start), str(end)), QUARTER_DAYS):
                continue
        except ValueError:
            continue
        filed = str(e.get("filed") or "")
        vals = per_end.setdefault(str(end), {})
        v = float(val)
        if v not in vals or filed < vals[v]:
            vals[v] = filed
    return _series_rows(per_end, scale)


def all_shares_series(facts: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Every share-count concept this filer reports, keyed `taxonomy:concept`.

    All of them are cached, not just the winner, because which one is usable depends on the
    measurement date: a concept the filer stopped tagging years ago is useless for a market cap
    today but was the right answer for a 2021 close. Choosing at read time (`shares_at`) keeps
    the extract re-derivable for any date without refetching."""
    out: dict[str, list[dict[str, Any]]] = {}
    for taxonomy, concept, kind, _basis in SHARES_CONCEPTS:
        entries = _entries(facts, taxonomy, concept, "shares")
        series = summed_instant_series(entries) if kind == "instant" else duration_series(entries)
        if series:
            out[f"{taxonomy}:{concept}"] = series
    return out


@dataclass(frozen=True)
class SharesPick:
    """The share count chosen for a measurement date, and what was passed over to get there."""
    value: float | None                  # millions of shares, None when nothing is usable
    concept: str | None                  # "taxonomy:concept"
    basis: str | None                    # "outstanding, cover page" | "diluted weighted average" | ...
    as_of: str | None                    # the `end` of the fact used
    age_days: int | None                 # measurement date minus that `end`
    rejected: tuple[str, ...] = ()       # one line per concept passed over, with the reason
    filed: str | None = None             # when that fact was filed: the date its share basis is on

    @property
    def approximate(self) -> bool:
        return bool(self.basis and self.basis.startswith("diluted"))

    @property
    def basis_date(self) -> date | None:
        """The date the count's share basis belongs to. A split after this date, and only a
        split after it, has to be applied before the count meets a split-adjusted close: a
        filing made after a split already reports post-split shares (SAB Topic 4C restates
        them), one made before does not — whatever the period the fact is for."""
        raw = self.filed or self.as_of
        return date.fromisoformat(raw) if raw else None


def shares_at(series_by_concept: Mapping[str, list[Mapping[str, Any]]], on: date,
              *, max_age_days: int = SHARES_MAX_AGE_DAYS, lag_days: int = SHARES_LAG_DAYS,
              ratio_band: tuple[float, float] = SHARES_RATIO_BAND,
              stale_band: tuple[float, float] = SHARES_STALE_BAND) -> SharesPick:
    """The best share count for `on`: the first concept in preference order whose latest fact
    at that date is positive, no older than `max_age_days`, and still credible against the
    filer's freshest concept — within `ratio_band` of its value when in step by date (no more
    than `lag_days` behind), within the tighter `stale_band` when behind.

    A dropped tag fails this long before it fails the absolute limit: a pre-listing count
    against a post-listing average is off by multiples, not percent, and a tag the filer
    stopped updating drifts away from the one it keeps filing. A concept merely reported
    annually falls behind by date every year but still agrees closely, so it is kept.

    Returning nothing is a real answer — the constituent goes unpriced with a stated reason,
    which is the honest outcome when the only counts on file predate the company's current
    capital structure. Silently pricing a 2026 market cap off a 2021 share count is not."""
    rejected: list[str] = []
    candidates: list[tuple[str, str, str, Mapping[str, Any], float, int]] = []
    for taxonomy, concept, _kind, basis in SHARES_CONCEPTS:
        key = f"{taxonomy}:{concept}"
        series = list(series_by_concept.get(key) or [])
        if not series:
            continue
        row = None
        for r in series:                                  # series is sorted by end
            end = str(r.get("end") or "")
            if end and end <= on.isoformat() and str(r.get("filed") or "") <= on.isoformat():
                row = r
        if row is None:
            rejected.append(f"{concept}: nothing filed on or before {on.isoformat()}")
            continue
        value = float(row.get("value") or 0.0)
        age = (on - date.fromisoformat(str(row["end"]))).days
        if value <= 0:
            rejected.append(f"{concept}: last value is {value:g} ({row['end']})")
            continue
        if age > max_age_days:
            years = age / 365.25
            rejected.append(f"{concept}: last filed {row['end']}, {years:.1f} years before the measurement date")
            continue
        candidates.append((key, concept, basis, row, value, age))

    if candidates:
        # the freshest concept is the one the filer is actually keeping up; the rest are judged by it
        fkey, fconcept, _b, frow, fvalue, _a = min(candidates, key=lambda c: c[5])
        for key, concept, basis, row, value, age in candidates:
            if key != fkey:
                behind = (date.fromisoformat(str(frow["end"])) - date.fromisoformat(str(row["end"]))).days
                ratio = value / fvalue if fvalue else 0.0
                lo, hi = stale_band if behind > lag_days else ratio_band
                if not (lo <= ratio <= hi):
                    why = (f"{behind} days behind {fconcept} ({frow['end']}) and {ratio:.2g}x its {fvalue:,.1f}M — the filer has moved on"
                           if behind > lag_days else
                           f"{value:,.1f}M is {ratio:.2g}x the {fvalue:,.1f}M under {fconcept} — not the same share base")
                    rejected.append(f"{concept}: last filed {row['end']}, {why}")
                    continue
            return SharesPick(value=value, concept=key, basis=basis, as_of=str(row["end"]),
                              age_days=age, rejected=tuple(rejected), filed=str(row.get("filed") or "") or None)
    return SharesPick(value=None, concept=None, basis=None, as_of=None, age_days=None,
                      rejected=tuple(rejected))


def shares_series(facts: Mapping[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    """Back-compat: the first concept with any data. Kept for readers of v2 extracts; new code
    caches every series (`all_shares_series`) and chooses at the measurement date."""
    for taxonomy, concept, kind, _basis in SHARES_CONCEPTS:
        entries = _entries(facts, taxonomy, concept, "shares")
        series = summed_instant_series(entries) if kind == "instant" else duration_series(entries)
        if series:
            return f"{taxonomy}:{concept}", series
    return None, []


def value_at(series: list[Mapping[str, Any]], on: date, *, filed_by: date | None = None) -> float | None:
    """The value of the latest entry whose `end` is on or before `on` — and, with `filed_by`,
    that had been filed by then (a row with no `filed` is never excluded)."""
    key = on.isoformat()
    fkey = filed_by.isoformat() if filed_by is not None else None
    best = None
    for row in series:
        if row["end"] > key or (fkey is not None and row.get("filed") and str(row["filed"]) > fkey):
            continue
        if best is None or (row["end"], str(row.get("filed") or "")) >= (best["end"], str(best.get("filed") or "")):
            best = row
    return float(best["value"]) if best is not None else None


def combine_series(parts: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Sum several instant series into one: at every `end` any part reports, the sum of each
    part's latest value at or before that end (a part with nothing yet counts 0). The combined
    row is filed when the last of its parts was."""
    ends = sorted({row["end"] for s in parts for row in s})
    out = []
    for end in ends:
        on = date.fromisoformat(end)
        filings = sorted({str(r.get("filed") or "") for s in parts for r in s if r["end"] == end})
        seen: dict[float, str] = {}
        for filed in filings:
            fb = date.fromisoformat(filed) if filed else None
            total = round(sum(value_at(s, on, filed_by=fb) or 0.0 for s in parts), 3)
            if total not in seen:
                seen[total] = filed
        out.extend({"end": end, "value": v, "filed": f} for v, f in seen.items())
    return sorted(out, key=lambda r: (r["end"], r["filed"]))


def cash_series(facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Cash and equivalents plus short-term investments (else current marketable securities)."""
    parts = [instant_series(_entries(facts, "us-gaap", CASH_CONCEPT, "USD"))]
    for concept in INVESTMENT_CONCEPTS:
        s = instant_series(_entries(facts, "us-gaap", concept, "USD"))
        if s:
            parts.append(s)
            break
    return combine_series(parts)


def debt_series(facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    """`LongTermDebt` if reported, else the non-current and current pieces (each 0 when absent)."""
    total = instant_series(_entries(facts, "us-gaap", DEBT_TOTAL_CONCEPT, "USD"))
    if total:
        return total
    return combine_series([instant_series(_entries(facts, "us-gaap", c, "USD")) for c in DEBT_PART_CONCEPTS])


def net_cash_at(cash: list[Mapping[str, Any]], debt: list[Mapping[str, Any]], on: date, *,
                filed_by: date | None = None) -> float:
    """Latest cash minus latest long-term debt at or before `on`; each 0 when nothing is reported.
    An approximation (no leases, no preferred, no minority interest) and labelled as such."""
    return round((value_at(cash, on, filed_by=filed_by) or 0.0) - (value_at(debt, on, filed_by=filed_by) or 0.0), 3)


def extract(facts: Mapping[str, Any]) -> dict[str, Any]:
    """The trimmed, cacheable extract of one filer — everything the provider needs, nothing else."""
    revenue_concepts, periods = revenue_periods(facts)
    shares_concept, shares = shares_series(facts)
    cik = facts.get("cik")
    by_concept = all_shares_series(facts)
    return {
        "extract_version": EXTRACT_VERSION,
        "cik": f"{int(cik):010d}" if cik is not None else None,
        "name": facts.get("entityName"),
        "revenue_concepts": revenue_concepts,
        "revenue_periods": periods,
        "shares_concept": shares_concept,          # v2 field, kept so an older reader still works
        "shares": shares,                          # v2 field, ditto
        "shares_by_concept": by_concept,           # v3: every concept, chosen at the measurement date
        "cash": cash_series(facts),
        "debt": debt_series(facts),
    }


SLIM_CONCEPTS = (
    [("us-gaap", c) for c in REVENUE_CONCEPTS] + [(t, c) for t, c, _k, _b in SHARES_CONCEPTS]
    + [("us-gaap", CASH_CONCEPT)] + [("us-gaap", c) for c in INVESTMENT_CONCEPTS]
    + [("us-gaap", DEBT_TOTAL_CONCEPT)] + [("us-gaap", c) for c in DEBT_PART_CONCEPTS]
)
_SLIM_FIELDS = ("start", "end", "val", "fy", "fp", "form", "filed", "frame")


def slim(facts: Mapping[str, Any]) -> dict[str, Any]:
    """The companyfacts document cut down to the concepts this module reads — a few hundred KB
    instead of several MB — kept beside the extract so a change to the arithmetic can be
    re-derived offline without another SEC call."""
    out: dict[str, Any] = {}
    for taxonomy, concept in SLIM_CONCEPTS:
        node = (facts.get("facts") or {}).get(taxonomy, {}).get(concept)
        if not node:
            continue
        units = {u: [{k: e[k] for k in _SLIM_FIELDS if k in e} for e in es]
                 for u, es in (node.get("units") or {}).items()}
        out.setdefault(taxonomy, {})[concept] = {"units": units}
    return {"cik": facts.get("cik"), "entityName": facts.get("entityName"), "facts": out}


def fetch_extract(client: EdgarClient, cik: int) -> dict[str, Any]:
    return extract(client.company_facts(cik))


def fetch_slim(client: EdgarClient, cik: int) -> dict[str, Any]:
    return slim(client.company_facts(cik))


__all__ = [
    "COMPANY_FACTS_URL", "COMPANY_TICKERS_URL", "CONTACT_ENV", "DEFAULT_CONTACT", "EdgarClient", "ExtractionError",
    "RevenueHistory", "cash_series", "combine_series", "debt_series", "extract", "fetch_extract", "fetch_slim",
    "net_cash_at", "parse_company_tickers", "quarters_from_periods", "resolve_ciks", "revenue_periods",
    "SharesPick", "all_shares_series", "shares_at", "shares_series", "slim", "summed_instant_series",
    "ttm_at", "user_agent", "value_at",
]
