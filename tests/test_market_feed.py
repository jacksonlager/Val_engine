"""The live market feed (docs/market-feed.md): EDGAR extraction, the pluggable price source
(Yahoo chart payloads, Stooq CSVs, month ends), browser-challenge detection, the cache rules,
the provider's per-constituent degradation, error collapsing, and the `/api/market` contract.
No test touches the network — every response is a recording under tests/fixtures/market/ or
an injected failure."""
from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hc_valuation.api.app import create_app
from hc_valuation.cli import app as cli_app
from hc_valuation.config import repo_root
from hc_valuation.connectors import (
    LIVE_LABEL_PREFIX, PRICE_SOURCE_ENV, MarketAssembly, assemble_market_data, live_label, resolve_price_source,
    resolve_provider,
)
from hc_valuation.connectors import fetch as fetch_mod
from hc_valuation.connectors.baskets import load_baskets
from hc_valuation.connectors.base import CompsProvider
from hc_valuation.connectors.cache import MarketCache
from hc_valuation.connectors.edgar import (
    cash_series,
    combine_series,
    COMPANY_FACTS_URL,
    COMPANY_TICKERS_URL,
    CONTACT_ENV,
    debt_series,
    DEFAULT_CONTACT,
    EdgarClient,
    extract,
    EXTRACT_VERSION,
    ExtractionError,
    net_cash_at,
    parse_company_tickers,
    quarters_from_periods,
    resolve_ciks,
    revenue_periods,
    RevenueHistory,
    shares_series,
    slim,
    SLIM_VERSION,
    summed_instant_series,
    ttm_at,
    user_agent,
    value_at,
)
from hc_valuation.connectors.fetch import FetchError, browser_challenge_message, fetch_text, is_browser_challenge
from hc_valuation.connectors.live import (
    COLLAPSE_AT, LiveFeedError, PublicCompsProvider, collapse_errors, live_source, months_back, stub_market_report,
)
from hc_valuation.connectors.prices import (
    DEFAULT_PRICE_SOURCE, PRICE_SOURCES, YAHOO_URL, PriceProvider, StooqPrices, YahooPrices, parse_yahoo_chart,
    price_provider,
)
from hc_valuation.connectors.stooq import STOOQ_URL, fetch_daily_closes, month_end_closes, parse_daily_csv
from hc_valuation.connectors.stubs import StubCompsProvider
from hc_valuation.export.static_report import write_static_report
from hc_valuation.pipeline import RunPaths, execute

ROOT = repo_root()
FIX = ROOT / "tests" / "fixtures" / "market"
AS_OF = date(2026, 9, 30)
CIKS = {"AAA": 1000001, "BBB": 1000002, "CCC": 1000003}
LIVE_LABEL = "live:edgar+yahoo"          # the default price source
LIVE_STOOQ = "live:edgar+stooq"
BASELINE = {"BLOCK": 7, "REVIEW": 20, "MONITOR": 39, "CLEAR": 34}

CONSTITUENT_KEYS = {"ticker", "name", "cik", "status", "price", "price_month", "shares_m", "market_cap_musd",
                    "net_cash_musd", "ttm_revenue_musd", "revenue_through", "ev_to_revenue", "error",
                     # input provenance and quality, added when the share-count and split defects
                     # were found in the committed cache (tests/test_market_inputs.py)
                     "shares_basis", "shares_as_of", "shares_age_days", "shares_rejected",
                     "months_negative_ev", "months_unverified_splits", "splits_known"}
SECTOR_KEYS = {"sector", "positions", "ev_to_revenue", "as_of_month", "source", "live", "prior_quarter", "qoq_pct",
               "history", "counts", "constituents"}
REPORT_KEYS = {"provider", "source", "reached_live", "as_of", "priced_as_of", "valuation_date", "fetched_at", "cache", "used_by", "baskets_file",
               "errors", "sectors"}


def facts(ticker: str) -> dict:
    return json.loads((FIX / f"companyfacts_{ticker}.json").read_text())


class FakeFetch:
    """The `fetch_text` seam: recorded bodies by URL, plus injectable failures."""

    def __init__(self, *, timeout: set[str] = frozenset(), html: set[str] = frozenset(), fail_all: bool = False,
                 challenge: set[str] = frozenset()) -> None:
        self.calls: list[str] = []
        self.headers: list[dict] = []
        self.timeout, self.html, self.fail_all, self.challenge = set(timeout), set(html), fail_all, set(challenge)
        self.routes = {COMPANY_TICKERS_URL: FIX / "company_tickers.json"}
        for t, cik in CIKS.items():
            self.routes[COMPANY_FACTS_URL.format(cik=cik)] = FIX / f"companyfacts_{t}.json"
            self.routes[STOOQ_URL.format(symbol=f"{t.lower()}.us")] = FIX / f"stooq_{t}.csv"
            self.routes[YAHOO_URL.format(symbol=t)] = FIX / f"yahoo_{t}.json"
        self.routes[YAHOO_URL.format(symbol="ZZZ")] = FIX / "yahoo_ZZZ.json"      # a delisted symbol: chart.error

    def __call__(self, url: str, headers, timeout_s: float) -> str:
        self.calls.append(url)
        self.headers.append(dict(headers or {}))
        if self.fail_all:
            raise FetchError("ConnectError: [Errno 101] Network is unreachable")
        if url in self.timeout:
            raise FetchError("ReadTimeout: timed out")
        if url in self.challenge:                       # what fetch_text raises for a bot-challenge page
            raise FetchError(browser_challenge_message(url))
        if url in self.html:
            return "<html><head><title>Not found</title></head><body>404</body></html>"
        p = self.routes.get(url)
        if p is None:
            raise FetchError(f"HTTP 404 for {url}")
        return p.read_text()


YAHOO = {t: YAHOO_URL.format(symbol=t) for t in CIKS}
STOOQ = {t: STOOQ_URL.format(symbol=f"{t.lower()}.us") for t in CIKS}

TEST_BASKETS = {
    "version": 1, "note": "test baskets over the recorded fixtures",
    "defaults": {"months_of_history": 36, "min_constituents": 2, "price_source": "yahoo", "price_max_per_s": 2},
    "sectors": {"AI/ML": ["AAA", "BBB", "CCC"], "Fintech": ["AAA", "CCC", "DDD"]},
    "overrides": {},
}


def write_baskets(root: Path, raw: dict | None = None) -> Path:
    p = root / "rules" / "comps_baskets.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(raw or TEST_BASKETS, sort_keys=False))
    return p


def make_provider(root: Path, fetch: FakeFetch | None = None, **kw) -> tuple[PublicCompsProvider, FakeFetch]:
    fetch = fetch or FakeFetch()
    baskets = load_baskets(write_baskets(root))
    p = PublicCompsProvider(baskets, StubCompsProvider(ROOT), MarketCache(root, AS_OF), AS_OF,
                            fetch_text=fetch, max_per_s=0, price_max_per_s=0, **kw)
    return p, fetch


# ---------------------------------------------------------------- baskets file

def test_baskets_file_matches_contract_and_validates_strictly(tmp_path: Path):
    b = load_baskets(ROOT / "rules" / "comps_baskets.yaml")
    assert b.version == 1 and len(b.sectors) == 12 and b.defaults.min_constituents == 3
    assert b.defaults.months_of_history == 96 and b.defaults.price_source == "yahoo" and b.defaults.price_max_per_s == 2
    assert b.sectors["AI/ML"] == ["PLTR", "AI", "SOUN", "BBAI", "NVDA"] and "DDOG" in b.tickers
    # SQ became XYZ (Block's 2025 rename); CFLT was taken private — neither stale symbol remains
    assert "XYZ" in b.sectors["Fintech"] and "TDC" in b.sectors["Data & Analytics"]
    assert not {"SQ", "CFLT"} & set(b.tickers) and b.overrides == {} and len(b.sha256) == 64
    assert "commit message" in b.note
    with pytest.raises(ValueError, match="extra|unknown|not permitted"):
        load_baskets(write_baskets(tmp_path, dict(TEST_BASKETS, min_constituents=3)))
    with pytest.raises(ValueError, match="extra|unknown|not permitted"):        # the old key is gone
        load_baskets(write_baskets(tmp_path, dict(TEST_BASKETS, defaults=dict(TEST_BASKETS["defaults"], stooq_suffix=".us"))))
    with pytest.raises(ValueError, match="price_source"):
        load_baskets(write_baskets(tmp_path, dict(TEST_BASKETS, defaults=dict(TEST_BASKETS["defaults"], price_source="bloomberg"))))
    with pytest.raises(ValueError, match="upper-case"):
        load_baskets(write_baskets(tmp_path, dict(TEST_BASKETS, sectors={"AI/ML": ["pltr"]})))
    with pytest.raises(FileNotFoundError):
        load_baskets(tmp_path / "nope.yaml")


