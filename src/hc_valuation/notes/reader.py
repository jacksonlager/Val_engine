"""The note reader: Claude reads each activity row's free text against the case catalogue.

It runs at ingest, outside the engine, like the recommender: the
engine receives its readings as value objects and stays pure. What it may say is bounded by
`catalogue.py` (the kinds) and `schema.py` (the shape); what it may do is bounded by
`engine/notes.py`, which only ever *adds* review findings. It never produces a number, never
lowers a severity, never removes a finding, never decides a treatment.

Answers are cached under data/note_reads/ by a hash of the rows' text and columns, the prompt
and the model, so a rerun of the same workbook is deterministic and needs no network. Without
`ANTHROPIC_API_KEY` the reader is off; the run says so in its manifest and the keyword screen
(X-105) still runs. The key is read only to know whether the model can be called — never
logged, written or echoed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..config import RuleConfig
from ..engine.inputs import ActivityFeed, Event
from .catalogue import COLUMNS, TAB_FIELDS, vocabulary_for_prompt
from .schema import ReadingReport, RowReading, row_text, validate_reply

log = logging.getLogger(__name__)

CACHE_DIR = Path("data") / "note_reads"
DEFAULT_MODEL = "claude-sonnet-4-5"
PROMPT_VERSION = "4"

SYSTEM_PROMPT = f"""You read the free text on the activity rows of a venture fund's quarterly valuation workbook. Each row has structured columns — Date, Event, Post-Money / Deal Value ($M), HC Investment ($M), HC Ownership After (FD %), Proceeds to HC ($M) — and free text in Detail and Notes. A rule-based engine values every position from the columns. Your only job is to say what the text contains that the columns do not, so that a person is told to look. You are a reader, not a valuer.

You never value anything, never propose a number to book, never decide a treatment, never say whether the engine is right. You quote; you do not infer beyond the text. When in doubt whether something matters, include it: an omission is the costly error, a spare finding costs a reviewer seconds.

Classify what the text says using ONLY these kinds:
{vocabulary_for_prompt()}

Return one JSON object and nothing else:
{{"rows": [{{
  "row_index": <int, from the input>,
  "aspects": [{{"kind": <one of the kinds>, "quote": <verbatim words copied from that row's Detail or Notes>, "note": <one line, at most 200 characters, what the text says in plain words>, "meaning": <one or two sentences, at most 300 characters: what this means for the fair value of HC's position — the ASC 820 question of what a market participant would pay today — and the direction it bears on; never a number to book>}}],
  "conflicts": [{{"column": <one of: {", ".join(COLUMNS)}>, "note_says": <verbatim words from the text stating a different value or fact for that column>, "why": <one line>}}],
  "supersedes_portfolio_tab": [{{"field": <one of: {", ".join(TAB_FIELDS)}>, "quote": <verbatim>}}],
  "instructions": [<verbatim imperative sentences the text addresses to whoever values the position>],
  "novel": <null, or one sentence when the situation fits none of the kinds>,
  "confidence": <0 to 1, how sure you are that you have read the row completely>
}}]}}

