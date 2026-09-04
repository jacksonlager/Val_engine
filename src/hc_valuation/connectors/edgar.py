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

* a *duration* concept (revenue) carries a `frame` such as `CY2026Q2` (one calendar
  quarter) or `CY2025` (one calendar year) on exactly one entry per period — SEC's own
  de-duplication of restatements. Entries with no `frame` are duplicates or odd periods and
  are ignored for revenue;
* an *instantaneous* concept (shares, cash, debt) carries frames ending in `I`
  (`CY2026Q2I`), but many entries have none, so instants are keyed by `end` and
  de-duplicated by taking the latest `filed` per `end`;
* a multi-class filer (Alphabet-style) reports `dei.EntityCommonStockSharesOutstanding`
  once per share class with the same `end`, `fy`, `fp` and `filed`; the API carries no class
  dimension, so rows sharing those keys are **summed** to reach total shares outstanding.
"""
from __future__ import annotations

import calendar
import logging
import os
import re
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
SHARES_CONCEPTS = (
    ("dei", "EntityCommonStockSharesOutstanding", "instant"),
    ("us-gaap", "CommonStockSharesOutstanding", "instant"),
    ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "duration"),
)
CASH_CONCEPT = "CashAndCashEquivalentsAtCarryingValue"
INVESTMENT_CONCEPTS = ("ShortTermInvestments", "MarketableSecuritiesCurrent")   # first present
DEBT_TOTAL_CONCEPT = "LongTermDebt"
DEBT_PART_CONCEPTS = ("LongTermDebtNoncurrent", "LongTermDebtCurrent")

MILLION = 1_000_000.0
_QUARTER_FRAME = re.compile(r"^CY(\d{4})Q([1-4])$")
_ANNUAL_FRAME = re.compile(r"^CY(\d{4})$")


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


def quarterly_from_entries(entries: list[Mapping[str, Any]]) -> dict[str, float]:
    """`{"CY2026Q2": musd, ...}` from one duration concept: quarterly frames as reported, plus a
    calendar Q4 derived as the annual frame minus Q1–Q3 when all three exist and Q4 itself
    has no frame. Entries without a frame are ignored."""
    quarters: dict[str, float] = {}
    annual: dict[str, float] = {}
    for e in entries:
        frame = e.get("frame")
        if not frame or e.get("val") is None:
            continue
        if _QUARTER_FRAME.match(frame):
            quarters[frame] = musd(e["val"])
        elif _ANNUAL_FRAME.match(frame):
            annual[frame] = musd(e["val"])
    for year, total in annual.items():
        q4 = f"{year}Q4"
        if q4 in quarters:
            continue
        parts = [quarters.get(f"{year}Q{i}") for i in (1, 2, 3)]
        if all(p is not None for p in parts):
            quarters[q4] = round(total - sum(parts), 3)   # type: ignore[arg-type]
    return dict(sorted(quarters.items()))


def quarterly_revenue(facts: Mapping[str, Any]) -> tuple[str | None, dict[str, float]]:
    """(concept used, quarterly revenue by frame) — the first concept in `REVENUE_CONCEPTS`
    that yields at least one quarterly value. `(None, {})` when none does."""
    for concept in REVENUE_CONCEPTS:
        q = quarterly_from_entries(_entries(facts, "us-gaap", concept, "USD"))
        if q:
            return concept, q
    return None, {}


def frame_end(frame: str) -> date:
    m = _QUARTER_FRAME.match(frame)
    if not m:
        raise ValueError(f"not a quarterly frame: {frame!r}")
    year, q = int(m.group(1)), int(m.group(2))
    month = 3 * q
    return date(year, month, calendar.monthrange(year, month)[1])


def frames_through(frame: str, n: int = 4) -> list[str]:
    """The `n` quarterly frames ending at `frame`, ascending."""
    m = _QUARTER_FRAME.match(frame)
    if not m:
        raise ValueError(f"not a quarterly frame: {frame!r}")
    year, q = int(m.group(1)), int(m.group(2))
    out = []
    for _ in range(n):
        out.append(f"CY{year}Q{q}")
        q -= 1
        if q == 0:
            year, q = year - 1, 4
    return list(reversed(out))


def ttm_revenue(quarterly: Mapping[str, float], through: str) -> float:
    """Sum of the four quarters ending at `through`; undefined when any is missing."""
    frames = frames_through(through)
    missing = [f for f in frames if f not in quarterly]
    if missing:
        raise ExtractionError(f"TTM through {through} undefined: missing {', '.join(missing)}")
    return round(sum(quarterly[f] for f in frames), 3)


def latest_quarter_at(quarterly: Mapping[str, float], on: date) -> str | None:
    """The latest quarterly frame whose quarter ends on or before `on`."""
    cands = [f for f in quarterly if _QUARTER_FRAME.match(f) and frame_end(f) <= on]
    return max(cands) if cands else None


def ttm_at(quarterly: Mapping[str, float], on: date) -> tuple[float, str]:
    """(TTM revenue, frame it runs through) for the latest quarter ended on or before `on`."""
    if not quarterly:
        raise ExtractionError("no quarterly revenue frames")
    through = latest_quarter_at(quarterly, on)
    if through is None:
        raise ExtractionError(f"no quarter ended on or before {on.isoformat()}")
    return ttm_revenue(quarterly, through), through


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
    per_end: dict[str, tuple[str, float]] = {}
    for (end, _fy, _fp, filed), total in groups.items():
        cur = per_end.get(end)
        if cur is None or filed > cur[0]:
            per_end[end] = (filed, total)
    return [{"end": end, "value": round(v / scale, 3)} for end, (_f, v) in sorted(per_end.items())]


def instant_series(entries: list[Mapping[str, Any]], scale: float = MILLION) -> list[dict[str, Any]]:
    """Instant rows keyed by `end`, latest `filed` per `end` (no summation)."""
    per_end: dict[str, tuple[str, float]] = {}
    for e in entries:
        end, val = e.get("end"), e.get("val")
        if not end or val is None:
            continue
        filed = str(e.get("filed") or "")
        cur = per_end.get(str(end))
        if cur is None or filed > cur[0]:
            per_end[str(end)] = (filed, float(val))
    return [{"end": end, "value": round(v / scale, 3)} for end, (_f, v) in sorted(per_end.items())]


def duration_series(entries: list[Mapping[str, Any]], scale: float = MILLION) -> list[dict[str, Any]]:
    """Duration rows read by quarterly frame only, keyed by the frame's quarter end."""
    out: dict[str, float] = {}
    for e in entries:
        frame, val = e.get("frame"), e.get("val")
        if frame and val is not None and _QUARTER_FRAME.match(frame):
            out[frame_end(frame).isoformat()] = float(val)
    return [{"end": end, "value": round(v / scale, 3)} for end, v in sorted(out.items())]