# ---------------------------------------------------------------- EDGAR extraction (pure)

def _facts_from(rows, concept="RevenueFromContractWithCustomerExcludingAssessedTax", **meta):
    """rows: (concept | None, start, end, $M, form). A None concept uses the default."""
    facts = {"cik": 1, "entityName": "Sample", "facts": {"us-gaap": {}}}
    for c, s, e, v, form in rows:
        node = facts["facts"]["us-gaap"].setdefault(c or concept, {"units": {"USD": []}})
        node["units"]["USD"].append({"start": s, "end": e, "val": v * 1e6, "form": form, "filed": e, **meta})
    return facts


def test_revenue_periods_merge_every_concept_and_read_by_dates_not_frames():
    concepts, periods = revenue_periods(facts("AAA"))
    assert concepts == ["RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert all(set(r) == {"start", "end", "value", "days", "filed"} for r in periods) and [r["end"] for r in periods] == sorted(r["end"] for r in periods)
    entries = facts("AAA")["facts"]["us-gaap"][concepts[0]]["units"]["USD"]
    assert sum(1 for e in entries if "frame" not in e) > 0             # frameless rows are read, not ignored...
    assert len({(r["start"], r["end"]) for r in periods}) == len(periods)   # ...and de-duplicated by period (same value re-filed)
    q = quarters_from_periods(periods)
    annual = next(e["val"] for e in entries if e.get("frame") == "CY2025")
    q123 = [next(e["val"] for e in entries if e.get("frame") == f"CY2025Q{i}") for i in (1, 2, 3)]
    assert q["2025-12-31"] == pytest.approx((annual - sum(q123)) / 1e6, abs=1e-3)   # Q4 derived from the year
    assert "2026-06-30" in q and "2026-09-30" not in q
    assert revenue_periods(facts("CCC")) == ([], [])                       # no revenue under any known concept
    with pytest.raises(ExtractionError, match="no revenue periods"):
        ttm_at([], AS_OF)


def test_ttm_is_four_consecutive_quarters_whatever_the_fiscal_calendar():
    # NVIDIA-shaped: year ends late January, 13-week quarters, and a concept switch (Revenues -> ASC 606 tag)
    old, new = "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"
    rows = [(old, "2019-01-28", "2019-04-28", 2220, "10-Q"), (old, "2019-04-29", "2019-07-28", 2579, "10-Q"),
            (old, "2019-07-29", "2019-10-27", 3014, "10-Q"), (old, "2019-01-28", "2019-10-27", 7813, "10-Q"),
            (old, "2019-01-28", "2020-01-26", 10918, "10-K"),
            (new, "2020-01-27", "2020-04-26", 3080, "10-Q"), (new, "2020-04-27", "2020-07-26", 3866, "10-Q"),
            (new, "2020-07-27", "2020-10-25", 4726, "10-Q"), (new, "2020-01-27", "2020-10-25", 11672, "10-Q"),
            (new, "2020-01-27", "2021-01-31", 16675, "10-K"),
            (new, "2021-02-01", "2021-05-02", 5661, "10-Q"), (new, "2021-05-03", "2021-08-01", 6507, "10-Q"),
            (new, "2021-02-01", "2021-08-01", 12168, "10-Q")]
    concepts, periods = revenue_periods(_facts_from(rows))
    assert concepts == [new, old]                                    # the concept in current use first
    h = RevenueHistory(periods)
    assert h.quarters["2020-01-26"] == 3105.0 and h.quarters["2021-01-31"] == 5003.0   # fiscal Q4s derived from FY − 9M
    assert h.ttm_at(date(2020, 1, 31)) == (10918.0, "2020-01-26")   # the fiscal year itself
    assert h.ttm_at(date(2020, 12, 31)) == (14777.0, "2020-10-25")  # four quarters spanning the concept switch
    assert h.ttm_at(date(2021, 9, 30)) == (21897.0, "2021-08-01")
    with pytest.raises(ExtractionError, match="no revenue period ended on or before"):
        h.ttm_at(date(2019, 1, 1))


def test_ttm_falls_back_to_fiscal_year_plus_ytd():
    # C3.ai-shaped: year ends April 30; only the year and this year's YTD are usable (a gap in the quarters)
    rows = [(None, "2024-05-01", "2025-04-30", 389, "10-K"),
            (None, "2024-05-01", "2024-10-31", 181, "10-Q"),     # prior-year six months
            (None, "2025-05-01", "2025-10-31", 203, "10-Q")]     # this year's six months
    h = RevenueHistory(revenue_periods(_facts_from(rows))[1])
    assert h.ttm_at(date(2026, 1, 31)) == (389 + 203 - 181, "2025-10-31")
    assert h.ttm_at(date(2025, 6, 30)) == (389.0, "2025-04-30")     # nothing filed since the year: the year
    with pytest.raises(ExtractionError, match="TTM through 2025-10-31 undefined"):
        RevenueHistory(revenue_periods(_facts_from(rows[:1] + rows[2:]))[1]).ttm_at(date(2026, 1, 31))   # no prior YTD
    # a restatement is kept as a second row: the latest filing wins by default, the earlier one as of its date
    early = {"start": "2026-01-01", "end": "2026-03-31", "val": 100e6, "filed": "2026-04-30", "form": "10-Q"}
    restated = dict(early, val=110e6, filed="2027-02-20", form="10-K")
    f = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [early, restated, dict(early, filed="2026-08-01")]}}}}}
    rows = revenue_periods(f)[1]
    assert rows == [{"start": "2026-01-01", "end": "2026-03-31", "value": 100.0, "days": 90, "filed": "2026-04-30"},
                    {"start": "2026-01-01", "end": "2026-03-31", "value": 110.0, "days": 90, "filed": "2027-02-20"}]
    assert RevenueHistory(rows).quarters == {"2026-03-31": 110.0}
    assert RevenueHistory(rows, filed_by=date(2026, 12, 31)).quarters == {"2026-03-31": 100.0}
    assert RevenueHistory(rows, filed_by=date(2026, 4, 1)).quarters == {}                  # nothing filed yet
    # concept tie-break: equally current concepts -> the larger latest value (a total over a component)
    fees = "RevenueFromContractWithCustomerExcludingAssessedTax"
    lender = _facts_from([(fees, "2026-01-01", "2026-03-31", 40, "10-Q"), ("Revenues", "2026-01-01", "2026-03-31", 100, "10-Q")])
    assert revenue_periods(lender)[0] == ["Revenues", fees] and revenue_periods(lender)[1][0]["value"] == 100.0


