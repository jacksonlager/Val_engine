"""Connector Protocols — the only shape the rest of the package knows about a data vendor.

Each Protocol documents the *real* vendor response it models so that a live connector
can be written against the vendor's payload while the stub in `stubs.py` keeps serving
the same-shaped fixture. Nothing here touches `engine/`: the engine receives an
already-fetched `MarketData` value object assembled in `connectors/__init__.py`.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable

from ..engine.models import MarketQuote, SectorComp


@runtime_checkable
class MarketDataProvider(Protocol):
    """Price a listed position at a measurement date.

    Models a quote endpoint such as Stooq's daily CSV (`Date,Open,High,Low,Close,Volume`,
    one row per trading day, no envelope) or a S&P Capital IQ / Bloomberg pricing call
    (`{"identifier": ..., "asOfDate": ..., "close": ..., "sharesOutstanding": ...,
    "marketCap": ...}`). The connector is responsible for turning a per-share close into a
    market capitalisation in USD millions; the engine only ever sees `MarketQuote`.

    Returns `None` when the company cannot be priced. A synthetic ticker (every company in
    this workbook is fictional) is *never* priced from a live feed — the stub seeds it to
    the IPO print and says so in `MarketQuote.note`.
    """

    def quote(self, company: str, as_of: date) -> MarketQuote | None: ...


@runtime_checkable
class CompsProvider(Protocol):
    """Sector-level public-comparable multiples with a monthly history.

    Models a PitchBook "Public Comps" export: an envelope
    (`requestId`, `asOfDate`, `currency`, `units`, `pagination`) around `items[]`, each item
    a sector with `evToNtmRevenue: {median, p25, p75}`, its constituents and a monthly
    `history.series` keyed `YYYY-MM`. Sector labels align to the workbook's `Sector`
    column — comps map off that column, never off the company name (policy section 7).

    `sector_multiples(as_of)` returns the multiple in force at the measurement date (the
    latest month <= as_of); `history(sector)` returns the whole monthly series so M-080 can
    read the multiple at a stale round's date as well as today's.
    """

    def sector_multiples(self, as_of: date) -> dict[str, SectorComp]: ...

    def history(self, sector: str) -> dict[str, float]: ...


@runtime_checkable
class CompanyMetricsProvider(Protocol):
    """Portfolio-company operating metrics as a monitoring vendor returns them.

    Models a Foresight-style payload: `companies[]` with `companyId`, `name`,
    `reportingPeriod` and a `metrics` object (`arr`, `arrGrowthYoY`, `grossMargin`,
    `netBurn`, `cash`, `headcount`, `netRevenueRetention`) plus the `sourceDocument` and a
    `confidence` label (`reported` | `estimated` | `public_filing`). Used for display and
    cross-checks against the workbook only — the workbook remains the marking input, so a
    vendor's restatement can never silently move a mark.
    """

    def metrics(self, company: str) -> dict[str, Any] | None: ...


@runtime_checkable
class NewsSignalProvider(Protocol):
    """Dated qualitative signals about a portfolio company.

    Models an AlphaSense search result: `results[]` with `documentId`, `publishedAt`
    (ISO-8601), `company`, `sourceType` (`news` | `filing` | `broker_research`), `source`,
    `sentiment` in [-1, 1], `relevance` in [0, 1], `title`, `snippet`, `topics[]`. Signals
    are surfaced beside a position for the reviewer; like X-105 they exist so a human reads
    the sentence, and they never touch a number.
    """

    def signals(self, company: str, since: date) -> list[dict[str, Any]]: ...
