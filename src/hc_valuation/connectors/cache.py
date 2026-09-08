"""On-disk cache of the live feed's trimmed extracts, one directory per measurement date.

    data/market_cache/<as_of>/
        meta.json               {"fetched_at", "as_of", "user_agent", "baskets_sha256", "price_source"}
        company_tickers.json    TICKER -> {"cik", "title"}     (only the baskets' tickers; cik null = unknown to SEC)
        edgar/<TICKER>.json     the `edgar.extract` of one filer
        edgar_raw/<TICKER>.json the `edgar.slim` companyfacts it was derived from (git-ignored: a few
                                hundred KB each; lets a changed extraction re-derive offline)
        prices/<TICKER>.json    {"YYYY-MM": close}            (month-end closes at or before as_of)

Rules (docs/market-feed.md §2.5): a complete cache means **no network call** — a re-run is
deterministic and works offline; `refresh=True` clears it first; a partial cache (a ticker
missing) is completed by fetching only what is missing. The price half is keyed by the
provider that wrote it (`meta.price_source`): a run with a different price source treats
every cached close as missing, refetches only prices, and — once the new provider has
answered for at least one ticker — drops what the old one wrote; if the new provider answers
for nobody, the old half and its `price_source` stay untouched. Never raw payloads: a companyfacts
document is megabytes, its extract is a few hundred bytes, and the whole directory is meant
to be committed after a real run so a reviewer sees live-shaped data without a network.
"""
from __future__ import annotations

import json
import math
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .fetch import loads_strict

CACHE_DIR = Path("data") / "market_cache"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return loads_strict(path.read_text(encoding="utf-8"))
    except ValueError:
        return None   # a corrupt file — or one carrying NaN — is treated as missing and refetched


