"""How much a sector's public comps re-rated between two months — the one statistic M-080 and
`comps_move` share.

A basket "median" over five names is one company's multiple, and the company at the median is
usually a different one in the two months being compared (on the shipped history, 29 of 42
calibrations divided one name's multiple by another's). A ratio of two such medians says what
two stocks did, not what the sector did, and it moves whenever a name enters or leaves the
basket (a sector whose 2021 basket had three names and whose 2026 basket has five reads a
+15% "re-rating" that is −20% on the three names present both times).

So the re-rating is taken name by name, on the same set of names: each constituent priced in
both months contributes its own ratio (now ÷ then), and the sector's factor is the median of
those ratios. A name that entered or left the basket contributes nothing. Each end can be
read over a window of months around the month asked for (the median of that name's values in
the window) so a single month-end print in a thin stock does not set a private mark's
alternative; the window is a policy choice (`calibration.anchor_window_months`).

When no per-name history is on file (the vendor-shaped fixture carries sector values only)
the basket-median ratio is used and labelled as such, so a reader always knows which
statistic produced the number.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .models import MarketData

SAME_SET = "same-set median of per-name ratios"
BASKET_RATIO = "basket-median ratio"


@dataclass(frozen=True)
class NameMove:
    ticker: str
    then: float        # the name's multiple at the earlier end (median over the window)
    now: float         # ... at the later end
    ratio: float       # now ÷ then


@dataclass(frozen=True)
class Rerating:
    factor: float                    # the sector re-rating, now ÷ then, before any policy bound
    then_key: str                    # the months the two ends were read at (YYYY-MM)
    now_key: str
    method: str                      # SAME_SET or BASKET_RATIO
    window: int                      # months either side of each end that were read
    names: tuple[NameMove, ...]      # per-name detail (empty for BASKET_RATIO)

    @property
    def n_names(self) -> int:
        return len(self.names)

    def formula(self) -> str:
        """The arithmetic, with operands: "SOUN 13.76÷7.70=1.79 · PLTR … ; median of 5 = 1.20"."""
        if self.method == BASKET_RATIO:
            return f"basket median now ÷ basket median then = {self.factor:.3f}"
        parts = " · ".join(f"{n.ticker} {n.now:.2f}÷{n.then:.2f}={n.ratio:.2f}" for n in self.names)
        return f"{parts}; median of {self.n_names} = {self.factor:.3f}"


def _shift(key: str, delta: int) -> str:
    y, m = int(key[:4]), int(key[5:7])
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _window_value(series: dict[str, float], key: str, window: int) -> float | None:
    """The median of a name's values in [key − window, key + window]; None when the name has no
    value anywhere in the window (it was not listed, or was excluded for that month)."""
    vals = [series[k] for k in (_shift(key, d) for d in range(-window, window + 1)) if series.get(k)]
    return statistics.median(vals) if vals else None


def sector_rerating(market: MarketData, sector: str, then_key: str, now_key: str, *,
                    window: int = 0, min_names: int = 3) -> Rerating | None:
    """The re-rating of `sector`'s comps from `then_key` to `now_key`, or None when the history
    cannot say: fewer than `min_names` names priced at both ends, and no basket history either."""
    names = market.comp_constituents.get(sector) or {}
    moves: list[NameMove] = []
    for ticker in sorted(names):
        then = _window_value(names[ticker], then_key, window)
        now = _window_value(names[ticker], now_key, window)
        if then and now:
            moves.append(NameMove(ticker=ticker, then=round(then, 2), now=round(now, 2), ratio=round(now / then, 4)))
    if len(moves) >= min_names:
        factor = statistics.median(m.ratio for m in moves)
        return Rerating(factor=round(factor, 4), then_key=then_key, now_key=now_key, method=SAME_SET,
                        window=window, names=tuple(moves))
    hist = market.comp_history.get(sector) or {}
    then_b, now_b = hist.get(then_key), hist.get(now_key)
    if not then_b or not now_b:
        return None
    return Rerating(factor=round(now_b / then_b, 4), then_key=then_key, now_key=now_key, method=BASKET_RATIO,
                    window=0, names=())
