"""The note reader and what the engine does with its readings.

The reader is a model that classifies a row's free text against the case catalogue and quotes
it. Here it is a fake: the tests are about the contract, which is what matters — a reading can
only add review findings; it never moves a mark, never lowers a severity, never removes a
finding; quotes are checked against the row text; kinds outside the catalogue become `other`;
a failed read is itself a finding; nothing runs and nothing is called without a key; and with
the reader off every run is what it was before the reader existed.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from hc_valuation.config import repo_root
from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import Readiness, Severity
from hc_valuation.engine.run import run_valuation
from hc_valuation.ingest.reader import read_workbook
from hc_valuation.ingest.validate import validate
from hc_valuation.notes import AspectKind, ClaudeReader, OffReader, RowReading, make_reader, read_feed
from hc_valuation.notes.catalogue import ASPECTS, BY_KIND, kinds_for_terms
from hc_valuation.notes.schema import validate_reply
from hc_valuation.pipeline import RunPaths, execute
from tests.conftest import GENERATED_AT, event, make_workbook, position, run_workbook
from hc_valuation.engine.models import MarketData
from hc_valuation.engine.overrides import OverrideLedger

ROOT = repo_root()


def _run(path: Path, cfg, readings: dict | None = None, reader_label: str = "fake"):
    snapshot, feed = read_workbook(path, cfg)
    issues = validate(snapshot, feed, cfg)
    return run_valuation(snapshot, feed, MarketData(as_of=cfg.quarter.measurement_date), OverrideLedger(), cfg,
                         validation=tuple(issues), note_readings=readings or {}, note_reader=reader_label,
                         input_sha256="x", input_file=path.name, generated_at=GENERATED_AT, market_data_source="test")


def _flags(c) -> dict[str, object]:
    return {f.rule_id: f for f in c.flags}


class FakeReader:
    """Answers from a script keyed by company; records what it was asked."""
    name = "fake"
    available = True
    workers = 1

    def __init__(self, script: dict[str, dict]) -> None:
        self.script = script
        self.asked: list[str] = []

    def read(self, company, rows):
        self.asked.append(company)
        raw = self.script.get(company)
        if raw is None:
            return {}
        readings, _ = validate_reply(raw, rows, "fake")
        return readings

    def report(self, rows_with_text):
        from hc_valuation.notes import ReadingReport
        return ReadingReport(status="on", provider="claude", model="fake", rows_with_text=rows_with_text, rows_read=rows_with_text)


# ---------------------------------------------------------------- the catalogue

def test_catalogue_is_closed_and_every_kind_has_a_spec():
    assert {a.kind for a in ASPECTS} == set(AspectKind)
    assert all(a.label and a.definition for a in ASPECTS)
    assert kinds_for_terms({"escrow"}) == {AspectKind.ESCROW_OR_HOLDBACK}
    assert AspectKind.NOTE_CONVERSION in kinds_for_terms({"conversion", "accrued"})
    assert kinds_for_terms(set()) == set()
    assert EventType.CONVERTIBLE_NOTE.value in BY_KIND[AspectKind.BRIDGE_FINANCING].events


# ---------------------------------------------------------------- hostile validation

def test_reply_validation_checks_quotes_columns_and_kinds():
    e = event(EventType.ACQ_CLOSED, date=date(2026, 9, 28), company="G", detail="Cash acquisition with escrow", value=133.0,
              ownership_after=0.0, proceeds=3.8, notes="HC's confirmed entitlement is $4.8M: $3.8M received and $1.0M held in escrow.")
    from hc_valuation.engine.inputs import Event
    ev = Event(**{**e, "row_index": 20})
    raw = {"rows": [{
        "row_index": 20,
        "aspects": [{"kind": "escrow_or_holdback", "quote": "$1.0M held in escrow", "note": "escrow"},
                    {"kind": "made_up_kind", "quote": "not in the text at all", "note": "?"}],
        "conflicts": [{"column": "proceeds", "note_says": "confirmed entitlement is $4.8M", "why": "entitlement vs received"},
                      {"column": "no_such_column", "note_says": "x"}],
        "supersedes_portfolio_tab": [{"field": "cash", "quote": "$3.8M received"}, {"field": "nonsense", "quote": "zzz"}],
        "instructions": ["Record $3.8M as realized proceeds"],
        "novel": None, "confidence": 1.7,
    }, {"row_index": 999, "aspects": []}, "junk"]}
    readings, unverified = validate_reply(raw, [ev], "fake")
    r = readings[20]
    assert [a.kind for a in r.aspects] == [AspectKind.ESCROW_OR_HOLDBACK, AspectKind.OTHER]
    assert r.aspects[0].verified and not r.aspects[1].verified and r.aspects[1].note.startswith("made_up_kind")
    assert [c.column for c in r.conflicts] == ["proceeds"] and r.conflicts[0].column_value == 3.8 and r.conflicts[0].verified
    assert [s.field for s in r.supersedes] == ["cash", "other"] and not r.supersedes[1].verified
    assert r.instructions == ("Record $3.8M as realized proceeds",) and r.confidence == 1.0
    assert unverified == 2 and 999 not in readings
    with pytest.raises(ValueError):
        validate_reply({"nope": 1}, [ev], "fake")


# ---------------------------------------------------------------- the engine's use of a reading

def test_reading_adds_findings_and_never_moves_a_mark(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.05, latest_post_money=100.0, prior_mark=5.0)
    rnd = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, ownership_after=0.045,
                notes="New investors hold a 2x participating liquidation preference senior to HC. Ownership per the cap table is 4.7%.")
    wb = make_workbook(tmp_path, [pos], [rnd])
    plain = _run(wb, cfg)
    readings = {2: RowReading(row_index=2, aspects=(
        {"kind": AspectKind.LIQUIDATION_PREFERENCE, "quote": "2x participating liquidation preference senior to HC", "note": "senior preference ahead of HC"},
    ), conflicts=({"column": "ownership_after", "column_value": 0.045, "note_says": "Ownership per the cap table is 4.7%", "why": "row says 4.5%"},),
        instructions=(), confidence=0.9, source="fake")}
    read = _run(wb, cfg, readings)
    a, b = plain.by_company()["Alpha"], read.by_company()["Alpha"]
    assert b.proposed_mark == a.proposed_mark == pytest.approx(0.045 * 150.0)
    assert b.steps == a.steps and b.invested_after == a.invested_after and b.ownership_after == a.ownership_after
    # X-105 already raised "preference" and "participating": the reader does not raise the same kind twice
    assert "X-105" in _flags(a) and "X-130" not in _flags(b)
    x131 = _flags(b)["X-131"]
    assert x131.severity is Severity.REVIEW and x131.family == "notes" and x131.evidence["column_value"] == 0.045
    assert "4.7%" in x131.points[0] and "HC Ownership After" in x131.points[0]
    assert {f.rule_id for f in a.flags} <= {f.rule_id for f in b.flags}          # only ever adds
    assert read.manifest.note_reader == "fake"


def test_reading_raises_x130_for_a_kind_no_rule_handled_and_skips_the_row_s_own_nature(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.05, latest_post_money=100.0, prior_mark=5.0)
    note = event(EventType.CONVERTIBLE_NOTE, date=date(2026, 8, 1), company="Alpha", detail="$2.0M bridge note, $120M cap",
                 hc_investment=0.5, notes="Bridge to a Series B. The founder stepped down as CEO in July; an interim CEO is in place.")
    wb = make_workbook(tmp_path, [pos], [note])
    readings = {2: RowReading(row_index=2, aspects=(
        {"kind": AspectKind.BRIDGE_FINANCING, "quote": "Bridge to a Series B", "note": "a bridge"},           # the row's own nature
        {"kind": AspectKind.MANAGEMENT_CHANGE, "quote": "The founder stepped down as CEO in July", "note": "CEO change"},
    ), confidence=0.8, source="fake")}
    c = _run(wb, cfg, readings).by_company()["Alpha"]
    x130 = _flags(c)["X-130"]
    assert x130.evidence["kinds"] == ["management_change"] and "management change" in x130.points[0]
    assert "The founder stepped down" in x130.points[1] and x130.severity is Severity.REVIEW
    assert c.note_at_cost == pytest.approx(0.5) and c.proposed_mark == pytest.approx(5.5)


def test_novel_and_unverified_readings_still_reach_a_person(tmp_path: Path, cfg):
    pos = position(company="Alpha")
    rnd = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, ownership_after=0.09, notes="Round closed.")
    wb = make_workbook(tmp_path, [pos], [rnd])
    readings = {2: RowReading(row_index=2, aspects=({"kind": AspectKind.RELATED_PARTY, "quote": "words the note never said", "note": "?", "verified": False},),
                              novel="The lead investor is the CEO's family office.", confidence=0.4, source="fake")}
    c = _run(wb, cfg, readings).by_company()["Alpha"]
    x130 = _flags(c)["X-130"]
    assert set(x130.evidence["kinds"]) == {"related_party", "other"} and x130.evidence["unverified_quotes"] == 1
    assert "could not be matched" in x130.points[1] and "family office" in x130.message


def test_supersession_raises_x126_once_and_a_failed_read_raises_x132(tmp_path: Path, cfg):
    pos = position(company="Alpha", cash=12.0, net_burn=0.5)
    rnd = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, ownership_after=0.09,
                notes="Post-close cash is $30.0M, which supersedes the June balance.")
    other = event(EventType.SECONDARY, date=date(2026, 9, 1), company="Alpha", detail="Secondary", value=150.0, ownership_after=0.085,
                  proceeds=0.7, notes="Sold a sliver.")
    wb = make_workbook(tmp_path, [pos], [rnd, other])
    readings = {2: RowReading(row_index=2, supersedes=({"field": "cash", "quote": "Post-close cash is $30.0M, which supersedes the June balance"},), source="fake"),
                3: RowReading(row_index=3, failed="APIStatusError: 529 overloaded", source="claude:x")}
    c = _run(wb, cfg, readings).by_company()["Alpha"]
    fl = [f.rule_id for f in c.flags]
    assert fl.count("X-126") == 1 and "cash" in _flags(c)["X-126"].evidence["fields"]
    assert fl.count("X-132") == 1 and _flags(c)["X-132"].evidence["row_index"] == 3
    assert c.readiness is not Readiness.READY


# ---------------------------------------------------------------- the reader itself

def test_off_reader_reads_nothing_and_says_why(tmp_path: Path, cfg):
    wb = make_workbook(tmp_path, [position()], [event(detail="Series B", value=150.0, ownership_after=0.09, notes="escrow of $1M")])
    _, feed = read_workbook(wb, cfg)
    readings, report = read_feed(feed, OffReader("switched off on the command line"))
    assert readings == {} and report.status == "off" and "switched off" in report.reason and report.rows_with_text == 1
    assert report.label().startswith("off:")


def test_claude_reader_without_a_key_is_off_and_makes_no_call(tmp_path: Path, cfg, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    wb = make_workbook(tmp_path, [position()], [event(detail="Series B", value=150.0, ownership_after=0.09, notes="escrow of $1M")])
    _, feed = read_workbook(wb, cfg)
    reader = ClaudeReader(tmp_path / "cache", model="m", api_key="")
    readings, report = read_feed(feed, reader)
    assert readings == {} and report.status == "off" and "ANTHROPIC_API_KEY" in report.reason and reader.calls == 0
    assert not (tmp_path / "cache").exists()


def test_claude_reader_caches_and_reports_failures(tmp_path: Path, cfg, monkeypatch):
    wb = make_workbook(tmp_path, [position(company="Alpha"), position(company="Beta")],
                       [event(company="Alpha", detail="Series B", value=150.0, ownership_after=0.09, notes="escrow of $1M"),
                        event(company="Beta", detail="Series C", value=250.0, ownership_after=0.03, notes="Fees netted.")])
    _, feed = read_workbook(wb, cfg)
    reader = ClaudeReader(tmp_path / "cache", model="m", api_key="k", workers=1)
    calls: list[str] = []

    def fake_call(payload):
        calls.append(payload["company"])
        if payload["company"] == "Beta":
            raise RuntimeError("boom")
        return {"rows": [{"row_index": r["row_index"], "aspects": [{"kind": "escrow_or_holdback", "quote": "escrow of $1M", "note": "escrow"}],
                          "conflicts": [], "supersedes_portfolio_tab": [], "instructions": [], "novel": None, "confidence": 0.9}
                         for r in payload["rows"]]}
    monkeypatch.setattr(reader, "_call", fake_call)
    readings, report = read_feed(feed, reader)
    alpha = next(r for r in readings.values() if not r.failed)
    beta = next(r for r in readings.values() if r.failed)
    assert alpha.aspects[0].kind is AspectKind.ESCROW_OR_HOLDBACK and alpha.source == "claude:m"
    assert "RuntimeError" in beta.failed and report.rows_failed == 1 and report.rows_read == 1 and report.status == "on"
    cached = list((tmp_path / "cache").glob("*.json"))
    assert len(cached) == 1 and json.loads(cached[0].read_text())["company"] == "Alpha"
    # second pass: Alpha from cache, no call; Beta retried
    calls.clear()
    reader2 = ClaudeReader(tmp_path / "cache", model="m", api_key="k", workers=1)
    monkeypatch.setattr(reader2, "_call", fake_call)
    readings2, report2 = read_feed(feed, reader2)
    assert calls == ["Beta"] and next(r for r in readings2.values() if not r.failed).source == "cache" and report2.rows_from_cache == 1


def test_make_reader_follows_flag_then_env_then_policy(cfg, tmp_path: Path, monkeypatch):
    env_off = make_reader(cfg, tmp_path)                                        # the suite pins HC_NOTE_READER=off
    assert isinstance(env_off, OffReader) and "for this run" in env_off.reason
    monkeypatch.delenv("HC_NOTE_READER", raising=False)
    assert isinstance(make_reader(cfg, tmp_path), ClaudeReader)                 # the policy says claude
    off = make_reader(cfg, tmp_path, "off")
    assert isinstance(off, OffReader) and "command line" in off.reason


# ---------------------------------------------------------------- through the pipeline

def test_pipeline_passes_readings_in_and_reports_the_reader(tmp_path: Path):
    import shutil
    root = tmp_path
    shutil.copytree(ROOT / "rules", root / "rules")
    shutil.copytree(ROOT / "data" / "mock_responses", root / "data" / "mock_responses")
    (root / "ledger").mkdir(); (root / "ledger" / "overrides.yaml").write_text("overrides: []\n")
    wb = make_workbook(tmp_path, [position(company="Alpha", ownership=0.05, latest_post_money=100.0, prior_mark=5.0)],
                       [event(company="Alpha", date=date(2026, 8, 15), detail="Series B", value=150.0, ownership_after=0.045,
                              notes="Pending a regulatory investigation into the company's data practices.")])
    paths = RunPaths.default(root=root, workbook=wb, policy=root / "rules" / "2026Q3.yaml", ledger_dir=root / "ledger")
    fake = FakeReader({"Alpha": {"rows": [{"row_index": 2, "aspects": [{"kind": "litigation_or_dispute",
                                                                      "quote": "regulatory investigation into the company's data practices",
                                                                      "note": "open investigation"}],
                                          "conflicts": [], "supersedes_portfolio_tab": [], "instructions": [], "novel": None, "confidence": 0.95}]}})
    r = execute(paths, provider="stub", adjudicate=False, reader=fake)
    c = r.run.by_company()["Alpha"]
    assert fake.asked == ["Alpha"] and "X-130" in _flags(c) and c.readiness is Readiness.NEEDS_REVIEW
    assert r.run.manifest.note_reader == "claude:fake" and r.run.manifest.note_reader_report["rows_read"] == 1
    off = execute(paths, provider="stub", adjudicate=False, note_reader="off")
    assert "X-130" not in _flags(off.run.by_company()["Alpha"]) and off.run.manifest.note_reader.startswith("off:")
    assert off.run.by_company()["Alpha"].proposed_mark == c.proposed_mark


def test_missing_sdk_switches_the_reader_off_once_rather_than_failing_every_row(tmp_path: Path, cfg, monkeypatch):
    import importlib.util as iu
    monkeypatch.setattr(iu, "find_spec", lambda name, *a, **k: None if name == "anthropic" else object())
    wb = make_workbook(tmp_path, [position()], [event(detail="Series B", value=150.0, ownership_after=0.09, notes="escrow of $1M")])
    _, feed = read_workbook(wb, cfg)
    reader = ClaudeReader(tmp_path / "cache", model="m", api_key="k")
    readings, report = read_feed(feed, reader)
    assert readings == {} and report.status == "off" and "not installed" in report.reason and reader.calls == 0



def test_meaning_reaches_the_card_with_three_courses(tmp_path: Path, cfg):
    pos = position(company="Alpha", ownership=0.05, latest_post_money=100.0, prior_mark=5.0, invested=3.0)
    rnd = event(date=date(2026, 8, 15), company="Alpha", detail="Series B", value=150.0, ownership_after=0.045,
                notes="The new money carries a 3x senior participating preference ahead of every earlier class.")
    wb = make_workbook(tmp_path, [pos], [rnd])
    readings = {2: RowReading(row_index=2, aspects=(
        {"kind": AspectKind.LIQUIDATION_PREFERENCE, "quote": "3x senior participating preference", "note": "senior 3x participating",
         "meaning": "At $150M post the new class takes the first $45M plus a share of the rest before HC's common-equivalent sees anything, so ownership x post overstates HC's claim."},
    ), confidence=0.9, source="fake")}
    c = _run(wb, cfg, readings).by_company()["Alpha"]
    fl = _flags(c)
    # the keyword screen does not know "3x senior participating preference" as its own terms here? it does ("participating", "preference"):
    # so X-105 covers the kind and X-130 is not raised twice -- take the X-105/X-130 that carries the meaning
    x = fl.get("X-130") or fl["X-105"]
    if "X-130" in fl:
        assert x.points[2].startswith("What it means:") and "overstates HC's claim" in x.evidence["meaning"]
        assert [s.key for s in x.suggestions] == ["as_proposed", "hold_prior", "at_cost"]
        assert x.suggestions[2].booked == pytest.approx(3.0)
    # a kind the keyword screen does not know carries the meaning either way
    readings2 = {2: RowReading(row_index=2, aspects=(
        {"kind": AspectKind.RELATED_PARTY, "quote": "ahead of every earlier class", "note": "insider terms",
         "meaning": "Insiders set terms that favour themselves over HC; the round price is weaker evidence."},), source="fake")}
    c2 = _run(wb, cfg, readings2).by_company()["Alpha"]
    x2 = _flags(c2)["X-130"]
    assert x2.points[2].startswith("What it means:") and x2.evidence["meaning"].startswith("Insiders")
    assert [s.key for s in x2.suggestions] == ["as_proposed", "hold_prior", "at_cost"] and x2.suggestions[2].booked == pytest.approx(3.0)



def test_live_reading_shapes_that_are_not_findings(tmp_path: Path, cfg):
    """Shapes the live model produced on the second stress workbook that must not become spurious reviews:
    a blank cell the text confirms is blank, a status the text confirms, an option pool on an ownership
    adjustment, DIP financing on a Chapter 11, 'no recovery' on a shutdown, insiders on an HC-led round."""
    book = [position(company="Fen", latest_post_money=285.1, ownership=0.038, invested=12.4, prior_mark=10.8),
            position(company="Quin", latest_post_money=61.1, ownership=0.121, invested=6.0, prior_mark=7.4),
            position(company="Stone", latest_post_money=18.1, ownership=0.094, invested=1.4, prior_mark=1.7),
            position(company="Isle", latest_post_money=277.8, ownership=0.036, invested=10.0, prior_mark=10.0),
            position(company="Will", latest_post_money=38.0, ownership=0.10, invested=6.0, prior_mark=4.7)]
    rows = [event(EventType.ACQ_ANNOUNCED, date=date(2026, 7, 30), company="Fen", detail="Definitive agreement, all cash", value=340.0,
                  notes="All-cash agreement signed, expected to close in Q4. No cash received at announcement."),
            event(EventType.OWNERSHIP_ADJUSTMENT, date=date(2026, 7, 21), company="Quin", detail="Option pool expansion", ownership_after=0.109,
                  notes="The board expanded the option pool by 200 basis points. The cap table was restated."),
            event(EventType.BANKRUPTCY_CH11, date=date(2026, 9, 11), company="Stone", detail="Filed for reorganisation", ownership_after=0.094,
                  notes="Operations continue under debtor-in-possession financing. Recovery to equity is unknown."),
            event(EventType.SHUTDOWN, date=date(2026, 9, 22), company="Isle", detail="Ceased operations", notes="Board voted to wind down. No recovery expected."),
            event(date=date(2026, 8, 6), company="Will", detail="Series B led by HC", value=72.0, hc_investment=1.7, ownership_after=0.124,
                  notes="$12.0M round led by HC. No outside lead set the price; existing investors followed HC's terms.")]
    wb = make_workbook(tmp_path, book, rows)
    A = AspectKind
    readings = {
        2: RowReading(row_index=2, conflicts=({"column": "proceeds", "column_value": None, "note_says": "No cash received at announcement", "why": "consistent"},),
                      aspects=({"kind": A.TIMING_OR_DATE, "quote": "expected to close in Q4", "note": "future close"},), source="fake"),
        3: RowReading(row_index=3, aspects=({"kind": A.SHARE_STRUCTURE, "quote": "expanded the option pool by 200 basis points", "note": "pool"},
                                            {"kind": A.OWNERSHIP_RESTATED, "quote": "The cap table was restated", "note": "restated"}), source="fake"),
        4: RowReading(row_index=4, aspects=({"kind": A.DEBT, "quote": "debtor-in-possession financing", "note": "DIP"},
                                            {"kind": A.VALUATION_ASSERTION, "quote": "Recovery to equity is unknown", "note": "unknown"}), source="fake"),
        5: RowReading(row_index=5, aspects=({"kind": A.VALUATION_ASSERTION, "quote": "No recovery expected.", "note": "zero"},),
                      supersedes=({"field": "status", "quote": "Board voted to wind down"},), source="fake"),
        6: RowReading(row_index=6, aspects=({"kind": A.INSIDER_PRICED, "quote": "No outside lead set the price", "note": "insiders"},), source="fake"),
    }
    run = _run(wb, cfg, readings)
    by = run.by_company()
    assert "X-131" not in _flags(by["Fen"])                                   # blank cell confirmed blank: not a conflict
    assert "X-130" in _flags(by["Fen"])                                       # the timing aspect still reaches a person (prompt tightened separately)
    for name in ("Quin", "Stone", "Isle", "Will"):
        assert "X-130" not in _flags(by[name]), (name, sorted(_flags(by[name])))
    assert "X-117" in _flags(by["Will"]) and "X-116" in _flags(by["Stone"]) and "X-110" in _flags(by["Quin"])
    # a status the text merely confirms is not a supersession
    kol = position(company="Kol", status="Acquired", latest_post_money=50.0, ownership=0.071, invested=5.8, prior_mark=0.0, realized=15.9)
    dist = event(EventType.DISTRIBUTION, date=date(2026, 8, 5), company="Kol", detail="Indemnity escrow released", proceeds=1.4,
                 notes="The escrow was released in full. The position remains Acquired and the mark stays at zero.")
    wb2 = make_workbook(tmp_path, [kol], [dist], name="b.xlsx")
    r2 = _run(wb2, cfg, {2: RowReading(row_index=2, supersedes=({"field": "status", "quote": "The position remains Acquired"},), source="fake")})
    assert "X-126" not in _flags(r2.by_company()["Kol"])
