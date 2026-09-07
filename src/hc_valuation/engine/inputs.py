"""Input value types consumed by the pure engine.

These are the *only* representations of the workbook the engine ever sees. They are
constructed by `ingest/`, which depends on this module — never the reverse.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Status(str, Enum):
    ACTIVE = "Active"
    ACQUIRED = "Acquired"
    SHUT_DOWN = "Shut Down"


class EventType(str, Enum):
    PRICED_ROUND = "Priced Equity Round"
    CONVERTIBLE_NOTE = "Convertible Note"
    IPO = "IPO"
    ACQ_CLOSED = "Acquisition (Closed)"
    ACQ_ANNOUNCED = "Acquisition (Announced)"
    SHUTDOWN = "Shutdown"
    SECONDARY = "Secondary Sale"
    TERM_SHEET = "Term Sheet Signed"
    SECONDARY_PURCHASE = "Secondary Purchase"
    DISTRIBUTION = "Distribution"
    OWNERSHIP_ADJUSTMENT = "Ownership Adjustment"
    NEW_INVESTMENT = "New Investment"
    ACQ_TERMINATED = "Acquisition (Terminated)"
    NOTE_REPAID = "Note Repaid"
    BANKRUPTCY_CH11 = "Bankruptcy (Chapter 11)"
    DIRECT_LISTING = "Direct Listing"


KNOWN_EVENT_TYPES: frozenset[str] = frozenset(e.value for e in EventType)


class Correction(BaseModel):
    """One thing the ingest layer read as something other than what the cell literally
    said. The engine never reads these; `ingest/validate.py` turns each into an X-91x /
    X-920 issue so a reviewer can see what was read as what (training/SPEC.md §2).

    `kind` selects the validation id: header | event_type | company | ambiguous | value |
    unit | structure | sheet | currency | unparseable | percent_block.
    """
    model_config = ConfigDict(frozen=True)

    kind: str
    original: str
    resolved: str
    method: str
    detail: str = ""
    sheet: str | None = None
    row_index: int | None = None
    column: str | None = None
    company: str | None = None

    def located(self, *, sheet: str | None = None, row_index: int | None = None,
                column: str | None = None, company: str | None = None) -> "Correction":
        """The pure normalizers do not know where a cell lives; the reader adds that here."""
        return self.model_copy(update={
            "sheet": sheet if sheet is not None else self.sheet,
            "row_index": row_index if row_index is not None else self.row_index,
            "column": column if column is not None else self.column,
            "company": company if company is not None else self.company,
        })


class Position(BaseModel):
    """One row of the Portfolio tab as of the prior close."""
    model_config = ConfigDict(frozen=True)

    company: str
    sector: str
    fund: str
    stage: str
    status: Status
    first_investment: date
    latest_round: date
    latest_post_money: float
    invested: float
    ownership: float
    prior_mark: float
    realized: float
    arr: float | None = None
    arr_growth: float | None = None
    gross_margin: float | None = None
    net_burn: float | None = None
    cash: float | None = None
    headcount: int | None = None
    sheet_moic: float | None = None      # cached formula value, for reconciliation only
    sheet_runway: float | None = None    # cached formula value, for reconciliation only
    row_index: int
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def runway_months(self) -> float | None:
        """Cash / burn, recomputed. None when burn is zero/absent (breakeven or inactive)."""
        if self.net_burn is None or self.net_burn <= 0 or self.cash is None:
            return None
        # $1.4M over $0.2M a month is seven months, not 6.999999999999999: the screens compare this
        # against whole-month thresholds, and a company exactly at the line must not fall under it.
        return round(self.cash / self.net_burn, 6)

    @property
    def moic(self) -> float | None:
        if not self.invested:
            return None
        return (self.prior_mark + self.realized) / self.invested


class Event(BaseModel):
    """One row of the quarterly activity tab. `event_type` is the canonical name once the
    normalizer has resolved it (the raw spelling then sits in `extra["raw_event_type"]`);
    unknown types are kept verbatim so M-999 can name them."""
    model_config = ConfigDict(frozen=True)

    date: date
    company: str
    event_type: str
    detail: str = ""
    value: float | None = None            # post-money / deal value / market cap / implied val
    hc_investment: float | None = None
    ownership_after: float | None = None
    proceeds: float | None = None
    notes: str = ""
    row_index: int
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def known(self) -> bool:
        return self.event_type in KNOWN_EVENT_TYPES

    @property
    def signature(self) -> str:
        """Normalised identity for caching adjudication proposals (E-09)."""
        d = self.detail.lower()
        tags = []
        if "recap" in d:
            tags.append("recap")
        if "extension" in d or "same terms" in d:
            tags.append("extension")
        if self.hc_investment:
            tags.append("hc_funded")
        if self.proceeds:
            tags.append("proceeds")
        return "|".join([self.event_type.strip().lower()] + sorted(tags))




class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    as_of: date
    positions: tuple[Position, ...]
    sheet_name: str
    unknown_columns: tuple[str, ...] = ()
    corrections: tuple[Correction, ...] = ()   # ingest normalization record; validation/report only

    def by_company(self) -> dict[str, Position]:
        return {p.company: p for p in self.positions}


class ActivityFeed(BaseModel):
    model_config = ConfigDict(frozen=True)
    quarter_label: str
    events: tuple[Event, ...]
    sheet_name: str
    unknown_columns: tuple[str, ...] = ()
    corrections: tuple[Correction, ...] = ()   # ingest normalization record; validation/report only

    def by_company(self) -> dict[str, list[Event]]:
        out: dict[str, list[Event]] = {}
        for e in self.events:
            out.setdefault(e.company, []).append(e)
        return out
