"""Fixture-backed connectors. Every response is read from `data/mock_responses/`, which is
shaped like the real vendor payload so a live connector is a drop-in swap.

Two honesty rules apply throughout:

* every company in the workbook is fictional, so no feed can price it — the market-data
  stub seeds an IPO'd company to its IPO print and labels the quote as such;
* fixtures carry a top-level `_note: "synthetic; ..."`, and the source label on every
  value object says `stub`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ..config import repo_root
from ..engine.inputs import ActivityFeed, EventType, PortfolioSnapshot, Status
from ..engine.models import MarketQuote, SectorComp

log = logging.getLogger(__name__)

FIXTURE_DIR = Path("data") / "mock_responses"


def fixture_root(root: Path | None) -> Path | None:
    """Locate `data/mock_responses`. Tests run with a temporary root; fall back to the
    repository's fixtures so a temp root without fixtures still gets comps."""
    for cand in (root, repo_root()):
        if cand is not None and (Path(cand) / FIXTURE_DIR).is_dir():
            return Path(cand) / FIXTURE_DIR
    return None


def _load(root: Path | None, rel: str) -> dict[str, Any]:
    base = fixture_root(root)
    if base is None:
        log.warning("mock_responses not found under %s; connector stub returns nothing", root)
        return {}
    p = base / rel
    if not p.exists():
        log.warning("fixture %s missing; connector stub returns nothing", p)
        return {}
    return json.loads(p.read_text())


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def latest_at_or_before(series: dict[str, float], as_of: date) -> tuple[str, float] | None:
    """The latest `YYYY-MM` observation not after `as_of`."""
    key = _month_key(as_of)
    keys = sorted(k for k in series if k <= key)
    return (keys[-1], float(series[keys[-1]])) if keys else None


# ---------------------------------------------------------------- market data

@dataclass(frozen=True)
class SeededDriftQuote:
    """Demo option: a quote seeded to the IPO print and drifted by `drift_pct` so a dashboard
    can show the 9/30 close differing from the print. Not a price. Off by default."""
    drift_pct: float = 0.0

    def apply(self, ipo_print: float) -> tuple[float, str, str]:
        if not self.drift_pct:
            return (ipo_print, "stub:seeded_to_ipo_print",
                    "Synthetic ticker; no live feed can price it. Seeded to the IPO print — replace with the measurement-date close.")
        cap = ipo_print * (1 + self.drift_pct)
        return (cap, "stub:seeded_to_ipo_print+drift",
                f"Synthetic ticker; seeded to the IPO print and drifted {self.drift_pct:+.1%} for demonstration only. "
                "Not a market price — replace with the measurement-date close.")


LISTED_STAGE = "public"
CARRIED_LISTING_SOURCE = "stub:carried_listing"


class StubMarketDataProvider:
    """Prices listed companies deterministically with no feed behind it:

    * a company that lists this quarter (IPO / Direct Listing in the feed) is seeded to its
      own print, optionally drifted;
    * a company the book already carries as `Public` (a prior quarter's listing, M-041 on
      the carry side) is seeded to its prior-close market cap — `Latest Post-Money` in the
      snapshot — and labelled as such.

    Neither is a price. The source label says so, and the engine's X-101 / M-041 chain
    tells the reviewer to replace it with the measurement-date close."""

    def __init__(self, feed: ActivityFeed, drift_pct: float = 0.0, snapshot: PortfolioSnapshot | None = None) -> None:
        self._prints = {e.company: float(e.value) for e in feed.events
                        if e.event_type in (EventType.IPO.value, EventType.DIRECT_LISTING.value) and e.value}
        self._carried = {p.company: float(p.latest_post_money) for p in (snapshot.positions if snapshot else ())
                         if p.status == Status.ACTIVE and p.stage.strip().lower() == LISTED_STAGE and p.latest_post_money}
        self._drift = SeededDriftQuote(drift_pct)

    @property
    def carried_listings(self) -> list[str]:
        return sorted(self._carried)

    def quote(self, company: str, as_of: date) -> MarketQuote | None:
        ipo_print = self._prints.get(company)
        if ipo_print is not None:
            cap, source, note = self._drift.apply(ipo_print)
            return MarketQuote(company=company, market_cap_musd=round(cap, 6), as_of=as_of, source=source, note=note)
        carried = self._carried.get(company)
        if carried is not None:
            return MarketQuote(
                company=company, market_cap_musd=round(carried, 6), as_of=as_of, source=CARRIED_LISTING_SOURCE,
                note="Synthetic ticker; no live feed can price it. Seeded to the market cap the book carried at the prior "
                     "close — replace with the measurement-date close.")
        return None


# ---------------------------------------------------------------- comps

class StubCompsProvider:
    """PitchBook-shaped public comps from `pitchbook/comps_software.json`."""

    source = "fixture:pitchbook"        # the one fixture label, shared with the market report (live.py)

    def __init__(self, root: Path | None = None) -> None:
        payload = _load(root, "pitchbook/comps_software.json")
        self._items: dict[str, dict[str, Any]] = {it["sector"]: it for it in payload.get("items", [])}
        self.as_of_label: str | None = payload.get("asOfDate")

    @property
    def sectors(self) -> list[str]:
        return sorted(self._items)

    def history(self, sector: str) -> dict[str, float]:
        it = self._items.get(sector)
        if not it:
            return {}
        return {k: float(v) for k, v in it.get("history", {}).get("series", {}).items()}

    def sample_constituents(self, sector: str) -> list[str]:
        """The fixture's `sampleConstituents` tickers — shown, never priced, by the market report."""
        it = self._items.get(sector)
        return [str(t) for t in (it or {}).get("sampleConstituents", [])]

    def sector_multiples(self, as_of: date) -> dict[str, SectorComp]:
        out: dict[str, SectorComp] = {}
        for sector in self._items:
            obs = latest_at_or_before(self.history(sector), as_of)
            if obs is None:
                continue
            out[sector] = SectorComp(sector=sector, ev_to_arr=obs[1], as_of=as_of, source=f"{self.source}@{obs[0]}")
        return out


# ---------------------------------------------------------------- metrics / news

class StubCompanyMetricsProvider:
    def __init__(self, root: Path | None = None) -> None:
        payload = _load(root, "foresight/company_metrics.json")
        self._by_name = {c["name"]: c for c in payload.get("companies", [])}

    def metrics(self, company: str) -> dict[str, Any] | None:
        return self._by_name.get(company)


class StubNewsSignalProvider:
    def __init__(self, root: Path | None = None) -> None:
        payload = _load(root, "alphasense/news_signals.json")
        self._results: list[dict[str, Any]] = list(payload.get("results", []))

    def signals(self, company: str, since: date) -> list[dict[str, Any]]:
        out = [r for r in self._results
               if r.get("company") == company and date.fromisoformat(r["publishedAt"][:10]) >= since]
        return sorted(out, key=lambda r: r["publishedAt"])
