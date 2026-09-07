"""An event resolves an open item opened earlier in the same quarter, not only one carried in.

Found by the synthetic Q2 2027 chain (HARDENING_REPORT.md, D-11): a term sheet signed on 15 March and
closed as a priced round the same day stayed a `term_sheet` open item, rolled into the next quarter,
aged past `term_sheet_stale_quarters` and put the position in front of a reviewer (E-07) for a deal
that had closed three months earlier. `RESOLVES` was applied to prior-quarter items only.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import OpenItemKind
from tests.conftest import event, make_workbook, position, run_workbook


def _kinds(run, company="Alpha"):
    return [i.kind for i in run.by_company()[company].open_items]


def test_term_sheet_then_round_in_one_quarter_leaves_no_term_sheet_item(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=22.8, ownership=0.095, prior_mark=2.166)
    ts = event(EventType.TERM_SHEET, date=date(2026, 8, 15), detail="Series B term sheet at ~$40.0M post", value=40.0)
    rnd = event(date=date(2026, 8, 15), detail="Series B", value=40.0, hc_investment=0.5, ownership_after=0.1075,
                notes="$10.0M round led by a new investor. HC participated.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [ts, rnd]), cfg)
    c = run.by_company()["Alpha"]
    assert c.proposed_mark == 0.1075 * 40.0 and _kinds(run) == []
    # ... and a term sheet dated after the round (a new one) is still open
    later = event(EventType.TERM_SHEET, date=date(2026, 9, 10), detail="Series C term sheet at ~$60.0M post", value=60.0)
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [rnd, later], name="b.xlsx"), cfg)
    assert _kinds(run2) == [OpenItemKind.TERM_SHEET]


def test_note_then_listing_in_one_quarter_converts_the_note(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=100.0, ownership=0.05, prior_mark=5.0)
    note = event(EventType.CONVERTIBLE_NOTE, date=date(2026, 7, 5), detail="$2.0M bridge note, $120.0M valuation cap", hc_investment=0.2,
                 notes="Converts at next priced round. HC participated in the note.")
    ipo = event(EventType.IPO, date=date(2026, 9, 20), detail="Listed on Nasdaq", value=500.0, ownership_after=0.045,
                notes="Priced at the top of the range. HC shares subject to a 180-day lock-up.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [note, ipo]), cfg)
    assert _kinds(run) == [OpenItemKind.IPO_LOCKUP]        # the listing's own item stays; the note is gone


def test_a_closing_with_no_cash_keeps_the_item_it_opened(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=842.1, ownership=0.058, prior_mark=48.8, invested=14.0)
    closed = event(EventType.ACQ_CLOSED, date=date(2026, 8, 20), detail="All-cash acquisition", value=30.0, notes="Transaction closed.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [closed]), cfg)
    assert _kinds(run) == [OpenItemKind.UNCONFIRMED_EXIT]