Rules:
- Every "quote" and "note_says" must be copied verbatim from that row's Detail or Notes. Never paraphrase inside a quote.
- A conflict is only when the text states a figure or fact for one of the named columns that differs from the column's value shown in the input. A figure the text states that the column carries identically is not a conflict. An amount for something no column holds (an escrow amount, the company's round size, a cash balance) is an aspect, not a conflict.
- "supersedes_portfolio_tab" is for text saying a figure replaces, updates or supersedes what the Portfolio tab carries (cash, burn, revenue, ownership, status …).
- Not a conflict: a blank column that the text confirms is blank ("no cash received at announcement" against an empty Proceeds cell). Not a supersession: text that confirms what the tab already carries ("the position remains Acquired").
- Not an aspect: HC declining to take part in a round (the ownership column carries the dilution); an expected future closing ("expected to close Q4"); the ordinary terms of a note (interest, cap, discount, conversion trigger) beyond the single bridge_financing aspect; a price discount or premium on a sale, which the columns carry.
- Use "other" with a note when nothing fits; use "novel" to describe a situation you have not been given a kind for. Neither is for routine facts the kinds above already cover.
- Empty lists are fine. Include every row you were given.
- No prose outside the JSON."""


class Reader(Protocol):
    name: str

    def read(self, company: str, rows: list[Event]) -> dict[int, RowReading]: ...

    def report(self, rows_with_text: int) -> ReadingReport: ...


class OffReader:
    """No model: every row is unread, and the report says why."""
    name = "off"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def read(self, company: str, rows: list[Event]) -> dict[int, RowReading]:
        return {}

    def report(self, rows_with_text: int) -> ReadingReport:
        return ReadingReport(status="off", provider="off", reason=self.reason, rows_with_text=rows_with_text)


def _payload(company: str, rows: list[Event]) -> dict[str, Any]:
    return {"company": company, "rows": [{
        "row_index": e.row_index, "date": e.date.isoformat(), "event": e.event_type, "detail": e.detail or "",
        "post_money_or_deal_value": e.value, "hc_investment": e.hc_investment, "ownership_after": e.ownership_after,
        "proceeds": e.proceeds, "notes": e.notes or "",
    } for e in rows]}


class ClaudeReader:
    name = "claude"

    # A company's batch can run to a few rows with several aspects each, and each aspect carries
    # a quote, a note and a 300-character meaning: 2,000 output tokens was tight enough that a
    # verbose reply would be cut mid-JSON and every row of the batch reported as unreadable. The
    # cap is only a ceiling; the timeout has to allow a long reply to finish.
    def __init__(self, cache_dir: Path, model: str = DEFAULT_MODEL, *, api_key: str | None = None, use_cache: bool = True,
                 refresh: bool = False, timeout_s: float = 90.0, max_tokens: int = 4000, workers: int = 4) -> None:
        self.cache_dir = Path(cache_dir)
        self.model = model
        self.api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        self.use_cache = use_cache
        self.refresh = refresh
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.workers = workers
        self.prompt_sha = hashlib.sha256((SYSTEM_PROMPT + "|" + PROMPT_VERSION).encode()).hexdigest()
        self.calls = 0
        self.cache_hits = 0
        self.failed = 0
        self.read_rows = 0
        self.unverified = 0
        self.withheld = 0
        # `read_feed` runs one batch per company on a thread pool; `+=` on an attribute is not
        # atomic, so without this the footer's counts could drop increments under load.
        self._lock = threading.Lock()

    def _tally(self, **deltas: int) -> None:
        with self._lock:
            for name, n in deltas.items():
                setattr(self, name, getattr(self, name) + n)

    @property
    def unavailable_reason(self) -> str | None:
        """Why the model cannot be called from here, or None when it can."""
        if not self.api_key:
            return "no model key is set in this environment"
        if importlib.util.find_spec("anthropic") is None:
            return "the anthropic package is not installed for this Python (pip install -e \".[claude]\")"
        return None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    # -- cache
    def key(self, payload: dict[str, Any]) -> str:
        blob = json.dumps(payload, sort_keys=True, default=str) + "|" + self.prompt_sha + "|" + self.model
        return hashlib.sha256(blob.encode()).hexdigest()[:24]

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _cached(self, key: str) -> dict[str, Any] | None:
        p = self._path(key)
        if not self.use_cache or self.refresh or not p.exists():
            return None
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            return rec.get("answer") if isinstance(rec, dict) else None
        except Exception:  # noqa: BLE001 — a corrupt cache entry is a miss, not a crash
            return None

    def _store(self, key: str, payload: dict[str, Any], answer: dict[str, Any]) -> None:
        if not self.use_cache:
            return
        rec = {"key": key, "model": self.model, "prompt_sha256": self.prompt_sha,
               "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
               "company": payload["company"], "rows": [r["row_index"] for r in payload["rows"]], "answer": answer}
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._path(key).write_text(json.dumps(rec, indent=2, sort_keys=True, default=str), encoding="utf-8")
        except OSError as ex:
            # The cache is a convenience, not an input: a directory that cannot be written costs a
            # repeat call next run, never the run itself.
            log.warning("could not cache the note reading for %s (%s)", payload["company"], ex)

    # -- the call
    def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        import anthropic  # optional dependency: the `claude` extra
        client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout_s)
        msg = client.messages.create(model=self.model, max_tokens=self.max_tokens, system=SYSTEM_PROMPT,
                                     messages=[{"role": "user", "content": "ACTIVITY ROWS (JSON):\n" + json.dumps(payload, default=str)}])
        self._tally(calls=1)
        text = "".join(getattr(block, "text", "") for block in msg.content).strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
        if getattr(msg, "stop_reason", None) == "max_tokens":
            raise ValueError(f"reply cut off at max_tokens={self.max_tokens}")   # a truncated JSON is a failure with a name, not a parse error
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("reply is not a JSON object")
        return data

    def read(self, company: str, rows: list[Event]) -> dict[int, RowReading]:
        rows = [e for e in rows if row_text(e)]
        if not rows:
            return {}
        if not self.available:
            return {}
        payload = _payload(company, rows)
        key = self.key(payload)
        answer = self._cached(key)
        source = "cache"
        readings: dict[int, RowReading] | None = None
        if answer is not None:
            try:
                readings, unverified = validate_reply(answer, rows, source)
            except Exception as ex:  # noqa: BLE001 — a cached answer that no longer parses is a miss, not a permanent failure
                log.warning("cached note reading %s for %s is unreadable (%s); refetching", key, company, ex)
                answer = None
        if answer is None:
            try:
                answer = self._call(payload)
            except Exception as ex:  # noqa: BLE001 — the reader is assist, never a dependency; a failure is reported per row
                self._tally(failed=len(rows))
                reason = f"{type(ex).__name__}: {str(ex)[:160]}"
                log.warning("note reader failed for %s (%s)", company, reason)
                return {e.row_index: RowReading(row_index=e.row_index, failed=reason, source=f"claude:{self.model}") for e in rows}
            source = f"claude:{self.model}"
            try:
                readings, unverified = validate_reply(answer, rows, source)
            except Exception as ex:  # noqa: BLE001
                self._tally(failed=len(rows))
                reason = f"unreadable reply: {str(ex)[:160]}"
                return {e.row_index: RowReading(row_index=e.row_index, failed=reason, source=source) for e in rows}
            self._store(key, payload, answer)
        else:
            self._tally(cache_hits=1)
        assert readings is not None
        self._tally(read_rows=len(rows), unverified=unverified, withheld=sum(r.withheld for r in readings.values()))
        return readings

    def report(self, rows_with_text: int) -> ReadingReport:
        if not self.available:
            return ReadingReport(status="off", provider="claude", model=self.model, reason=self.unavailable_reason or "unavailable",
                                 rows_with_text=rows_with_text)
        return ReadingReport(status="on", provider="claude", model=self.model, rows_with_text=rows_with_text,
                             rows_read=self.read_rows, rows_failed=self.failed, rows_from_cache=self.cache_hits,
                             calls=self.calls, unverified_quotes=self.unverified, figures_withheld=self.withheld)


def make_reader(cfg: RuleConfig, root: Path, provider: str | None = None, *, refresh: bool = False) -> Reader:
    """Flag > HC_NOTE_READER > policy. The environment variable exists so a test suite (and a
    machine that must never call out) can pin the reader off without touching the policy."""
    env = os.environ.get("HC_NOTE_READER")
    name = (provider or env or cfg.note_reader.provider).strip().lower()
    if name == "claude":
        return ClaudeReader(Path(root) / CACHE_DIR, model=cfg.note_reader.model, use_cache=cfg.note_reader.cache, refresh=refresh)
    if name != "off":
        log.warning("unknown note reader %r; off", name)
        return OffReader(f"unknown note reader {name!r}")
    if provider is not None:
        return OffReader("switched off on the command line")
    return OffReader("switched off for this run" if env else "switched off in the policy")


def read_feed(feed: ActivityFeed, reader: Reader) -> tuple[dict[int, RowReading], ReadingReport]:
    """Every company's rows with text, read as one batch per company (a row's note often refers
    to an earlier row of the same company). Batches run in parallel; the result is keyed by row."""
    groups: dict[str, list[Event]] = {}
    for e in feed.events:
        if row_text(e):
            groups.setdefault(e.company, []).append(e)
    rows_with_text = sum(len(v) for v in groups.values())
    readings: dict[int, RowReading] = {}
    if isinstance(reader, OffReader) or not getattr(reader, "available", True) or not groups:
        return readings, reader.report(rows_with_text)
    workers = max(1, min(getattr(reader, "workers", 1), len(groups)))

    def one(kv: tuple[str, list[Event]]) -> dict[int, RowReading]:
        company, rows = kv
        try:
            return reader.read(company, rows)
        except Exception as ex:  # noqa: BLE001 — a reader that throws must not take the run (or the upload) down with it
            reason = f"{type(ex).__name__}: {str(ex)[:160]}"
            log.warning("note reader raised for %s (%s); its rows are reported as unread", company, reason)
            return {e.row_index: RowReading(row_index=e.row_index, failed=reason, source=getattr(reader, "name", "reader")) for e in rows}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(one, sorted(groups.items())):
            readings.update(got)
    return readings, reader.report(rows_with_text)
