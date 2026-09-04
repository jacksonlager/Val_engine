"""Stooq daily closes — kept as the alternative price source (`--price-source stooq`).

    https://stooq.com/q/d/l/?s=<symbol>&i=d   ->   Date,Open,High,Low,Close,Volume

The implementation lives in `prices.py` (`StooqPrices`); this module keeps the earlier
function-style names. Since September 2026 the host answers non-browser clients with a
JavaScript browser-verification page; `fetch.py` reports that as such, and nothing here
tries to get around it.
"""
from __future__ import annotations

from .fetch import DEFAULT_TIMEOUT_S, FetchText, LiveFeedError
from .prices import STOOQ_URL, StooqPrices, month_end_closes, parse_daily_csv


def fetch_daily_closes(symbol: str, timeout_s: float = DEFAULT_TIMEOUT_S, *,
                       fetch_text: FetchText | None = None) -> dict[str, float]:
    """`YYYY-MM-DD -> close` for one Stooq symbol (`aaa.us`). Raises LiveFeedError on any failure."""
    ticker = symbol[:-len(StooqPrices.SUFFIX)] if symbol.lower().endswith(StooqPrices.SUFFIX) else symbol
    return StooqPrices(fetch_text=fetch_text, timeout_s=timeout_s, max_per_s=0).daily_closes(ticker)


__all__ = ["STOOQ_URL", "LiveFeedError", "StooqPrices", "fetch_daily_closes", "month_end_closes", "parse_daily_csv"]
