"""The `synthetic` comps provider: invented sector multiples for quarters no feed can price.

The real market cache (`data/market_cache/<as_of>/`) is genuine EDGAR and Yahoo data and ends
where the calendar does. A test quarter dated after that — Q1 2027, Q2 2027 — still needs a
multiple per sector so the screens and the report render, and there is exactly one honest way
to supply it: a value that is *structurally* impossible to mistake for an observation.

Four properties hold, and the tests in `tests/test_synthetic_market.py` pin each one:

* the file must declare itself. `data/synthetic_market/<as_of>.yaml` carries `synthetic: true`
  and a `warning:` sentence, and the provider refuses a file without the marker;
* every value is labelled. The manifest says `synthetic:invented-test-data`, every
  `SectorComp.source` starts with `synthetic:`, and the market report carries
  `synthetic: true` plus a `notice` the Market tab prints above the numbers;
* nothing is written. The provider never touches `data/market_cache/` or `~/.cache`; there is
  no fetch, no refresh, no cache directory;
* the engine treats it as not observed. `M-080` calibration and the `relative_to_comps` screens
  both require a `live:` source, so a synthetic multiple never moves an alternative mark and
  the valuation screens fall back to the policy's absolute bounds.

`scripts/make_synthetic_market.py` writes the file from a seed and a deterministic drift; the
numbers inside are a stage prop, and the file says so in its first line.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..engine.models import SectorComp
from .stubs import latest_at_or_before

SYNTHETIC_DIR = Path("data") / "synthetic_market"
SYNTHETIC_SOURCE = "synthetic:invented-test-data"
SYNTHETIC_NOTICE = ("SYNTHETIC TEST DATA. Every multiple on this page was invented by a script for a test quarter "
                    "and is not an observation of any market. Nothing here was fetched, nothing is cached, and no "
                    "mark calibrates to it.")


class SyntheticDataError(ValueError):
    """The file is not marked as synthetic, or does not have the shape the provider expects."""


def synthetic_file(root: Path, as_of: date) -> Path:
    return Path(root) / SYNTHETIC_DIR / f"{as_of.isoformat()}.yaml"


class SyntheticCompsProvider:
    """`CompsProvider` over one declared-synthetic YAML file. Read-only by construction."""

    source = SYNTHETIC_SOURCE

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        raw = yaml.safe_load(self.path.read_text()) or {}
        if raw.get("synthetic") is not True:
            raise SyntheticDataError(f"{self.path}: refusing a market file that does not declare `synthetic: true`")
        sectors = raw.get("sectors")
        if not isinstance(sectors, Mapping) or not sectors:
            raise SyntheticDataError(f"{self.path}: no `sectors:` mapping")
        self.warning = str(raw.get("warning") or SYNTHETIC_NOTICE)
        self.as_of_label = str(raw.get("as_of") or "")
        self._series: dict[str, dict[str, float]] = {}
        for sector, body in sectors.items():
            hist = (body or {}).get("history") if isinstance(body, Mapping) else None
            if not isinstance(hist, Mapping) or not hist:
                raise SyntheticDataError(f"{self.path}: sector {sector!r} has no `history:` series")
            self._series[str(sector)] = {str(k): float(v) for k, v in hist.items()}

    @property
    def sectors(self) -> list[str]:
        return sorted(self._series)

    def history(self, sector: str) -> dict[str, float]:
        return dict(self._series.get(sector, {}))

    def sector_multiples(self, as_of: date) -> dict[str, SectorComp]:
        out: dict[str, SectorComp] = {}
        for sector, series in self._series.items():
            obs = latest_at_or_before(series, as_of)
            if obs is None:
                continue
            out[sector] = SectorComp(sector=sector, ev_to_arr=obs[1], as_of=as_of, source=f"{self.source}@{obs[0]}")
        return out

    def report(self, as_of: date, *, positions: Mapping[str, int] | None = None,
               used_by: Mapping[str, Any] | None = None, months_of_history: int | None = None) -> dict[str, Any]:
        """The `/api/market` body (docs/market-feed.md §3) with the synthetic marker on every level."""
        from .live import qoq, trim_history
        sectors = []
        for sector in self.sectors:
            history = trim_history(self.history(sector), as_of, months_of_history)
            obs = latest_at_or_before(history, as_of)
            month = obs[0] if obs else None
            prior, change = qoq(history, month) if month else (None, None)
            sectors.append({
                "sector": sector, "positions": int((positions or {}).get(sector, 0)),
                "ev_to_revenue": obs[1] if obs else None, "as_of_month": month,
                "source": f"{self.source}@{month}" if month else self.source, "live": False, "synthetic": True,
                "prior_quarter": prior, "qoq_pct": change, "history": history, "counts": {},
                "constituents": [],    # invented numbers have no constituents behind them
            })
        return {
            "provider": "synthetic", "source": self.source, "reached_live": False, "synthetic": True,
            "notice": self.warning, "synthetic_file": self.path.as_posix(),
            "as_of": as_of.isoformat(), "fetched_at": None, "cache": None,
            "used_by": dict(used_by or {}), "baskets_file": "",
            "errors": [], "sectors": sorted(sectors, key=lambda s: (-s["positions"], s["sector"])),
        }