def _finite_positive(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


class MarketCache:
    def __init__(self, root: Path, as_of: date) -> None:
        self.root = Path(root)
        self.as_of = as_of
        self.dir = self.root / CACHE_DIR / as_of.isoformat()

    @property
    def rel_dir(self) -> str:
        """`data/market_cache/2026-09-30` — the form the report shows."""
        return (CACHE_DIR / self.as_of.isoformat()).as_posix()

    def exists(self) -> bool:
        return self.read_meta() is not None

    def clear(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir)

    # ---------------------------------------------------------------- meta
    def read_meta(self) -> dict[str, Any] | None:
        """None unless the record says when the cache was fetched, as a date: per-ticker files
        without that provenance are not a cache, and are refetched rather than served as live."""
        meta = _read_json(self.dir / "meta.json")
        if not isinstance(meta, dict):
            return None
        try:
            date.fromisoformat(str(meta.get("fetched_at") or "")[:10])
        except ValueError:
            return None
        return meta

    def write_meta(self, *, user_agent: str, baskets_sha256: str, price_source: str,
                   fetched_at: datetime | None = None) -> dict[str, Any]:
        stamp = (fetched_at or datetime.now(timezone.utc)).replace(microsecond=0)
        meta = {"fetched_at": stamp.isoformat().replace("+00:00", "Z"), "as_of": self.as_of.isoformat(),
                "user_agent": user_agent, "baskets_sha256": baskets_sha256, "price_source": price_source}
        _write_json(self.dir / "meta.json", meta)
        return meta

    def price_source(self) -> str | None:
        """The provider that wrote `prices/`, or None when there is no meta yet."""
        meta = self.read_meta()
        return meta.get("price_source") if meta else None

    def prices_match(self, price_source: str) -> bool:
        """False when the cached closes were written by another provider (their symbols and
        rounding differ) — the caller then clears the price half and refetches it."""
        recorded = self.price_source()
        return recorded is None or recorded == price_source

    def prune_prices(self, keep: set[str]) -> list[str]:
        """Delete every cached close file except `keep` — used after a change of price source
        once the new provider has answered, so no file written by the old one survives."""
        gone = []
        for f in sorted((self.dir / "prices").glob("*.json")) if (self.dir / "prices").exists() else []:
            if f.stem.upper() not in {k.upper() for k in keep}:
                f.unlink()
                gone.append(f.stem)
        return gone

    # ---------------------------------------------------------------- ticker table
    def read_tickers(self) -> dict[str, dict[str, Any]]:
        return _read_json(self.dir / "company_tickers.json") or {}

    def write_tickers(self, table: dict[str, dict[str, Any]]) -> None:
        merged = self.read_tickers()
        merged.update(table)
        _write_json(self.dir / "company_tickers.json", merged)

    # ---------------------------------------------------------------- per ticker
    def edgar_path(self, ticker: str) -> Path:
        return self.dir / "edgar" / f"{ticker.upper()}.json"

    def edgar_raw_path(self, ticker: str) -> Path:
        return self.dir / "edgar_raw" / f"{ticker.upper()}.json"

    def read_edgar_raw(self, ticker: str) -> dict[str, Any] | None:
        """None when the slim was cut with an older keep-list: it cannot carry a concept the current
        extractor reads, so re-deriving from it would silently reproduce the old gap. The ticker is
        refetched from SEC instead — its closes are untouched, so nothing is re-priced."""
        from .edgar import SLIM_VERSION
        raw = _read_json(self.edgar_raw_path(ticker))
        if not (isinstance(raw, dict) and "facts" in raw):
            return None
        return raw if raw.get("slim_version") == SLIM_VERSION else None

    def write_edgar_raw(self, ticker: str, slim_facts: dict[str, Any]) -> None:
        _write_json(self.edgar_raw_path(ticker), slim_facts)

    def prices_path(self, ticker: str) -> Path:
        return self.dir / "prices" / f"{ticker.upper()}.json"

    def read_edgar(self, ticker: str) -> dict[str, Any] | None:
        ext = _read_json(self.edgar_path(ticker))
        return ext if self._extract_current(ext) else None

    @staticmethod
    def _extract_current(ext: Any) -> bool:
        """An extract written by an earlier extraction (frame-keyed `revenue_quarterly`, or an
        older `extract_version`) is treated as missing so it is re-derived from the slim facts
        or refetched."""
        from .edgar import EXTRACT_VERSION
        return isinstance(ext, dict) and ext.get("extract_version") == EXTRACT_VERSION

    def write_edgar(self, ticker: str, extract: dict[str, Any]) -> None:
        _write_json(self.edgar_path(ticker), extract)

    def read_prices(self, ticker: str) -> dict[str, float] | None:
        """None when the file is not `{YYYY-MM: positive close}` with at least one row — an empty or
        malformed file is a miss to refetch, not a constituent with no price."""
        raw = _read_json(self.prices_path(ticker))
        if not isinstance(raw, dict) or not raw or not all(isinstance(k, str) and _finite_positive(v) for k, v in raw.items()):
            return None
        return {k: float(v) for k, v in raw.items()}

    def write_prices(self, ticker: str, closes: dict[str, float]) -> None:
        _write_json(self.prices_path(ticker), closes)

    def splits_path(self, ticker: str) -> Path:
        return self.dir / "splits" / f"{ticker}.json"

    def read_splits(self, ticker: str) -> dict[str, float] | None:
        """`{YYYY-MM-DD: ratio}`, or None when the cache predates split capture — which is not
        the same as "this company never split", and the caller must treat it that way."""
        raw = _read_json(self.splits_path(ticker))
        if not isinstance(raw, dict):
            return None
        return {k: float(v) for k, v in raw.items() if _finite_positive(v)}   # a ratio of 0 is not a split

    def write_splits(self, ticker: str, splits: dict[str, float]) -> None:
        _write_json(self.splits_path(ticker), splits)

    def missing(self, tickers: list[str]) -> tuple[list[str], list[str]]:
        """(tickers with no EDGAR extract, tickers with no cached closes)."""
        return ([t for t in tickers if not self._extract_current(_read_json(self.edgar_path(t)))],
                [t for t in tickers if self.read_prices(t) is None])

    def drop_edgar(self, ticker: str) -> None:
        """Forget one filer's facts (the extract and the slim) — used when the ticker now resolves
        to a different CIK, so what is cached is another company's filings."""
        for path in (self.edgar_path(ticker), self.edgar_raw_path(ticker)):
            if path.is_file():
                path.unlink()
