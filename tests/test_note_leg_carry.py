"""A convertible-note leg carried at cost survives the quarter boundary as a number, not as prose.

Found by the synthetic Q1 2027 chain (HARDENING_REPORT.md, D-5): Yarrowbank's Q4 mark was 0.6 of
equity plus a 0.3 note HC funded, carried at cost on its own leg (M-060). The emitted Q1 book has one
`Prior Mark` column, 0.9, and the sidecar explained the departure only in words — so Q1 read 0.9 as
equity, and when the note was repaid (0.31 of cash) the engine kept the 0.9 *and* booked the cash: the
principal counted twice, with only an X-115 REVIEW between the double count and the book. The sidecar
now carries `note_legs` and the next run restores the leg.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from hc_valuation.config import load_config, write_next_policy
from hc_valuation.engine.inputs import EventType
from hc_valuation.export.snapshot import note_legs, write_next_quarter_workbook
from hc_valuation.pipeline import load_note_legs
from tests.conftest import event, make_workbook, position, run_workbook


def _funded_note_quarter(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=7.7, ownership=0.084, prior_mark=0.6468, invested=2.0)
    note = event(EventType.CONVERTIBLE_NOTE, detail="$1.0M bridge note, $45.0M valuation cap", hc_investment=0.3,
                 notes="Uncapped interest, converts at next priced round. HC participated in the note.")
    src = make_workbook(tmp_path, [pos], [note])
    run, _ = run_workbook(src, cfg)
    return src, run


def test_sidecar_carries_the_note_leg_as_a_number(tmp_path: Path, cfg):
    src, run = _funded_note_quarter(tmp_path, cfg)
    c = run.by_company()["Alpha"]
    assert c.note_at_cost == pytest.approx(0.3) and c.proposed_mark == pytest.approx(0.6468 + 0.3)
    assert note_legs(run) == [{"company": "Alpha", "amount_musd": 0.3,
                               "reason": "note leg $0.30M carried at cost inside the $0.95M prior mark (M-060)"}]
    out = write_next_quarter_workbook(run, src, tmp_path / "next" / "portfolio_Q4_2026.xlsx", cfg)
    sidecar = yaml.safe_load((out.parent / "open_items_carry.yaml").read_text())
    assert sidecar["note_legs"] == note_legs(run)
    assert load_note_legs(out.parent / "open_items_carry.yaml") == {"Alpha": 0.3}


def _next_quarter(tmp_path: Path, cfg, events):
    src, run = _funded_note_quarter(tmp_path, cfg)
    out = write_next_quarter_workbook(run, src, tmp_path / "next" / "portfolio_Q4_2026.xlsx", cfg)
    sidecar = out.parent / "open_items_carry.yaml"
    from hc_valuation.pipeline import load_mark_basis, load_prior_open_items
    cfg4 = load_config(write_next_policy(_policy_copy(tmp_path)))
    # the emitted Q4 book, with the new quarter's rows appended to its (empty) activity tab
    import openpyxl
    wb = openpyxl.load_workbook(out)
    ws = wb["Q4 2026 Activity"]
    from hc_valuation.ingest.schema import ACTIVITY_COLUMNS
    inv = {v: k for k, v in ACTIVITY_COLUMNS.items()}
    for e in events:
        ws.append([e.get(ACTIVITY_COLUMNS[h]) for h in ACTIVITY_COLUMNS])
    wb.save(out)
    from hc_valuation.engine.models import MarketData, OverrideLedger
    from hc_valuation.engine.run import run_valuation
    from hc_valuation.ingest.reader import read_workbook
    from hc_valuation.ingest.validate import validate
    snap, feed = read_workbook(out, cfg4)
    issues = validate(snap, feed, cfg4, explained_departures=load_mark_basis(sidecar))
    assert not [i for i in issues if i.blocking]
    return run_valuation(snap, feed, MarketData(as_of=cfg4.quarter.measurement_date), OverrideLedger(), cfg4,
                         validation=tuple(issues), prior_open_items=load_prior_open_items(sidecar),
                         prior_note_legs=load_note_legs(sidecar), input_sha256="x", input_file=out.name,
                         generated_at=None, market_data_source="test")


def test_note_repaid_next_quarter_clears_the_leg_instead_of_counting_it_twice(tmp_path: Path, cfg):
    from datetime import datetime
    repaid = {"date": datetime(2026, 11, 20), "company": "Alpha", "event_type": EventType.NOTE_REPAID.value,
              "detail": "Bridge note repaid with interest", "proceeds": 0.31, "notes": "Repaid from operating cash."}
    run = _next_quarter(tmp_path, cfg, [repaid])
    c = run.by_company()["Alpha"]
    assert c.prior_mark == pytest.approx(0.9468)
    assert c.note_at_cost == 0.0 and c.equity_mark == pytest.approx(0.6468)
    assert c.proposed_mark == pytest.approx(0.6468)            # not 0.9468: the principal came back as cash
    assert c.realized_quarter == pytest.approx(0.31)
    assert "X-115" in {f.rule_id for f in c.flags}


def test_no_activity_next_quarter_keeps_the_split_and_the_total(tmp_path: Path, cfg):
    run = _next_quarter(tmp_path, cfg, [])
    c = run.by_company()["Alpha"]
    assert c.proposed_mark == pytest.approx(0.9468) and c.note_at_cost == pytest.approx(0.3) and c.equity_mark == pytest.approx(0.6468)


def test_a_priced_round_next_quarter_folds_the_leg_as_before(tmp_path: Path, cfg):
    from datetime import datetime
    rnd = {"date": datetime(2026, 11, 20), "company": "Alpha", "event_type": EventType.PRICED_ROUND.value,
           "detail": "Series B", "value": 50.0, "ownership_after": 0.09, "notes": "Led by a new investor; the note rolled in at its cap."}
    run = _next_quarter(tmp_path, cfg, [rnd])
    c = run.by_company()["Alpha"]
    assert c.proposed_mark == pytest.approx(0.09 * 50.0) and c.note_at_cost == 0.0


def test_a_leg_the_prior_mark_cannot_hold_is_ignored(tmp_path: Path, cfg):
    """A sidecar claiming a 5.0 leg inside a 0.95 mark is wrong; the mark stays equity and X-904 says why."""
    from hc_valuation.engine.models import MarketData, OverrideLedger
    from hc_valuation.engine.run import run_valuation
    from hc_valuation.ingest.reader import read_workbook
    pos = position(company="Alpha", prior_mark=0.95, latest_post_money=7.7, ownership=0.084)
    src = make_workbook(tmp_path, [pos], [])
    snap, feed = read_workbook(src, cfg)
    run = run_valuation(snap, feed, MarketData(as_of=cfg.quarter.measurement_date), OverrideLedger(), cfg,
                        prior_note_legs={"Alpha": 5.0}, input_sha256="x", input_file="x", market_data_source="test")
    c = run.by_company()["Alpha"]
    assert c.note_at_cost == 0.0 and c.proposed_mark == pytest.approx(0.95)


def _policy_copy(tmp_path: Path) -> Path:
    import shutil
    from hc_valuation.config import repo_root
    dst = tmp_path / "rules" / "2026Q3.yaml"
    dst.parent.mkdir(exist_ok=True)
    shutil.copy(repo_root() / "rules" / "2026Q3.yaml", dst)
    return dst
