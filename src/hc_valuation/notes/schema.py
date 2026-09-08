"""What a note reading is, and the hostile validation that turns a model reply into one.

The reply is data about the text, never about the valuation: which catalogue kinds the text
shows, quoted; which columns the text argues with, quoted; which Portfolio-tab fields it
supersedes; the instructions it gives. Every quote has to be found in the row's own text — a
quote that is not there is kept but marked unverified, because dropping it would let a
hallucination guard hide a true finding; the reviewer sees the flag either way. A kind outside
the catalogue is coerced to `other` with the model's word kept in the note. Column values are
taken from the row, never from the model. Nothing here can produce a number to book.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..engine.inputs import Event
from .catalogue import COLUMNS, TAB_FIELDS, AspectKind


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Aspect(_Frozen):
    kind: AspectKind
    quote: str = ""
    note: str = ""              # ≤ 200 chars, the model's one-line gloss (or its own kind word when coerced to `other`)
    meaning: str = ""           # ≤ 300 chars, what it means for the fair value of HC's position — words, never a number
    verified: bool = True       # the quote was found in the row's text


class Conflict(_Frozen):
    column: str                 # a key of COLUMNS
    column_value: Any           # what the row carries (from the row, not the model)
    note_says: str              # verbatim
    why: str = ""
    verified: bool = True


class Supersession(_Frozen):
    field: str                  # one of TAB_FIELDS
    quote: str = ""
    verified: bool = True


class RowReading(_Frozen):
    row_index: int
    aspects: tuple[Aspect, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    supersedes: tuple[Supersession, ...] = ()
    instructions: tuple[str, ...] = ()
    novel: str | None = None    # the model's sentence when the situation fits no kind
    confidence: float = 1.0
    failed: str | None = None   # the reader could not read this row: the reason (a REVIEW on its own)
    source: str = ""            # "claude:<model>" | "cache" | "fake"
    withheld: int = 0           # fields dropped because they named a figure the row does not carry (see `figures_carried`)

    @property
    def empty(self) -> bool:
        return not (self.aspects or self.conflicts or self.supersedes or self.instructions or self.novel or self.failed)


class ReadingReport(_Frozen):
    """What the footer says about the reader: on or off, why, and how much it read."""
    status: str                 # "on" | "off"
    provider: str               # "claude" | "off"
    model: str = ""
    reason: str = ""            # why off, or "" when on
    rows_with_text: int = 0
    rows_read: int = 0
    rows_failed: int = 0
    rows_from_cache: int = 0
    calls: int = 0
    unverified_quotes: int = 0
    figures_withheld: int = 0

    def label(self) -> str:
        if self.status != "on":
            return f"off: {self.reason}" if self.reason else "off"
        return f"claude:{self.model}"


# ---------------------------------------------------------------- validation

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "").replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def row_text(e: Event) -> str:
    return f"{e.detail or ''} {e.notes or ''}".strip()


def quote_in(quote: str, text: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(text)


def _column_value(e: Event, column: str) -> Any:
    return {
        "date": e.date.isoformat(), "event": e.event_type, "post_money_or_deal_value": e.value,
        "hc_investment": e.hc_investment, "ownership_after": e.ownership_after, "proceeds": e.proceeds,
    }.get(column)


def _str(v: Any, limit: int) -> str:
    return str(v if v is not None else "").strip()[:limit]


# ---------------------------------------------------------------- figures the model did not get from the row

_FIGURE = re.compile(r"\d+(?:[.,]\d+)*")
_ASC = {820.0}      # "ASC 820" is the prompt's own vocabulary, not a figure about the position


def _figures(s: str) -> set[float]:
    out: set[float] = set()
    for m in _FIGURE.findall(s or ""):
        try:
            out.add(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


def row_figures(e: Event) -> set[float]:
    """Every number the model was shown for this row: the text's, the columns' (ownership both as
    a fraction and a percentage) and the date's parts."""
    allowed = _figures(row_text(e)) | _ASC
    for v in (e.value, e.hc_investment, e.proceeds):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            allowed |= {float(v), round(float(v), 1), round(float(v), 2)}
    if isinstance(e.ownership_after, (int, float)) and not isinstance(e.ownership_after, bool):
        o = float(e.ownership_after)
        allowed |= {o, round(o * 100, 4), round(o * 100, 1)}
    allowed |= {float(e.date.year), float(e.date.month), float(e.date.day)}
    return allowed


