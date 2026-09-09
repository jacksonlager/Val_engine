"""Pre-demo review of the two model-assisted layers: the note reader and the recommender.
Every test here injects a fake in place of the model — the suite pins
HC_NOTE_READER=off and hides the key — and asserts the contract that matters when Claude is
called for real:

* nothing a layer does can raise into the run or the upload (a cache directory that cannot be
  written, a reader that throws, an unreadable cached answer);
* the counters the footer reports are exact under the parallel executors;
* a reply that validates but names a figure the row does not carry is withheld, not shown as if
  it were a mark; a quote from another row is unverified;
* a cache entry survives exactly as long as the prompt and model it was written under;
* the keyword screen and the reader do not raise the same aspect twice; a refused row's reading
  raises nothing; a reading never moves a mark or lowers readiness.
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import types
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hc_valuation.api.app import create_app
from hc_valuation.config import load_config, repo_root
from hc_valuation.engine.inputs import Event, EventType
from hc_valuation.engine.models import MarketData, OverrideLedger, Readiness, Severity
from hc_valuation.engine.run import build_registry, run_valuation
from hc_valuation.ingest.reader import read_workbook
from hc_valuation.ingest.validate import validate
from hc_valuation.notes import AspectKind, ClaudeReader, RowReading, read_feed
from hc_valuation.notes.schema import validate_reply
from hc_valuation.pipeline import RunPaths, execute
from hc_valuation.recommend import ClaudeChooser, build_brief, build_position_brief, recommend_run
from tests.conftest import GENERATED_AT, event, make_workbook, position

ROOT = repo_root()


# ---------------------------------------------------------------- helpers

def _run(path: Path, cfg, readings: dict | None = None):
    snapshot, feed = read_workbook(path, cfg)
    issues = validate(snapshot, feed, cfg)
    return run_valuation(snapshot, feed, MarketData(as_of=cfg.quarter.measurement_date), OverrideLedger(), cfg,
                         validation=tuple(issues), note_readings=readings or {}, note_reader="fake",
                         input_sha256="x", input_file=path.name, generated_at=GENERATED_AT, market_data_source="test")


def _flags(c) -> dict:
    return {f.rule_id: f for f in c.flags}


def _ev(**kw) -> Event:
    base = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, ownership_after=0.045,
                 notes="New investors hold a 2x participating preference. $1.0M is held in escrow.")
    base.update(kw)
    return Event(**{**base, "row_index": 2})


def _reply(row_index: int, **row) -> dict:
    item = {"row_index": row_index, "aspects": [], "conflicts": [], "supersedes_portfolio_tab": [], "instructions": [],
            "novel": None, "confidence": 0.9}
    item.update(row)
    return {"rows": [item]}


class _Block:
    def __init__(self, text: str) -> None:
        self.text = text


class _Msg:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


def _fake_anthropic(reply_text: str, seen: dict) -> types.ModuleType:
    mod = types.ModuleType("anthropic")

    class Anthropic:
        def __init__(self, api_key=None, timeout=None, **kw) -> None:
            seen["timeout"] = timeout
            self.messages = self

        def create(self, **kw):
            seen["request"] = kw
            return _Msg(reply_text)

    mod.Anthropic = Anthropic
    return mod


@pytest.fixture
def test_reader_survives_a_cache_directory_it_cannot_write(tmp_path: Path, cfg, monkeypatch):
    wb = make_workbook(tmp_path, [position()], [event(detail="Series B", value=150.0, ownership_after=0.09, notes="escrow of $1M")])
    _, feed = read_workbook(wb, cfg)
    blocker = tmp_path / "cache"
    blocker.write_text("a file where the cache directory should be")     # mkdir(parents=True) raises on it
    reader = ClaudeReader(blocker, model="m", api_key="k", workers=1)
    monkeypatch.setattr(reader, "_call", lambda payload: _reply(2, aspects=[{"kind": "escrow_or_holdback", "quote": "escrow of $1M", "note": "escrow"}]))
    readings, report = read_feed(feed, reader)
    assert readings[2].aspects[0].kind is AspectKind.ESCROW_OR_HOLDBACK and not readings[2].failed
    assert report.rows_read == 1 and report.rows_failed == 0


def test_a_reader_that_throws_is_a_failed_row_not_a_dead_run(tmp_path: Path, cfg):
    wb = make_workbook(tmp_path, [position()], [event(detail="Series B", value=150.0, ownership_after=0.09, notes="escrow of $1M")])
    _, feed = read_workbook(wb, cfg)

    class Boom:
        name = "boom"
        available = True
        workers = 2

        def read(self, company, rows):
            raise RuntimeError("the executor died")

        def report(self, rows_with_text):
            from hc_valuation.notes import ReadingReport
            return ReadingReport(status="on", provider="claude", model="boom", rows_with_text=rows_with_text)

    readings, _ = read_feed(feed, Boom())
    assert readings[2].failed and "RuntimeError" in readings[2].failed
    c = _run(wb, cfg, readings).by_company()["Alpha"]
    assert "X-132" in _flags(c) and c.readiness is Readiness.NEEDS_REVIEW


def test_an_unreadable_cached_answer_is_refetched_not_failed_forever(tmp_path: Path, cfg, monkeypatch):
    wb = make_workbook(tmp_path, [position()], [event(detail="Series B", value=150.0, ownership_after=0.09, notes="escrow of $1M")])
    _, feed = read_workbook(wb, cfg)
    reader = ClaudeReader(tmp_path / "cache", model="m", api_key="k", workers=1)
    rows = [e for e in feed.events]
    from hc_valuation.notes.reader import _payload
    key = reader.key(_payload("Alpha", rows))
    reader._store(key, _payload("Alpha", rows), {"rows": "not a list"})       # an older, broken record
    calls = []

    def fake_call(payload):
        calls.append(payload["company"])
        return _reply(2, aspects=[{"kind": "escrow_or_holdback", "quote": "escrow of $1M", "note": "escrow"}])
    monkeypatch.setattr(reader, "_call", fake_call)
    readings, report = read_feed(feed, reader)
    assert calls == ["Alpha"] and not readings[2].failed and readings[2].source == "claude:m"
    assert json.loads((tmp_path / "cache" / f"{key}.json").read_text())["answer"]["rows"][0]["row_index"] == 2


def test_recommender_survives_a_cache_directory_it_cannot_write(tmp_path: Path):
    base = execute(RunPaths.default(), provider="stub", recommender="policy")
    c = next(c for c in base.run.companies if any(f.severity is not Severity.MONITOR and len(f.suggestions) >= 2 for f in c.flags))
    f = next(f for f in c.flags if f.severity is not Severity.MONITOR and len(f.suggestions) >= 2)
    blocker = tmp_path / "rec"
    blocker.write_text("not a directory")

    class Fake(ClaudeChooser):
        def _call(self, brief, system=None):
            self._tally(calls=1)
            if "findings" in brief:
                return json.dumps({"rule_id": f.rule_id, "choice": f.suggestions[1].key, "label": "Do this first.",
                                   "reasons": ["a", "b"], "covers": [f.rule_id], "rationale": "r", "confidence": 0.6})
            return json.dumps({"choice": f.suggestions[1].key, "label": "Do this.", "reasons": ["a", "b"], "rationale": "r", "confidence": 0.6})

    ch = Fake(blocker, api_key="k")
    rec = ch.choose(build_brief(c, f, base.run), f)
    assert rec.source == "claude" and rec.key == f.suggestions[1].key and rec.booked == f.suggestions[1].booked
    step = ch.choose_position(build_position_brief(c, base.run), c)
    assert step is not None and step.source == "claude"
    out = recommend_run(base.run, ch)                       # the whole run, six workers, no exception
    assert out.manifest.recommender.startswith("claude")


def _hammer(fn, threads: int = 8, per_thread: int = 3000) -> None:
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        ts = [threading.Thread(target=lambda: [fn() for _ in range(per_thread)]) for _ in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        sys.setswitchinterval(old)


def test_reader_counters_are_exact_under_the_parallel_executor(tmp_path: Path):
    reader = ClaudeReader(tmp_path / "cache", model="m", api_key="k", workers=4)
    _hammer(lambda: reader._tally(calls=1, read_rows=2, unverified=1))
    assert (reader.calls, reader.read_rows, reader.unverified) == (24000, 48000, 24000)
    assert reader.report(1).calls == 24000


def test_recommender_counters_are_exact_under_the_parallel_executor(tmp_path: Path):
    ch = ClaudeChooser(tmp_path / "rec", api_key="k")
    _hammer(lambda: ch._tally(calls=1, cache_hits=1))
    assert (ch.calls, ch.cache_hits) == (24000, 24000)


# ================================================================ C. a reply that validates but misleads

def test_a_meaning_naming_a_figure_the_row_does_not_carry_is_withheld():
    e = _ev()
    raw = _reply(2, aspects=[
        {"kind": "liquidation_preference", "quote": "2x participating preference", "note": "senior 2x participating",
         "meaning": "The new class takes 2x first, so HC's position is worth about $3.2M rather than the $6.75M the columns imply."},
        {"kind": "escrow_or_holdback", "quote": "$1.0M is held in escrow", "note": "$1.0M in escrow",
         "meaning": "The $1.0M in escrow is at risk of claims; at $150M post and 4.5% held the escrow is a small share of value."},
    ], instructions=["Mark the position to $3.2M.", "Do not double count the escrow."],
        novel="A side arrangement worth $0.4M to insiders.", confidence=0.9)
    readings, _ = validate_reply(raw, [e], "fake")
    r = readings[2]
    pref, escrow = r.aspects
    assert pref.meaning == "" and pref.quote and pref.verified                     # the invented figures are gone; the finding is not
    assert escrow.meaning.startswith("The $1.0M in escrow")                       # figures from the note and the columns are fine
    assert r.instructions == ("Do not double count the escrow.",)
    assert r.novel is None
    assert r.withheld == 3


def test_a_withheld_meaning_never_reaches_the_card(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.05, latest_post_money=100.0, prior_mark=5.0, invested=3.0)
    rnd = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, ownership_after=0.045,
                notes="The lead is the CEO's family office and sets its own terms.")
    wb = make_workbook(tmp_path, [pos], [rnd])
    raw = _reply(2, aspects=[{"kind": "related_party", "quote": "the CEO's family office", "note": "insider lead",
                             "meaning": "An insider-led round is weak price evidence; a market participant would pay nearer $4.0M."}])
    _, feed = read_workbook(wb, cfg)
    readings, _ = validate_reply(raw, feed.events, "fake")
    c = _run(wb, cfg, readings).by_company()["Alpha"]
    x130 = _flags(c)["X-130"]
    text = " ".join([x130.message, *x130.points, x130.action, json.dumps(x130.evidence)])
    assert "$4.0M" not in text and "4.0" not in text
    assert "withheld" in text.lower()
    assert x130.evidence["kinds"] == ["related_party"] and c.proposed_mark == pytest.approx(0.045 * 150.0)


def test_a_quote_copied_from_another_row_is_unverified():
    a = _ev()
    b = Event(**{**event(EventType.SECONDARY, date=date(2026, 9, 1), company="Alpha", detail="Secondary", value=150.0,
                         ownership_after=0.04, proceeds=0.7, notes="Sold a sliver to an existing investor."), "row_index": 3})
    raw = {"rows": [
        {"row_index": 2, "aspects": [{"kind": "partial_exit", "quote": "Sold a sliver to an existing investor", "note": "?"}],
         "conflicts": [], "supersedes_portfolio_tab": [], "instructions": [], "novel": None, "confidence": 1},
        {"row_index": 3, "aspects": [{"kind": "liquidation_preference", "quote": "2x participating preference", "note": "?"}],
         "conflicts": [], "supersedes_portfolio_tab": [], "instructions": [], "novel": None, "confidence": 1},
    ]}
    readings, unverified = validate_reply(raw, [a, b], "fake")
    assert unverified == 2 and not readings[2].aspects[0].verified and not readings[3].aspects[0].verified


def test_reader_cache_key_moves_with_prompt_version_model_and_catalogue(tmp_path: Path, monkeypatch):
    from hc_valuation.notes import reader as mod
    payload = {"company": "Alpha", "rows": [{"row_index": 2, "notes": "x"}]}
    k1 = ClaudeReader(tmp_path, model="m").key(payload)
    assert ClaudeReader(tmp_path, model="m2").key(payload) != k1
    monkeypatch.setattr(mod, "PROMPT_VERSION", "999")
    assert ClaudeReader(tmp_path, model="m").key(payload) != k1
    monkeypatch.setattr(mod, "PROMPT_VERSION", mod.PROMPT_VERSION)
    # the catalogue is part of the prompt: a changed definition changes every key
    assert mod.vocabulary_for_prompt() in mod.SYSTEM_PROMPT


def test_recommendation_cache_is_revalidated_against_todays_candidates(tmp_path: Path):
    base = execute(RunPaths.default(), provider="stub", recommender="policy")
    c = next(c for c in base.run.companies if any(f.severity is not Severity.MONITOR and len(f.suggestions) >= 2 for f in c.flags))
    f = next(f for f in c.flags if f.severity is not Severity.MONITOR and len(f.suggestions) >= 2)
    ch = ClaudeChooser(tmp_path / "rec", api_key=None)
    brief = build_brief(c, f, base.run)
    from hc_valuation.recommend import brief_hash
    key = brief_hash(brief, ch.prompt_sha, ch.model)
    ch._write(key, brief, {"choice": "a_key_that_no_longer_exists", "label": "Do it.", "reasons": ["a", "b"], "rationale": "r", "confidence": 0.5})
    rec = ch.choose(brief, f)
    assert rec.source == "policy" and rec.key == f.suggestions[0].key and ch.cache_hits == 0


# ================================================================ E. deciding on a draft

def test_keyword_screen_and_reader_do_not_raise_the_same_aspect_twice(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.05, latest_post_money=100.0, prior_mark=5.0)
    rnd = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, ownership_after=0.045,
                notes="The board is weighing a bankruptcy filing if the round does not close; receivership is possible.")
    wb = make_workbook(tmp_path, [pos], [rnd])
    readings = {2: RowReading(row_index=2, aspects=(
        {"kind": AspectKind.DISTRESS_OR_GOING_CONCERN, "quote": "weighing a bankruptcy filing", "note": "may file"},), source="fake")}
    c = _run(wb, cfg, readings).by_company()["Alpha"]
    fl = _flags(c)
    assert "X-105" in fl and "bankruptcy" in fl["X-105"].evidence["terms"]
    assert "X-130" not in fl, "the keyword screen already raised this sentence"


def test_a_refused_rows_reading_raises_nothing(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.05, latest_post_money=100.0, prior_mark=5.0)
    late = event(date=date(2026, 10, 2), company="Alpha", detail="Series B", value=150.0, ownership_after=0.045,
                 notes="A 3x senior preference sits ahead of HC.")                         # X-905: after the quarter end
    wb = make_workbook(tmp_path, [pos], [late])
    readings = {2: RowReading(row_index=2, aspects=({"kind": AspectKind.LIQUIDATION_PREFERENCE, "quote": "3x senior preference", "note": "x"},),
                              conflicts=({"column": "ownership_after", "column_value": 0.045, "note_says": "3x", "why": "?"},), source="fake")}
    c = _run(wb, cfg, readings).by_company()["Alpha"]
    ids = {f.rule_id for f in c.flags}
    assert "X-900" in ids and not ids & {"X-130", "X-131", "X-132", "X-105"}
    failed = {2: RowReading(row_index=2, failed="APIStatusError: 529", source="claude:m")}
    assert "X-132" not in {f.rule_id for f in _run(wb, cfg, failed).by_company()["Alpha"].flags}
    assert c.proposed_mark == pytest.approx(5.0)


def test_a_reading_only_adds_findings_and_never_moves_mark_or_readiness_downwards(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.05, latest_post_money=100.0, prior_mark=5.0)
    rnd = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, ownership_after=0.045,
                notes="The lead is a family office of the CEO. Ownership per the cap table is 4.7%.")
    wb = make_workbook(tmp_path, [pos], [rnd])
    plain = _run(wb, cfg).by_company()["Alpha"]
    readings = {2: RowReading(row_index=2,
                              aspects=({"kind": AspectKind.RELATED_PARTY, "quote": "family office of the CEO", "note": "insider"},),
                              conflicts=({"column": "ownership_after", "column_value": 0.045, "note_says": "Ownership per the cap table is 4.7%", "why": "?"},),
                              source="fake")}
    read = _run(wb, cfg, readings).by_company()["Alpha"]
    assert (read.proposed_mark, read.booked_mark, read.steps) == (plain.proposed_mark, plain.booked_mark, plain.steps)
    assert {f.rule_id for f in plain.flags} <= {f.rule_id for f in read.flags}
    assert plain.readiness is Readiness.READY and read.readiness is Readiness.NEEDS_REVIEW
    # Both of the reader's findings on one row sit in the notes family, so a single reading cannot
    # escalate a clean position to a decision on its own (the policy's two-family rule needs an
    # independent concern). Readiness stays Needs Review: a reading is never a missing input.
    assert read.disposition.value == "REVIEW" and read.readiness is not Readiness.BLOCKED
    for f in read.flags:
        if f.rule_id in ("X-130", "X-131"):
            assert f.severity is Severity.REVIEW and f.suggestions and all(s.booked >= 0 for s in f.suggestions)


# ================================================================ G. the request shape for a live call

def test_reader_call_leaves_headroom_for_a_long_reply(tmp_path: Path, monkeypatch):
    seen: dict = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(json.dumps(_reply(2)), seen))
    reader = ClaudeReader(tmp_path / "cache", model="m", api_key="k")
    reader._call({"company": "Alpha", "rows": [{"row_index": 2}]})
    assert seen["request"]["max_tokens"] >= 4000 and seen["timeout"] >= 60


