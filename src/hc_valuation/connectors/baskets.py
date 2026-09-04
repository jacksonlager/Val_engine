"""`rules/comps_baskets.yaml` -> `Baskets`: which public names stand for each workbook sector.

Policy-adjacent and reviewed like the policy file, so it is loaded the same way: every key
is declared, an unknown key is an error, and every number the live provider needs
(`months_of_history`, `min_constituents`, the price source and its request rate) comes
from here — nothing is a literal in code. A provider's symbol convention (Yahoo's `-` for
`.`, Stooq's `.us` suffix) is the provider's own business and lives in `prices.py`.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import repo_root
from .prices import DEFAULT_PRICE_SOURCE, PRICE_SOURCES

BASKETS_FILE = Path("rules") / "comps_baskets.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BasketDefaults(_Strict):
    months_of_history: int = Field(gt=0)
    min_constituents: int = Field(gt=0)
    price_source: str = DEFAULT_PRICE_SOURCE        # yahoo | stooq (prices.PRICE_SOURCES)
    price_max_per_s: float = Field(gt=0)            # polite request rate against the price source

    @field_validator("price_source")
    @classmethod
    def _known_price_source(cls, v: str) -> str:
        name = v.strip().lower()
        if name not in PRICE_SOURCES:
            raise ValueError(f"defaults.price_source: {v!r} is not one of {', '.join(PRICE_SOURCES)}")
        return name


class TickerOverride(_Strict):
    cik: int | None = None
    name: str | None = None


class Baskets(_Strict):
    version: int
    note: str = ""
    defaults: BasketDefaults
    sectors: dict[str, list[str]]
    overrides: dict[str, TickerOverride] = Field(default_factory=dict)
    sha256: str = ""       # of the file text; recorded in the cache's meta.json
    path: str = ""

    @field_validator("sectors")
    @classmethod
    def _tickers_are_symbols(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if not v:
            raise ValueError("sectors: at least one sector is required")
        for sector, tickers in v.items():
            if not sector.strip():
                raise ValueError("sectors: empty sector name")
            if not tickers:
                raise ValueError(f"sectors[{sector!r}]: empty basket")
            for t in tickers:
                if not isinstance(t, str) or not t.strip() or t != t.strip().upper():
                    raise ValueError(f"sectors[{sector!r}]: ticker {t!r} must be an upper-case symbol")
            if len(set(tickers)) != len(tickers):
                raise ValueError(f"sectors[{sector!r}]: duplicate ticker")
        return v

    @property
    def tickers(self) -> list[str]:
        """Every ticker in any basket, once, sorted."""
        return sorted({t for ts in self.sectors.values() for t in ts})


def default_baskets_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / BASKETS_FILE


def load_baskets(path: str | Path | None = None) -> Baskets:
    """Load and strictly validate the baskets file. Raises on unknown keys or malformed tickers."""
    p = Path(path) if path is not None else default_baskets_path()
    if not p.exists():
        raise FileNotFoundError(f"comps baskets file not found: {p}")
    text = p.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{p}: top level must be a mapping")
    raw = dict(raw)
    raw["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    raw["path"] = str(p)
    return Baskets.model_validate(raw)