def figures_carried(field: str, allowed: set[float]) -> bool:
    """Does every number in a free-text field come from the row? The prompt forbids a number to
    book; the only numbers a reading may repeat are the ones the row itself shows. A sentence
    that brings its own figure — "worth about $3.2M", "mark to $4.0M", "$45M of preference" —
    is exactly what must not reach a reviewer as if it were a mark, so the field is withheld and
    the finding says so. The kind and the quote still reach a person."""
    return all(any(abs(x - a) < 1e-9 for a in allowed) for x in _figures(field))


def validate_row(raw: dict[str, Any], e: Event, source: str) -> tuple[RowReading, int]:
    """One row's reading from the model's object for it. Returns the reading and the count of
    quotes that could not be matched to the row text."""
    text = row_text(e)
    allowed = row_figures(e)
    unverified = 0
    withheld = 0

    def prose(v: Any, limit: int) -> str:
        nonlocal withheld
        s = _str(v, limit)
        if s and not figures_carried(s, allowed):
            withheld += 1
            return ""
        return s

    aspects: list[Aspect] = []
    for a in raw.get("aspects") or []:
        if not isinstance(a, dict):
            continue
        kind_raw = _str(a.get("kind"), 60)
        try:
            kind = AspectKind(kind_raw)
            note = prose(a.get("note"), 200)
        except ValueError:
            kind = AspectKind.OTHER
            note = (f"{kind_raw}: " if kind_raw else "") + prose(a.get("note"), 180)
        quote = _str(a.get("quote"), 300)
        ok = quote_in(quote, text)
        if quote and not ok:
            unverified += 1
        aspects.append(Aspect(kind=kind, quote=quote, note=note, meaning=prose(a.get("meaning"), 300), verified=ok))
    conflicts: list[Conflict] = []
    for c in raw.get("conflicts") or []:
        if not isinstance(c, dict):
            continue
        column = _str(c.get("column"), 40)
        if column not in COLUMNS:
            continue                        # a column that does not exist cannot conflict with anything
        says = _str(c.get("note_says"), 300)
        ok = quote_in(says, text)
        if says and not ok:
            unverified += 1
        conflicts.append(Conflict(column=column, column_value=_column_value(e, column), note_says=says,
                                  why=prose(c.get("why"), 200), verified=ok))
    sups: list[Supersession] = []
    for s in raw.get("supersedes_portfolio_tab") or []:
        if not isinstance(s, dict):
            continue
        field = _str(s.get("field"), 40)
        if field not in TAB_FIELDS:
            field = "other"
        quote = _str(s.get("quote"), 300)
        ok = quote_in(quote, text)
        if quote and not ok:
            unverified += 1
        sups.append(Supersession(field=field, quote=quote, verified=ok))
    instructions = tuple(x for x in (prose(i, 200) for i in (raw.get("instructions") or [])) if x)[:6]
    novel = prose(raw.get("novel"), 300) or None
    try:
        conf = min(1.0, max(0.0, float(raw.get("confidence", 1.0))))
    except (TypeError, ValueError):
        conf = 0.0
    return RowReading(row_index=e.row_index, aspects=tuple(aspects), conflicts=tuple(conflicts), supersedes=tuple(sups),
                      instructions=instructions, novel=novel, confidence=round(conf, 3), source=source,
                      withheld=withheld), unverified


def validate_reply(data: Any, rows: list[Event], source: str) -> tuple[dict[int, RowReading], int]:
    """The model's whole reply for one batch. Rows the reply does not mention are read as empty
    (the model was asked about them and said nothing); a reply that is not the expected shape
    raises, and the caller records every row as failed."""
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError("reply is not an object with a 'rows' list")
    by_index = {e.row_index: e for e in rows}
    out: dict[int, RowReading] = {}
    unverified = 0
    for item in data["rows"]:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("row_index"))
        except (TypeError, ValueError):
            continue
        e = by_index.get(idx)
        if e is None:
            continue                        # a row not in the batch is not evidence about anything
        reading, n = validate_row(item, e, source)
        unverified += n
        out[idx] = reading
    for idx, e in by_index.items():
        out.setdefault(idx, RowReading(row_index=idx, source=source))
    return out, unverified