def shares_series(facts: Mapping[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    """(concept used, [{end, value in millions}]) — first concept in `SHARES_CONCEPTS` with data."""
    for taxonomy, concept, kind in SHARES_CONCEPTS:
        entries = _entries(facts, taxonomy, concept, "shares")
        series = summed_instant_series(entries) if kind == "instant" else duration_series(entries)
        if series:
            return f"{taxonomy}:{concept}", series
    return None, []


def value_at(series: list[Mapping[str, Any]], on: date) -> float | None:
    """The value of the latest entry whose `end` is on or before `on`."""
    key = on.isoformat()
    best = None
    for row in series:
        if row["end"] <= key and (best is None or row["end"] >= best["end"]):
            best = row
    return float(best["value"]) if best is not None else None


def combine_series(parts: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Sum several instant series into one: at every `end` any part reports, the sum of each
    part's latest value at or before that end (a part with nothing yet counts 0)."""
    ends = sorted({row["end"] for s in parts for row in s})
    out = []
    for end in ends:
        on = date.fromisoformat(end)
        out.append({"end": end, "value": round(sum(value_at(s, on) or 0.0 for s in parts), 3)})
    return out


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


def net_cash_at(cash: list[Mapping[str, Any]], debt: list[Mapping[str, Any]], on: date) -> float:
    """Latest cash minus latest long-term debt at or before `on`; each 0 when nothing is reported.
    An approximation (no leases, no preferred, no minority interest) and labelled as such."""
    return round((value_at(cash, on) or 0.0) - (value_at(debt, on) or 0.0), 3)


def extract(facts: Mapping[str, Any]) -> dict[str, Any]:
    """The trimmed, cacheable extract of one filer — everything the provider needs, nothing else."""
    revenue_concept, quarterly = quarterly_revenue(facts)
    shares_concept, shares = shares_series(facts)
    cik = facts.get("cik")
    return {
        "cik": f"{int(cik):010d}" if cik is not None else None,
        "name": facts.get("entityName"),
        "revenue_concept": revenue_concept,
        "revenue_quarterly": quarterly,
        "shares_concept": shares_concept,
        "shares": shares,
        "cash": cash_series(facts),
        "debt": debt_series(facts),
    }


def fetch_extract(client: EdgarClient, cik: int) -> dict[str, Any]:
    return extract(client.company_facts(cik))


__all__ = [
    "COMPANY_FACTS_URL", "COMPANY_TICKERS_URL", "CONTACT_ENV", "DEFAULT_CONTACT", "EdgarClient", "ExtractionError",
    "cash_series", "combine_series", "debt_series", "extract", "fetch_extract", "frame_end", "frames_through",
    "latest_quarter_at", "net_cash_at", "parse_company_tickers", "quarterly_from_entries", "quarterly_revenue",
    "resolve_ciks", "shares_series", "summed_instant_series", "ttm_at", "ttm_revenue", "user_agent", "value_at",
]