def test_shares_sum_multi_class_rows_and_fall_back_by_concept():
    concept, s = shares_series(facts("BBB"))
    assert concept == "dei:EntityCommonStockSharesOutstanding"
    assert value_at(s, AS_OF) == 200.0                              # 150 class A + 50 class B, in millions
    rows = facts("BBB")["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
    assert sum(1 for r in rows if r["end"] == s[-1]["end"]) == 2    # two rows share the cover date
    concept_a, sa = shares_series(facts("AAA"))
    assert concept_a.startswith("dei:") and value_at(sa, AS_OF) == 108.5 and value_at(sa, date(2020, 1, 1)) is None
    concept_c, sc = shares_series(facts("CCC"))
    assert concept_c == "us-gaap:CommonStockSharesOutstanding" and value_at(sc, AS_OF) == 50.0
    # diluted weighted-average fallback: a 10-Q reports 3- and 9-month averages at the same end; only the
    # quarterly frame is read, so nothing is double counted
    diluted = {"facts": {"us-gaap": {"WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
        {"start": "2026-04-01", "end": "2026-06-30", "val": 90e6, "fy": 2026, "fp": "Q2", "filed": "2026-08-01", "frame": "CY2026Q2"},
        {"start": "2026-01-01", "end": "2026-06-30", "val": 89e6, "fy": 2026, "fp": "Q2", "filed": "2026-08-01"},
    ]}}}}}
    assert shares_series(diluted) == ("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                                      [{"end": "2026-06-30", "value": 90.0, "filed": "2026-08-01"}])
    assert shares_series({"facts": {}}) == (None, [])


def test_instant_series_keeps_latest_filed_per_end():
    rows = [{"end": "2025-12-31", "val": 100e6, "fy": 2025, "fp": "FY", "filed": "2026-02-25"},
            {"end": "2025-12-31", "val": 50e6, "fy": 2025, "fp": "FY", "filed": "2000-01-01"},
            {"end": "2026-06-30", "val": 120e6, "fy": 2026, "fp": "Q2", "filed": "2026-08-05"}]
    series = summed_instant_series(rows)
    assert series == [{"end": "2025-12-31", "value": 50.0, "filed": "2000-01-01"}, {"end": "2025-12-31", "value": 100.0, "filed": "2026-02-25"},
                      {"end": "2026-06-30", "value": 120.0, "filed": "2026-08-05"}]
    assert value_at(series, date(2026, 3, 31)) == 100.0                                 # latest filing wins...
    assert value_at(series, date(2026, 3, 31), filed_by=date(2026, 1, 31)) == 50.0       # ...unless asked as of a date
    assert value_at(series, date(2026, 9, 30), filed_by=date(2026, 7, 31)) == 100.0      # Q2 not filed by end-July
    assert value_at(cash_series(facts("AAA")), date(2025, 12, 31)) > 0    # the 0.5x restated comparative lost


def test_net_cash_fallbacks():
    a = facts("AAA")
    assert net_cash_at(cash_series(a), debt_series(a), AS_OF) == pytest.approx(670.0 - 100.0)   # cash+STI − LongTermDebt
    b = facts("BBB")
    assert value_at(cash_series(b), AS_OF) == 750.0                       # cash + MarketableSecuritiesCurrent
    assert value_at(debt_series(b), AS_OF) == 1250.0                      # noncurrent + current pieces
    assert net_cash_at(cash_series(b), debt_series(b), AS_OF) == -500.0
    c = facts("CCC")
    assert debt_series(c) == [] and net_cash_at(cash_series(c), debt_series(c), AS_OF) == 120.0
    assert net_cash_at([], [], AS_OF) == 0.0

    def inst(concept, val, end="2026-06-30"):
        return {concept: {"units": {"USD": [{"end": end, "val": val * 1e6, "filed": "2026-08-01", "form": "10-Q"}]}}}
    def mk(*nodes):
        f = {}
        for n in nodes: f.update(n)
        return {"facts": {"us-gaap": f}}
    # a filer with only convertible notes (Okta, Snowflake, Hims, Planet, Nutanix): read, not zero
    only_conv = mk(inst("ConvertibleDebtNoncurrent", 1751.3))
    assert value_at(debt_series(only_conv), AS_OF) == pytest.approx(1751.3)
    # the same notes tagged under both families at one date: one instrument, counted once
    twice = mk(inst("LongTermDebtNoncurrent", 1751.3), inst("ConvertibleDebtNoncurrent", 1751.3))
    assert value_at(debt_series(twice), AS_OF) == pytest.approx(1751.3)
    # distinct borrowings: a term loan and a convertible, summed
    two = mk(inst("LongTermDebtNoncurrent", 500.0), inst("ConvertibleDebtNoncurrent", 1200.0))
    assert value_at(debt_series(two), AS_OF) == pytest.approx(1700.0)
    # a family is read first-present, never summed within itself
    both_conv = mk(inst("ConvertibleDebt", 900.0), inst("ConvertibleDebtNoncurrent", 900.0))
    assert value_at(debt_series(both_conv), AS_OF) == pytest.approx(900.0)
    assert combine_series([[{"end": "2026-03-31", "value": 1.0}], [{"end": "2026-06-30", "value": 2.0}]]) == [
        {"end": "2026-03-31", "value": 1.0, "filed": ""}, {"end": "2026-06-30", "value": 3.0, "filed": ""}]


def test_extract_is_trimmed_and_cacheable():
    x = extract(facts("AAA"))
    assert set(x) == {"extract_version", "cik", "name", "revenue_concepts", "revenue_periods",
                          "shares_concept", "shares", "shares_by_concept", "cash", "debt"}
    assert x["extract_version"] == 4        # v4 reads convertible notes into debt; v3 cached every share concept
    assert x["cik"] == "0001000001" and x["name"] == "Alpha Analytics Corp"
    assert len(json.dumps(x)) < 8000 < len(json.dumps(facts("AAA")))
    # the slim companyfacts keeps only the concepts read, with the fields read, and re-derives the same extract
    sl = slim(facts("AAA"))
    assert extract(sl) == x and len(json.dumps(sl)) <= len(json.dumps(facts("AAA")))
    assert all(set(e) <= {"start", "end", "val", "fy", "fp", "form", "filed", "frame"}
               for tax in sl["facts"].values() for node in tax.values() for es in node["units"].values() for e in es)
    assert sl["slim_version"] == 2           # a slim cut with the old keep-list is refetched, not re-derived


def test_ticker_table_and_cik_resolution():
    table = parse_company_tickers(json.loads((FIX / "company_tickers.json").read_text()))
    assert table["AAA"] == {"cik": 1000001, "title": "Alpha Analytics Corp"}
    r = resolve_ciks(["AAA", "DDD", "SQ"], table, {"SQ": {"cik": 1512673, "name": "Block, Inc."}})
    assert r["AAA"]["cik"] == 1000001 and r["DDD"] == {"cik": None, "title": None}
    assert r["SQ"] == {"cik": 1512673, "title": "Block, Inc."}
    with pytest.raises(FetchError):
        parse_company_tickers({"0": {"nope": 1}})


def test_edgar_client_sends_the_sec_user_agent(monkeypatch):
    monkeypatch.delenv(CONTACT_ENV, raising=False)
    assert user_agent().endswith(f"({DEFAULT_CONTACT})") and user_agent().startswith("hc-valuation/")
    monkeypatch.setenv(CONTACT_ENV, "jackson@example.org")
    fetch = FakeFetch()
    client = EdgarClient(fetch_text=fetch, max_per_s=0)
    assert client.user_agent == user_agent("jackson@example.org")
    assert client.company_tickers()["BBB"]["cik"] == 1000002
    assert fetch.headers[0]["User-Agent"] == "hc-valuation/" + client.user_agent.split("/", 1)[1]
    assert "(jackson@example.org)" in fetch.headers[0]["User-Agent"]
    assert extract(client.company_facts(1000002))["name"].startswith("Beta Bio")
    with pytest.raises(FetchError):
        client.company_facts(4242)          # 404
    html = FakeFetch(html={COMPANY_FACTS_URL.format(cik=1000001)})
    with pytest.raises(FetchError, match="not JSON"):
        EdgarClient(fetch_text=html, max_per_s=0).company_facts(1000001)


# ---------------------------------------------------------------- prices: Yahoo (default)

def yahoo(ticker: str) -> dict:
    return json.loads((FIX / f"yahoo_{ticker}.json").read_text())


def test_yahoo_chart_parsing_skips_null_closes_and_reports_errors():
    daily = parse_yahoo_chart(yahoo("AAA"), "AAA")
    csv = parse_daily_csv((FIX / "stooq_AAA.csv").read_text())
    assert daily == csv                                              # same recording, two envelopes
    stamps = yahoo("AAA")["chart"]["result"][0]["timestamp"]
    closes = yahoo("AAA")["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    assert None in closes and len(daily) == len(stamps) - 1        # the null (holiday) row is skipped, not zeroed
    assert "2026-09-07" not in daily and daily["2026-09-30"] == 57.43
    assert all(len(k) == 10 and date.fromisoformat(k) for k in daily)   # unix stamps -> ISO dates, UTC
    assert parse_yahoo_chart(yahoo("CCC"), "CCC") == parse_daily_csv((FIX / "stooq_CCC.csv").read_text())
    with pytest.raises(LiveFeedError, match="ZZZ: Yahoo chart error: No data found, symbol may be delisted"):
        parse_yahoo_chart(yahoo("ZZZ"), "ZZZ")
    with pytest.raises(LiveFeedError, match="no result"):
        parse_yahoo_chart({"chart": {"result": [], "error": None}}, "X")
    with pytest.raises(LiveFeedError, match="no closes"):
        parse_yahoo_chart({"chart": {"result": [{"timestamp": [1, 2], "indicators": {"quote": [{"close": [None, None]}]}}], "error": None}}, "X")
    with pytest.raises(LiveFeedError, match="not a Yahoo chart"):
        parse_yahoo_chart({"finance": {"error": "x"}}, "X")


def test_yahoo_provider_fetches_with_browser_like_headers_and_wraps_failures():
    fetch = FakeFetch()
    y = YahooPrices(fetch_text=fetch, max_per_s=0)
    assert y.daily_closes("AAA")["2026-09-30"] == 57.43 and fetch.calls == [YAHOO["AAA"]]
    assert fetch.headers[0]["User-Agent"].startswith("Mozilla/5.0 (compatible; hc-valuation/")
    assert fetch.headers[0]["Accept"] == "application/json"
    with pytest.raises(LiveFeedError, match="not JSON"):
        YahooPrices(fetch_text=FakeFetch(html={YAHOO["AAA"]}), max_per_s=0).daily_closes("AAA")
    with pytest.raises(LiveFeedError, match="AAA: ReadTimeout: timed out"):
        YahooPrices(fetch_text=FakeFetch(timeout={YAHOO["AAA"]}), max_per_s=0).daily_closes("AAA")
    with pytest.raises(LiveFeedError, match="QQQ: HTTP 404 for"):
        YahooPrices(fetch_text=FakeFetch(), max_per_s=0).daily_closes("QQQ")
    with pytest.raises(LiveFeedError, match="ZZZ: Yahoo chart error: No data found, symbol may be delisted"):
        YahooPrices(fetch_text=FakeFetch(), max_per_s=0).daily_closes("ZZZ")
    with pytest.raises(LiveFeedError, match="browser-verification page"):
        YahooPrices(fetch_text=FakeFetch(challenge={YAHOO["AAA"]}), max_per_s=0).daily_closes("AAA")


def test_price_symbol_mapping_and_factory():
    assert YahooPrices().symbol_for("BRK.B") == "BRK-B" and YahooPrices().symbol_for("pltr") == "PLTR"
    assert StooqPrices().symbol_for("BRK.B") == "brk.b.us" and StooqPrices().symbol_for("PLTR") == "pltr.us"
    assert YahooPrices().url_for("BRK.B") == YAHOO_URL.format(symbol="BRK-B")
    assert StooqPrices().url_for("AAA") == STOOQ["AAA"]
    assert PRICE_SOURCES == ("yahoo", "stooq") and DEFAULT_PRICE_SOURCE == "yahoo"
    for name in PRICE_SOURCES:
        prov = price_provider(name, max_per_s=0)
        assert isinstance(prov, PriceProvider) and prov.name == name
    assert price_provider(None).name == "yahoo" and price_provider("Stooq").name == "stooq"
    assert YahooPrices.MAX_PER_S == 2.0 and StooqPrices.MAX_PER_S == 2.0
    with pytest.raises(ValueError, match="unknown price source 'bloomberg'"):
        price_provider("bloomberg")


# ---------------------------------------------------------------- browser-challenge detection (fetch.py)

CHALLENGE = ("<!DOCTYPE html><html><head><title>Just a moment</title></head><body>"
             "<p>Please verify you are a human. JavaScript is required to continue.</p>"
             "<script>solve_challenge()</script></body></html>")


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code, self.text = status_code, text


def test_browser_challenge_predicate():
    assert is_browser_challenge(CHALLENGE) and is_browser_challenge(CHALLENGE.lower())
    assert is_browser_challenge("<html><body>Checking your browser (JavaScript)</body></html>")
    assert not is_browser_challenge("Date,Open,High,Low,Close,Volume\n2026-09-30,1,1,1,1,1")
    assert not is_browser_challenge('{"chart": {"result": [], "error": null}}')
    assert not is_browser_challenge("<html><head><title>Not found</title></head><body>404</body></html>")
    assert not is_browser_challenge("") and not is_browser_challenge("please verify the JavaScript challenge")   # not HTML
    assert browser_challenge_message("https://stooq.com/q/d/l/?s=aaa.us&i=d") == (
        "stooq.com answered with a browser-verification page; this source cannot be read by an automated client")


def test_fetch_text_reports_challenge_pages_on_any_status_and_keeps_status_errors_short(monkeypatch):
    import httpx
    url = "https://stooq.com/q/d/l/?s=aaa.us&i=d"
    responses: dict[str, FakeResponse] = {}
    monkeypatch.setattr(httpx, "get", lambda u, **kw: responses[u])

    responses[url] = FakeResponse(200, CHALLENGE)
    with pytest.raises(FetchError, match="^stooq.com answered with a browser-verification page; this source cannot be read by an automated client$"):
        fetch_text(url)
    responses[url] = FakeResponse(404, CHALLENGE)                    # what Stooq actually serves
    with pytest.raises(FetchError, match="browser-verification page"):
        fetch_text(url)
    responses[url] = FakeResponse(404, '{"chart":{"result":null,"error":{"code":"Not Found","description":"x"}}}')
    with pytest.raises(FetchError, match=f"^HTTP 404 for {re.escape(url)}$") as ex:
        fetch_text(url)
    assert "mozilla" not in str(ex.value).lower() and "\n" not in str(ex.value)
    responses[url] = FakeResponse(503, "<html><body>Service unavailable</body></html>")
    with pytest.raises(FetchError, match="^HTTP 503 for "):
        fetch_text(url)
    responses[url] = FakeResponse(200, "Date,Open,High,Low,Close,Volume\n2026-09-30,1,1,1,2,1\n")
    assert fetch_text(url).startswith("Date,")

    def boom(u, **kw):
        raise httpx.ConnectError("[Errno 101] Network is unreachable\nFor more information check: https://developer.mozilla.org/x")
    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(FetchError, match="^ConnectError: \\[Errno 101\\] Network is unreachable$"):
        fetch_text(url)


# ---------------------------------------------------------------- prices: Stooq (alternative)

def test_month_end_closes_honour_as_of():
    daily = parse_daily_csv((FIX / "stooq_AAA.csv").read_text(), "aaa.us")
    assert "2026-10-05" in daily
    unfiltered = month_end_closes(daily)
    assert "2026-10" in unfiltered and unfiltered["2026-09"] == daily["2026-09-30"]
    filtered = month_end_closes(daily, AS_OF)
    assert max(filtered) == "2026-09" and filtered["2026-09"] == daily["2026-09-30"]
    assert month_end_closes(daily, date(2026, 9, 16))["2026-09"] == daily["2026-09-15"]   # last close ≤ as_of
    assert list(filtered) == sorted(filtered)


def test_stooq_failure_paths(monkeypatch):
    def boom(url, headers=None, timeout_s=8.0):
        raise FetchError("ConnectError: simulated outage")
    monkeypatch.setattr(fetch_mod, "fetch_text", boom)             # the default seam is resolved at call time
    with pytest.raises(LiveFeedError, match="simulated outage"):
        fetch_daily_closes("aaa.us")
    with pytest.raises(LiveFeedError, match="not a Stooq CSV"):
        parse_daily_csv("<html><body>Exceeded the daily hits limit</body></html>", "x.us")
    with pytest.raises(LiveFeedError, match="no closes"):
        parse_daily_csv("Date,Open,High,Low,Close,Volume\n", "x.us")
    with pytest.raises(LiveFeedError, match="timed out"):
        fetch_daily_closes("aaa.us", fetch_text=FakeFetch(timeout={STOOQ_URL.format(symbol="aaa.us")}))
    with pytest.raises(LiveFeedError, match="zzz.us: HTTP 404"):
        fetch_daily_closes("zzz.us", fetch_text=FakeFetch())
    assert fetch_daily_closes("bbb.us", fetch_text=FakeFetch())["2026-09-30"] > 0
    assert StooqPrices(fetch_text=FakeFetch(), max_per_s=0).daily_closes("BBB")["2026-09-30"] > 0
    with pytest.raises(LiveFeedError, match="aaa.us: stooq.com answered with a browser-verification page"):
        StooqPrices(fetch_text=FakeFetch(challenge={STOOQ["AAA"]}), max_per_s=0).daily_closes("AAA")


# ---------------------------------------------------------------- provider

def test_provider_medians_the_basket_and_captures_errors_per_constituent(tmp_path: Path):
    p, fetch = make_provider(tmp_path)
    assert isinstance(p, CompsProvider) and p.reached_live and p.source == LIVE_LABEL
    assert p.price_source == "yahoo" and p.live_source == live_source("yahoo") == live_label("yahoo") == LIVE_LABEL
    assert p.is_live("AI/ML") and not p.is_live("Fintech")
    rep = p.report(positions={"AI/ML": 18, "Fintech": 10}, provider="live")
    assert set(rep) == REPORT_KEYS and rep["reached_live"] and rep["source"] == LIVE_LABEL
    assert rep["cache"] == {"dir": "data/market_cache/2026-09-30", "hit": False, "refreshable": True}
    assert rep["fetched_at"] and rep["fetched_at"].endswith("Z")
    by = {s["sector"]: s for s in rep["sectors"]}
    ai = by["AI/ML"]
    assert set(ai) == SECTOR_KEYS and ai["live"] and ai["source"] == f"{LIVE_LABEL}@2026-09" and ai["as_of_month"] == "2026-09"
    cons = {c["ticker"]: c for c in ai["constituents"]}
    assert set(cons["AAA"]) == CONSTITUENT_KEYS and cons["AAA"]["status"] == "ok" and cons["BBB"]["status"] == "ok"
    assert cons["CCC"]["status"] == "error" and "no revenue periods" in cons["CCC"]["error"]
    assert all(cons["CCC"][k] is None for k in ("price", "shares_m", "ev_to_revenue", "ttm_revenue_musd"))
    # arithmetic: EV = close × shares − net cash; EV / TTM revenue; median of the two that priced
    daily = parse_yahoo_chart(yahoo("AAA"))
    a = cons["AAA"]
    assert a["price"] == daily["2026-09-30"] and a["shares_m"] == 108.5 and a["net_cash_musd"] == 570.0
    assert a["revenue_through"] == "2026-06-30" and a["cik"] == "0001000001" and a["name"] == "Alpha Analytics Corp"
    assert a["market_cap_musd"] == pytest.approx(a["price"] * 108.5, abs=1e-3)
    assert a["ev_to_revenue"] == pytest.approx((a["market_cap_musd"] - 570.0) / a["ttm_revenue_musd"], abs=0.01)
    b = cons["BBB"]
    assert b["shares_m"] == 200.0 and b["net_cash_musd"] == -500.0
    assert ai["ev_to_revenue"] == pytest.approx((a["ev_to_revenue"] + b["ev_to_revenue"]) / 2, abs=0.01)
    assert ai["history"]["2026-09"] == ai["ev_to_revenue"] and list(ai["history"]) == sorted(ai["history"])
    assert ai["counts"]["2026-09"] == 2 and set(ai["counts"]) == set(ai["history"]) and p.counts("AI/ML") == ai["counts"]
    assert p.counts("Consumer") == {}                                    # a fixture sector has no constituent counts
    assert len(ai["history"]) <= 96 and "2026-10" not in ai["history"] and ai["history"]["2024-01"] > 0
    assert ai["prior_quarter"] == ai["history"]["2026-06"] and ai["qoq_pct"] == pytest.approx(ai["ev_to_revenue"] / ai["prior_quarter"] - 1, abs=1e-3)
    # the engine-facing surface agrees with the report
    comps = p.sector_multiples(AS_OF)
    assert comps["AI/ML"].ev_to_arr == ai["ev_to_revenue"] and comps["AI/ML"].source == f"{LIVE_LABEL}@2026-09"
    assert p.history("AI/ML") == ai["history"]
    # positions from the snapshot, sorted descending; a fixture-only sector shows fixture rows
    assert [s["sector"] for s in rep["sectors"][:2]] == ["AI/ML", "Fintech"] and by["Consumer"]["positions"] == 0
    assert by["Consumer"]["constituents"][0]["status"] == "fixture" and not by["Consumer"]["live"]
    # the ticker table was fetched once, then one companyfacts and one chart per resolvable ticker (DDD: neither)
    assert fetch.calls.count(COMPANY_TICKERS_URL) == 1
    assert sum(1 for u in fetch.calls if "companyfacts" in u) == 3 and sum(1 for u in fetch.calls if "finance.yahoo" in u) == 3
    assert not any("stooq" in u for u in fetch.calls)


def test_stooq_as_the_alternative_price_source(tmp_path: Path):
    p, fetch = make_provider(tmp_path, price_source="stooq")
    assert p.reached_live and p.source == LIVE_STOOQ and p.price_source == "stooq"
    assert sorted(u for u in fetch.calls if "stooq" in u) == sorted(STOOQ.values()) and not any("yahoo" in u for u in fetch.calls)
    rep = p.report()
    assert rep["source"] == LIVE_STOOQ
    cons = {c["ticker"]: c for s in rep["sectors"] if s["sector"] == "AI/ML" for c in s["constituents"]}
    assert cons["AAA"]["status"] == "ok" and cons["AAA"]["price"] == 57.43
    assert cons["CCC"]["status"] == "error" and "no revenue periods" in cons["CCC"]["error"]   # priced, but no revenue
    assert MarketCache(tmp_path, AS_OF).read_meta()["price_source"] == "stooq"
    assert (MarketCache(tmp_path, AS_OF).dir / "prices" / "CCC.json").is_file()
    # the same numbers whichever envelope carried the closes
    q, _ = make_provider(tmp_path / "y")
    assert q.sector_multiples(AS_OF)["AI/ML"].ev_to_arr == p.sector_multiples(AS_OF)["AI/ML"].ev_to_arr
    assert q.sector_multiples(AS_OF)["AI/ML"].source == f"{LIVE_LABEL}@2026-09"
    assert p.sector_multiples(AS_OF)["AI/ML"].source == f"{LIVE_STOOQ}@2026-09"


def test_min_constituents_keeps_the_fixture_for_that_sector(tmp_path: Path):
    p, _ = make_provider(tmp_path)
    stub = StubCompsProvider(ROOT)
    rep = p.report()
    fin = next(s for s in rep["sectors"] if s["sector"] == "Fintech")
    assert not fin["live"] and fin["source"].startswith("fixture:pitchbook@2026-09")
    assert fin["ev_to_revenue"] == stub.sector_multiples(AS_OF)["Fintech"].ev_to_arr
    statuses = {c["ticker"]: c["status"] for c in fin["constituents"]}
    assert statuses == {"AAA": "ok", "CCC": "error", "DDD": "error"}
    ddd = next(c for c in fin["constituents"] if c["ticker"] == "DDD")
    assert "cannot resolve" in ddd["error"]
    assert any("Fintech: only 1 of 3" in e and "min_constituents 2" in e for e in rep["errors"])
    assert p.sector_multiples(AS_OF)["Fintech"].source == stub.sector_multiples(AS_OF)["Fintech"].source
    assert p.history("Fintech") == stub.history("Fintech")
    assert len(fin["history"]) == 36                                     # fixture history trimmed to months_of_history


def test_cache_hit_makes_no_network_call_and_refresh_refetches(tmp_path: Path):
    p1, f1 = make_provider(tmp_path)
    assert not p1.cache_hit and f1.calls
    cache = MarketCache(tmp_path, AS_OF)
    assert cache.exists() and (cache.dir / "edgar" / "AAA.json").is_file() and (cache.dir / "prices" / "CCC.json").is_file()
    assert not (cache.dir / "stooq").exists()
    meta = cache.read_meta()
    assert set(meta) == {"fetched_at", "as_of", "user_agent", "baskets_sha256", "price_source"} and meta["as_of"] == "2026-09-30"
    assert meta["price_source"] == "yahoo"
    assert cache.read_tickers()["DDD"] == {"cik": None, "title": None}     # a miss is recorded, not retried
    assert set(cache.read_prices("AAA")) <= set(months_back(AS_OF, 60)) and "2026-10" not in cache.read_prices("AAA")
    committed = [f for f in cache.dir.rglob("*.json") if "edgar_raw" not in f.parts]
    assert sum(f.stat().st_size for f in committed) < 60_000            # trimmed extracts, not payloads
    assert (cache.dir / "edgar_raw" / "AAA.json").is_file()              # the slim facts sit beside them, git-ignored
    assert "edgar_raw/" in (ROOT / ".gitignore").read_text()

    p2, f2 = make_provider(tmp_path)
    assert f2.calls == [] and p2.cache_hit and p2.report()["cache"]["hit"]
    assert p2.report()["fetched_at"] == meta["fetched_at"]
    assert p2.report()["sectors"] == p1.report()["sectors"] and p2.sector_multiples(AS_OF) == p1.sector_multiples(AS_OF)

    p3, f3 = make_provider(tmp_path, refresh=True)
    assert not p3.cache_hit and COMPANY_TICKERS_URL in f3.calls and len(f3.calls) == len(f1.calls)
    assert cache.read_meta()["fetched_at"] >= meta["fetched_at"]


def test_partial_cache_fetches_only_what_is_missing(tmp_path: Path):
    make_provider(tmp_path)
    cache = MarketCache(tmp_path, AS_OF)
    (cache.dir / "prices" / "BBB.json").unlink()
    (cache.dir / "edgar" / "AAA.json").unlink()                          # extract gone, slim facts still there
    p, f = make_provider(tmp_path)
    assert f.calls == [YAHOO["BBB"]], "a lost extract is re-derived from the slim facts, not refetched"
    assert not p.cache_hit and p.reached_live and (cache.dir / "prices" / "BBB.json").is_file()
    assert (cache.dir / "edgar" / "AAA.json").is_file()
    # an extract written by the earlier, frame-keyed extraction is treated as missing and re-derived too
    (cache.dir / "edgar" / "AAA.json").write_text(json.dumps({"cik": "0001000001", "revenue_quarterly": {"CY2026Q2": 1.0}}))
    assert cache.read_edgar("AAA") is None and "AAA" in cache.missing(["AAA"])[0]
    p, f = make_provider(tmp_path)
    assert f.calls == [] and "revenue_periods" in cache.read_edgar("AAA")
    # slim facts gone as well: only then is SEC asked again
    (cache.dir / "edgar" / "AAA.json").unlink()
    (cache.dir / "edgar_raw" / "AAA.json").unlink()
    p, f = make_provider(tmp_path)
    assert f.calls == [COMPANY_FACTS_URL.format(cik=1000001)]


def test_cache_written_by_another_price_source_is_a_miss_for_prices_only(tmp_path: Path, caplog):
    make_provider(tmp_path, price_source="stooq")
    cache = MarketCache(tmp_path, AS_OF)
    assert cache.price_source() == "stooq" and cache.prices_match("stooq") and not cache.prices_match("yahoo")
    assert (cache.dir / "prices" / "CCC.json").is_file()
    (cache.dir / "prices" / "STALE.json").write_text("{}")             # anything the other provider left behind
    with caplog.at_level("WARNING"):
        p, f = make_provider(tmp_path)                    # default: yahoo
    assert "holds stooq closes; refetching prices from yahoo" in caplog.text
    assert sorted(f.calls) == sorted(YAHOO.values())     # no EDGAR call: the fundamentals half was a hit
    assert not p.cache_hit and p.reached_live and p.source == LIVE_LABEL
    assert cache.read_meta()["price_source"] == "yahoo" and cache.read_meta()["fetched_at"]
    assert not (cache.dir / "prices" / "STALE.json").exists()          # the price half was cleared, then rewritten
    assert cache.read_prices("CCC")["2026-09"] > 0
    p2, f2 = make_provider(tmp_path)
    assert f2.calls == [] and p2.cache_hit
    p3, f3 = make_provider(tmp_path, price_source="stooq")
    assert sorted(f3.calls) == sorted(STOOQ.values()) and p3.source == LIVE_STOOQ


def test_price_source_selection_default_kwarg_env(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(PRICE_SOURCE_ENV, raising=False)
    assert resolve_price_source(None) is None and resolve_price_source("Stooq") == "stooq"
    monkeypatch.setenv(PRICE_SOURCE_ENV, "stooq")
    assert resolve_price_source(None) == "stooq" and resolve_price_source("yahoo") == "yahoo"   # argument wins

    root = tmp_path / "root"
    root.mkdir()
    make_provider(root, price_source="stooq")             # a complete stooq cache under root/data/market_cache

    def boom(url, headers=None, timeout_s=8.0):
        raise FetchError("network")
    monkeypatch.setattr(fetch_mod, "fetch_text", boom)
    paths = RunPaths.default(ROOT)
    paths.root = root
    r = execute(paths, provider="live", adjudicate=False)                       # env: stooq -> cache hit, offline
    assert r.run.manifest.market_data_source == LIVE_STOOQ and r.market_report["source"] == LIVE_STOOQ
    assert r.market_report["cache"]["hit"] is True

    monkeypatch.setenv(PRICE_SOURCE_ENV, "yahoo")                               # env: yahoo -> price half refetched, fails
    r = execute(paths, provider="live", adjudicate=False)
    assert r.run.manifest.market_data_source == "stub" and not r.market_report["reached_live"]
    assert any(e.startswith("3 tickers: price fetch failed (yahoo): network") for e in r.market_report["errors"])
    cache = MarketCache(root, AS_OF)                                            # nothing answered: the stooq half survives
    assert cache.price_source() == "stooq" and cache.read_prices("AAA")["2026-09"] == 57.43

    monkeypatch.delenv(PRICE_SOURCE_ENV, raising=False)
    from hc_valuation.config import load_config
    from hc_valuation.ingest.reader import read_workbook
    cfg = load_config(ROOT / "rules" / "2026Q3.yaml")
    snapshot, feed = read_workbook(ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx", cfg)
    asm = assemble_market_data(cfg, root, snapshot, feed, provider="live", price_source="stooq")   # kwarg: stooq
    assert asm.label == LIVE_STOOQ and asm.report["source"] == LIVE_STOOQ
    with pytest.raises(ValueError, match="unknown price source"):
        make_provider(tmp_path / "bad", price_source="bloomberg")
    asm = assemble_market_data(cfg, root, snapshot, feed, provider="live", price_source="bloomberg")
    assert asm.label == "stub" and any("unknown price source 'bloomberg'" in e for e in asm.report["errors"])


def test_one_constituent_timing_out_does_not_stop_the_sector(tmp_path: Path):
    fetch = FakeFetch(timeout={COMPANY_FACTS_URL.format(cik=1000002)}, html={YAHOO["AAA"]})
    p, _ = make_provider(tmp_path, fetch)
    cons = {c["ticker"]: c for s in p.report()["sectors"] if s["sector"] == "AI/ML" for c in s["constituents"]}
    assert cons["BBB"]["status"] == "error" and "timed out" in cons["BBB"]["error"]
    assert cons["AAA"]["status"] == "error" and cons["AAA"]["error"].startswith("price fetch failed (yahoo): response is not JSON")
    assert not p.reached_live and p.source == StubCompsProvider(ROOT).source     # nobody priced: < min_constituents
    assert not (MarketCache(tmp_path, AS_OF).dir / "edgar" / "BBB.json").exists()   # a failure is not cached
    assert len(p.report()["errors"]) == len(p.errors)                                # three different messages: nothing collapsed


def test_source_wide_price_outage_is_one_finding(tmp_path: Path):
    fetch = FakeFetch(challenge=set(YAHOO.values()))
    p, _ = make_provider(tmp_path, fetch)
    assert not p.reached_live
    tail = "price fetch failed (yahoo): query1.finance.yahoo.com answered with a browser-verification page; this source cannot be read by an automated client"
    assert sum(1 for e in p.errors if e.endswith(tail)) == 3                          # raw: one per ticker
    rep = p.report()
    collapsed = [e for e in rep["errors"] if tail in e]
    assert collapsed == [f"3 tickers: {tail} [AAA, BBB, CCC]"]
    assert any(e.startswith("DDD: EDGAR cannot resolve") for e in rep["errors"])     # a lone ticker line stays
    assert any(e.startswith("AI/ML: only 0 of 3") for e in rep["errors"])             # sector notes untouched
    cons = {c["ticker"]: c for s in rep["sectors"] if s["sector"] == "AI/ML" for c in s["constituents"]}
    assert cons["AAA"]["error"] == tail                                               # per-constituent detail kept


def test_collapse_errors_helper():
    assert COLLAPSE_AT == 3
    same = [f"{t}: price fetch failed (stooq): stooq.com answered with a browser-verification page" for t in ("AAA", "BRK.B", "XYZ")]
    other = ["DDD: EDGAR cannot resolve ticker", "Fintech: only 1 of 3 constituents have data", "company_tickers.json: HTTP 503"]
    out = collapse_errors([other[0], *same[:2], other[1], same[2], other[2]])
    assert out == [other[0], f"3 tickers: {same[0].split(': ', 1)[1]} [AAA, BRK.B, XYZ]", other[1], other[2]]
    assert collapse_errors(same[:2]) == same[:2] and collapse_errors([]) == []
    assert collapse_errors(same, at=2)[0].startswith("3 tickers: ")
    assert collapse_errors(["AI/ML: no basket value"] * 3) == ["AI/ML: no basket value"] * 3   # a sector is not a ticker


def test_full_failure_falls_back_to_the_fixture_everywhere(tmp_path: Path, monkeypatch, caplog):
    p, f = make_provider(tmp_path, FakeFetch(fail_all=True))
    assert not p.reached_live and p.source == StubCompsProvider(ROOT).source and not p.fetched_at
    assert p.errors and all(not s["live"] for s in p.report()["sectors"])
    assert p.sector_multiples(AS_OF) == StubCompsProvider(ROOT).sector_multiples(AS_OF)
    assert not MarketCache(tmp_path, AS_OF).exists()                     # nothing fetched, nothing written

    # through the assembler and the pipeline: manifest says `stub`, errors are listed, the run is unchanged
    def boom(url, headers=None, timeout_s=8.0):
        raise FetchError("ConnectError: simulated outage")
    monkeypatch.setattr(fetch_mod, "fetch_text", boom)
    root = tmp_path / "root"
    root.mkdir()
    write_baskets(root)
    paths = RunPaths.default(ROOT)
    paths.root = root
    with caplog.at_level("WARNING"):
        r = execute(paths, provider="live", adjudicate=False)
    assert r.run.manifest.market_data_source == "stub" and r.run.totals.dispositions == BASELINE
    rep = r.market_report
    assert rep["provider"] == "live" and rep["source"] == "stub" and not rep["reached_live"]
    assert rep["cache"]["hit"] is False and rep["fetched_at"] is None
    assert any("company_tickers.json" in e for e in rep["errors"]) and any("cannot resolve CIK" in e for e in rep["errors"])
    assert any("min_constituents" in e for e in rep["errors"])
    assert "falling back" in caplog.text


def test_provider_names(monkeypatch):
    monkeypatch.delenv("HC_MARKET_PROVIDER", raising=False)
    assert resolve_provider("pitchbook") == "pitchbook" and resolve_provider("stooq") == "live"
    assert LIVE_LABEL_PREFIX == "live:edgar+" and live_label("yahoo") == LIVE_LABEL and live_source("stooq") == LIVE_STOOQ


def test_pitchbook_is_not_configured_and_never_stops_a_run(tmp_path: Path):
    paths = RunPaths.default(ROOT)
    paths.root = tmp_path
    r = execute(paths, provider="pitchbook", adjudicate=False)
    assert r.run.manifest.market_data_source == "stub" and r.run.totals.dispositions == BASELINE
    assert r.market_report["provider"] == "pitchbook" and r.market_report["source"] == "stub"
    assert any("PITCHBOOK_API_KEY" in e and "connectors/pitchbook.py" in e for e in r.market_report["errors"])


def test_assembler_keeps_the_two_tuple_and_carries_the_report():
    from hc_valuation.config import load_config
    from hc_valuation.ingest.reader import read_workbook
    cfg = load_config(ROOT / "rules" / "2026Q3.yaml")
    snapshot, feed = read_workbook(ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx", cfg)
    asm = assemble_market_data(cfg, ROOT, snapshot, feed, provider="stub")
    assert isinstance(asm, MarketAssembly)
    market, label = asm
    assert label == "stub" and market.as_of == AS_OF and asm.report["provider"] == "stub"
    assert asm.report["used_by"]["multiple_mode"] == "relative_to_comps" and asm.report["used_by"]["calibration_enabled"] is True
    assert "relative_to_comps" in asm.report["used_by"]["note"]


# ---------------------------------------------------------------- /api/market

def _paths(tmp_path: Path, root: Path | None = None) -> RunPaths:
    data = tmp_path / "data"
    if not data.exists():
        shutil.copytree(ROOT / "data", data, ignore=shutil.ignore_patterns("sample_run.json", "market_cache", "overrides.yaml", "published", "open_items_carry.yaml", "Q? ???? *.xlsx"))
    return RunPaths(root=root or ROOT, policy=ROOT / "rules" / "2026Q3.yaml", workbook=data / "HC_Mock_Portfolio_Data.xlsx",
                    overrides=data / "overrides.yaml", proposals_dir=data / "proposals", precedent=data / "precedent.yaml",
                    open_items_carry=data / "open_items_carry.yaml")


def test_api_market_stub_shape(tmp_path: Path):
    client = TestClient(create_app(_paths(tmp_path), static_dir=tmp_path / "no-static"))
    rep = client.get("/api/market").json()
    assert set(rep) == REPORT_KEYS
    assert rep["provider"] == "stub" and rep["source"] == "stub" and rep["reached_live"] is False
    assert rep["fetched_at"] is None and rep["cache"] is None and rep["errors"] == []
    assert rep["as_of"] == "2026-09-30" and rep["baskets_file"] == "rules/comps_baskets.yaml"
    assert set(rep["used_by"]) == {"multiple_mode", "calibration_enabled", "note"}
    positions = [s["positions"] for s in rep["sectors"]]
    assert positions == sorted(positions, reverse=True) and rep["sectors"][0] == {**rep["sectors"][0], "sector": "AI/ML", "positions": 18}
    for s in rep["sectors"]:
        assert set(s) == SECTOR_KEYS and s["live"] is False and s["source"] == "fixture:pitchbook@2026-09"
        assert s["as_of_month"] == "2026-09" and s["ev_to_revenue"] == s["history"]["2026-09"]
        assert len(s["history"]) == 93 and list(s["history"]) == sorted(s["history"]) and s["qoq_pct"] is not None
        for c in s["constituents"]:
            assert set(c) == CONSTITUENT_KEYS and c["status"] == "fixture" and c["ev_to_revenue"] is None and c["error"] is None
    ai = rep["sectors"][0]
    assert [c["ticker"] for c in ai["constituents"]] == ["PLTR", "AI", "SOUN", "BBAI"]
    assert client.get("/api/run").json()["manifest"]["market_data_source"] == "stub"


def test_api_market_live_from_cache_without_network(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    make_provider(root)                                  # populates root/data/market_cache/2026-09-30 from the recordings

    def boom(url, headers=None, timeout_s=8.0):
        raise AssertionError(f"network call attempted: {url}")
    monkeypatch.setattr(fetch_mod, "fetch_text", boom)

    client = TestClient(create_app(_paths(tmp_path, root), provider="live", static_dir=tmp_path / "no-static"))
    rep = client.get("/api/market").json()
    assert rep["provider"] == "live" and rep["source"] == LIVE_LABEL and rep["reached_live"] is True
    assert rep["cache"] == {"dir": "data/market_cache/2026-09-30", "hit": True, "refreshable": True} and rep["fetched_at"]
    by = {s["sector"]: s for s in rep["sectors"]}
    assert by["AI/ML"]["live"] and by["AI/ML"]["positions"] == 18 and by["AI/ML"]["source"] == f"{LIVE_LABEL}@2026-09"
    assert not by["Fintech"]["live"] and by["Fintech"]["positions"] == 10
    assert {c["ticker"]: c["status"] for c in by["AI/ML"]["constituents"]} == {"AAA": "ok", "BBB": "ok", "CCC": "error"}
    assert not any("fetch failed" in e for e in rep["errors"])
    run = client.get("/api/run").json()
    assert run["manifest"]["market_data_source"] == LIVE_LABEL
    # comps are a screen, never a mark: no number moves; the screens on the one live sector re-bound to its
    # live median (relative_to_comps), every other sector keeps the absolute bounds
    stub = execute(_paths(tmp_path, root), provider="stub").run
    assert run["totals"]["proposed_nav"] == pytest.approx(stub.totals.proposed_nav) and run["totals"]["booked_nav"] == pytest.approx(stub.totals.booked_nav)
    live_flags = [f for c in run["companies"] for f in c["flags"] if f["rule_id"] in ("X-401", "X-402") and c["sector"] == "AI/ML"]
    other_flags = [f for c in run["companies"] for f in c["flags"] if f["rule_id"] in ("X-401", "X-402") and c["sector"] != "AI/ML"]
    assert live_flags and all(f["evidence"]["basis"] == "live sector median" for f in live_flags)
    assert all(f["evidence"]["basis"] == "absolute policy bound" for f in other_flags)
    by_stub = {c.company: {f.rule_id for f in c.flags} for c in stub.companies}
    for c in run["companies"]:
        if c["sector"] != "AI/ML":
            assert {f["rule_id"] for f in c["flags"]} == by_stub[c["company"]], c["company"]


def test_static_report_inlines_the_market_report(tmp_path: Path):
    r = execute(_paths(tmp_path), adjudicate=False)
    rep = dict(r.market_report, errors=["<script>alert(1)</script>"])
    html = write_static_report(r.run, tmp_path / "report.html", tmp_path / "no-static", None, rep).read_text()
    assert "window.__HC_MARKET__ = " in html and "window.__HC_RUN__ = " in html
    assert "</script>alert" not in html and "\\u003cscript>alert" in html
    assert "window.__HC_MARKET__" not in write_static_report(r.run, tmp_path / "r2.html", None).read_text()


def test_cli_market_json_parses_and_text_lists_sectors():
    runner = CliRunner()
    r = runner.invoke(cli_app, ["market", "--json"])
    assert r.exit_code == 0, r.output
    rep = json.loads(r.output)
    assert rep["provider"] == "stub" and len(rep["sectors"]) == 12
    r = runner.invoke(cli_app, ["market"])
    assert r.exit_code == 0 and "AI/ML" in r.output and "fixture:pitchbook@2026-09" in r.output and "provider stub" in r.output
    r = runner.invoke(cli_app, ["market", "--provider", "pitchbook"])
    assert r.exit_code == 0 and "PITCHBOOK_API_KEY" in r.output
    r = runner.invoke(cli_app, ["market", "--price-source", "stooq"])           # accepted; irrelevant to the stub
    assert r.exit_code == 0 and "provider stub" in r.output


def test_cli_market_live_prints_collapsed_errors(monkeypatch, tmp_path: Path):
    """A source-wide outage is one line in the errors block, not one per ticker. The run is
    rooted in a scratch copy of the repo with no market cache (a checkout that has done a real
    live run carries one under data/market_cache/, which would satisfy some tickers from disk),
    so every URL goes through the (replaced) seam and nothing is written into the repo."""
    monkeypatch.delenv(PRICE_SOURCE_ENV, raising=False)
    scratch = tmp_path / "root"
    (scratch / "rules").mkdir(parents=True)
    for f in (ROOT / "rules").glob("*.yaml"):
        shutil.copy(f, scratch / "rules" / f.name)
    shutil.copytree(ROOT / "data", scratch / "data", ignore=shutil.ignore_patterns("sample_run.json", "market_cache", "published", "overrides.yaml", "published", "open_items_carry.yaml", "Q? ???? *.xlsx"))
    import hc_valuation.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "repo_root", lambda: scratch)
    import hc_valuation.config as config_mod
    monkeypatch.setattr(config_mod, "repo_root", lambda: scratch)

    def challenge(url, headers=None, timeout_s=8.0):
        raise FetchError(browser_challenge_message(url))
    monkeypatch.setattr(fetch_mod, "fetch_text", challenge)
    r = CliRunner().invoke(cli_app, ["market", "--provider", "live"])
    assert r.exit_code == 0, r.output
    n = len(load_baskets(ROOT / "rules" / "comps_baskets.yaml").tickers)
    assert f"{n} tickers: EDGAR ticker table unavailable; cannot resolve CIK [" in r.output
    assert r.output.count("cannot resolve CIK") == 1 and "www.sec.gov answered with a browser-verification page" in r.output
    assert "source stub" in r.output and not (scratch / "data" / "market_cache" / "2026-09-30").exists()


def test_stub_market_report_helper_direct():
    rep = stub_market_report(StubCompsProvider(ROOT), AS_OF, positions={"AI/ML": 3}, months_of_history=12)
    assert rep["sectors"][0]["sector"] == "AI/ML" and len(rep["sectors"][0]["history"]) == 12


def test_multi_class_total_row_is_not_double_counted():
    """A filer that tags Class A, Class B *and* the total for the same date must not have the
    total added to the classes (observed pattern; guarded by the 0.5% total-row rule)."""
    from hc_valuation.connectors.edgar import summed_instant_series

    rows = [
        {"end": "2026-06-30", "val": 1_500_000_000, "fy": 2026, "fp": "Q2", "filed": "2026-08-05"},   # class A
        {"end": "2026-06-30", "val": 100_000_000, "fy": 2026, "fp": "Q2", "filed": "2026-08-05"},     # class B
        {"end": "2026-06-30", "val": 1_600_000_000, "fy": 2026, "fp": "Q2", "filed": "2026-08-05"},   # the total, also tagged
        {"end": "2026-03-31", "val": 1_450_000_000, "fy": 2026, "fp": "Q1", "filed": "2026-05-05"},   # class A only
        {"end": "2026-03-31", "val": 100_000_000, "fy": 2026, "fp": "Q1", "filed": "2026-05-05"},     # class B
    ]
    series = {r["end"]: r["value"] for r in summed_instant_series(rows)}
    assert series["2026-06-30"] == 1600.0      # total row recognised, classes not added on top
    assert series["2026-03-31"] == 1550.0      # plain multi-class sum


def test_real_edgar_shape_palantir_revenue_ttm():
    """Values as served by data.sec.gov for CIK 1321655 on 2026-09-04 (companyconcept payload,
    duplicates across filings, frame only on the de-duplicated row, Q4 never framed)."""
    from datetime import date
    from hc_valuation.connectors import edgar

    rows = [("2025-01-01", "2025-03-31", 883855000, "CY2025Q1"), ("2025-04-01", "2025-06-30", 1003697000, "CY2025Q2"),
            ("2025-07-01", "2025-09-30", 1181092000, "CY2025Q3"), ("2025-01-01", "2025-12-31", 4475446000, "CY2025"),
            ("2026-01-01", "2026-03-31", 1632583000, "CY2026Q1"), ("2026-04-01", "2026-06-30", 1935464000, "CY2026Q2"),
            ("2026-01-01", "2026-06-30", 3568047000, None), ("2025-01-01", "2025-09-30", 3068644000, None),
            ("2025-01-01", "2025-03-31", 883855000, None)]
    entries = [{"start": s, "end": e, "val": v, "fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-08-04",
                **({"frame": f} if f else {})} for s, e, v, f in rows]
    facts = {"cik": 1321655, "entityName": "Palantir Technologies Inc.",
             "facts": {"us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": entries}}}}}
    concepts, periods = edgar.revenue_periods(facts)
    assert concepts == ["RevenueFromContractWithCustomerExcludingAssessedTax"]
    h = edgar.RevenueHistory(periods)
    assert h.quarters["2025-12-31"] == 1406.802             # 4475.446 - 883.855 - 1003.697 - 1181.092 (FY − 9M)
    assert h.ttm_at(date(2026, 9, 30)) == (6155.941, "2026-06-30")
    assert h.ttm_at(date(2025, 12, 31)) == (4475.446, "2025-12-31")


def test_committed_cache_carries_convertible_notes_for_the_names_that_issue_them():
    """A regression pin on the cache in git, no network. The extractor once read only LongTermDebt*
    and left 15 of 54 constituents with no debt series at all; five of them carry convertibles
    (confirmed against SEC's companyconcept endpoint), so net cash was overstated and their
    multiples understated — Okta *was* the May-2021 Cybersecurity median, at 29.5x instead of 31.4x.
    If a future extractor change drops the convertible concepts, this is what fails."""
    from hc_valuation.config import repo_root
    from hc_valuation.connectors.cache import MarketCache
    cache = MarketCache(repo_root(), date(2026, 9, 30))
    if not cache.exists():
        pytest.skip("no committed live cache on this checkout")
    expect = {  # ticker: (a date SEC reports, the carrying value in $M, tolerance)
        "OKTA": ("2021-04-30", 1772.1, 1.0),   # 1,751.3 non-current + 20.8 current, filed 2021-05-27
        "SNOW": ("2026-07-31", 2284.0, 5.0),
        "HIMS": ("2026-06-30", 1365.0, 5.0),
        "PL":   ("2026-07-31", 448.0, 5.0),
    }
    for t, (end, want, tol) in expect.items():
        ext = cache.read_edgar(t)
        assert ext is not None, f"{t}: no current extract in the cache (extract_version {EXTRACT_VERSION} expected)"
        rows = [r for r in ext["debt"] if r["end"] == end]
        assert rows, f"{t}: no debt row at {end} — the convertible concepts are not being read"
        assert rows[-1]["value"] == pytest.approx(want, abs=tol), f"{t} at {end}"
    # and the slim beside it was cut with the current keep-list, so a re-derive cannot lose them
    raw = cache.read_edgar_raw("OKTA")
    assert raw is not None and raw.get("slim_version") == SLIM_VERSION
