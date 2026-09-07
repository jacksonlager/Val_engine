"""Three late-quarter rows the reviewer added to the Q3 2026 activity tab, each with a note that says
what the right answer is:

* Duskfern — a Series B into which HC's $0.5M note converts, no new cash, 7.5% after. The note leg
  must vanish, the principal count once, and the reviewer be asked about the conversion, not the
  (now moot) bridge.
* Gryphonel — the announced $133M acquisition closed early: $3.8M received, $1.0M in a 12-month
  escrow. $3.8M is realized; the escrow is a claim to value separately, carried as an open item.
* Halcyra — the signed Series B term sheet was withdrawn; nothing closed; the note reports $1.3M
  cash and $0.65M burn (two months). The term sheet's item and indication go; the mark holds;
  funding risk is escalated; the cash/burn in prose reaches a person, never the runway screen.

Before this the engine treated "Term Sheet Withdrawn" as unknown (Blocked, term sheet still open),
raised the stale note-bridge question on the conversion, screened the words "conversion" and
"escrow" a second time, and never carried the escrow claim forward.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import OpenItemKind, Readiness
from hc_valuation.ingest import normalize as nz
from tests.conftest import event, make_workbook, position, run_workbook


def _flags(c) -> dict[str, object]:
    return {f.rule_id: f for f in c.flags}


# ---------------------------------------------------------------- Duskfern: the note converts

def test_note_converting_in_the_round_counts_the_principal_once(tmp_path: Path, cfg):
    pos = position(company="Duskfern", latest_post_money=100.0, ownership=0.061, invested=5.6, prior_mark=6.1,
                   cash=4.0, net_burn=1.0)
    note = event(EventType.CONVERTIBLE_NOTE, date=date(2026, 8, 28), company="Duskfern", detail="Convertible note",
                 hc_investment=0.5, notes="$0.5M note, 20% discount, $150M cap.")
    series_b = event(date=date(2026, 9, 25), company="Duskfern", detail="Series B; existing note converts",
                     value=150.0, hc_investment=0.0, ownership_after=0.075,
                     notes="HC's $0.5M note funded on August 28 converts fully into Series B equity, including accrued "
                           "interest. No additional HC cash is invested. The final cap table confirms 7.5% fully diluted "
                           "ownership, including converted shares. Remove the separate note position and verify the "
                           "conversion schedule. Do not count the original $0.5M contribution twice.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [note, series_b]), cfg)
    c = run.by_company()["Duskfern"]
    assert c.proposed_mark == pytest.approx(0.075 * 150.0) and c.note_at_cost == 0.0
    assert c.invested_after == pytest.approx(6.1)                     # 5.6 + 0.5, once
    assert c.ownership_after == pytest.approx(0.075)
    fl = _flags(c)
    assert "X-124" in fl and fl["X-124"].evidence["note_leg"] == pytest.approx(0.5)
    assert "X-107" not in fl and "X-108" not in fl                    # the bridge questions are settled
    assert "X-105" not in fl                                          # "conversion" is the rule's own business now
    assert not any(i.kind is OpenItemKind.CONVERTIBLE_NOTE for i in c.open_items)
    assert [s.rule_id for s in c.steps] == ["M-060", "M-010"]


def test_note_converting_on_listing_gets_the_same_finding(tmp_path: Path, cfg):
    pos = position(company="Duskfern", latest_post_money=100.0, ownership=0.061, invested=5.6, prior_mark=6.1)
    note = event(EventType.CONVERTIBLE_NOTE, date=date(2026, 8, 1), company="Duskfern", hc_investment=0.5, notes="Bridge note.")
    ipo = event(EventType.IPO, date=date(2026, 9, 1), company="Duskfern", detail="IPO", value=400.0, ownership_after=0.05,
                notes="Note converts at listing.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [note, ipo]), cfg)
    c = run.by_company()["Duskfern"]
    fl = _flags(c)
    assert "X-124" in fl and "X-107" not in fl and c.note_at_cost == 0.0 and c.invested_after == pytest.approx(6.1)


# ---------------------------------------------------------------- Gryphonel: escrow at closing

def test_closed_exit_with_escrow_realizes_cash_and_carries_the_claim(tmp_path: Path, cfg):
    pos = position(company="Gryphonel", latest_post_money=97.0, ownership=0.036, invested=2.0, prior_mark=3.5)
    announced = event(EventType.ACQ_ANNOUNCED, date=date(2026, 9, 8), company="Gryphonel", detail="Cash acquisition",
                      value=133.0, notes="Definitive agreement signed; expected to close in Q4.")
    closed = event(EventType.ACQ_CLOSED, date=date(2026, 9, 28), company="Gryphonel", detail="Cash acquisition with escrow",
                   value=133.0, ownership_after=0.0, proceeds=3.8,
                   notes="The $133M acquisition announced September 8 closed earlier than expected. HC's confirmed entitlement "
                         "is $4.8M: $3.8M received at closing and $1.0M held in escrow for 12 months, subject to "
                         "indemnification claims. No equity remains. Record $3.8M as realized proceeds and separately assess "
                         "the escrow claim's fair value using the payout agreement.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [announced, closed]), cfg)
    c = run.by_company()["Gryphonel"]
    assert c.status_after.value == "Acquired" and c.proposed_mark == 0.0
    assert c.realized_cumulative == pytest.approx(3.8)                # cash received, nothing more
    fl = _flags(c)
    x101 = fl["X-101"]
    assert x101.severity.value == "REVIEW" and x101.evidence["proceeds"] == 3.8
    gap = next(s for s in x101.suggestions if s.key == "carry_gap")
    assert gap.booked == pytest.approx(0.036 * 133.0 - 3.8)            # the claim, valued from implied entitlement
    assert "X-105" not in fl                                          # "escrow" is the gap finding's own business
    item = next(i for i in c.open_items if i.kind is OpenItemKind.UNCONFIRMED_EXIT)
    assert "escrow" in item.detail and item.amount_musd == pytest.approx(0.036 * 133.0 - 3.8)
    assert not any(i.kind is OpenItemKind.PENDING_ACQUISITION for i in c.open_items)
    assert c.readiness is Readiness.NEEDS_REVIEW or c.readiness is Readiness.BLOCKED


# ---------------------------------------------------------------- Halcyra: term sheet withdrawn

HALCYRA_NOTE = ("The approximately $50M post-money Series B term sheet signed September 17 was withdrawn. No financing "
                "closed, cash was received, or shares were issued. Management's September 29 update reports $1.3M available "
                "cash and $0.65M monthly burn, implying two months of runway; this supersedes the earlier cash balance. "
                "Escalate funding risk and reassess support for the existing mark.")


def test_term_sheet_withdrawn_closes_the_item_holds_the_mark_and_escalates(tmp_path: Path, cfg):
    pos = position(company="Halcyra", latest_post_money=42.5, ownership=0.10, invested=3.0, prior_mark=4.25,
                   cash=9.0, net_burn=0.6)
    signed = event(EventType.TERM_SHEET, date=date(2026, 9, 17), company="Halcyra", detail="Series B term sheet",
                   value=50.0, notes="Signed term sheet, non-binding.")
    withdrawn = event(EventType.TERM_SHEET_WITHDRAWN, date=date(2026, 9, 29), company="Halcyra",
                      detail="Proposed Series B financing cancelled", notes=HALCYRA_NOTE)
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [signed, withdrawn]), cfg)
    c = run.by_company()["Halcyra"]
    assert c.proposed_mark == pytest.approx(4.25) and c.readiness is not Readiness.BLOCKED
    assert [s.rule_id for s in c.steps] == ["M-070", "M-071"]
    assert not any(i.kind is OpenItemKind.TERM_SHEET for i in c.open_items)
    assert "term_sheet_indicated" not in c.alternative_marks
    fl = _flags(c)
    assert "M-999" not in fl and "X-109" not in fl
    assert fl["X-125"].severity.value == "REVIEW" and fl["X-125"].evidence["term_sheet_indicated"] == pytest.approx(5.0)   # HC's 10% of the $50M indication
    assert {s.key for s in fl["X-125"].suggestions} == {"as_proposed", "at_cost"}
    assert next(s for s in fl["X-125"].suggestions if s.key == "at_cost").booked == pytest.approx(3.0)
    x126 = fl["X-126"]
    assert x126.severity.value == "REVIEW" and {"cash", "burn", "runway"} <= set(x126.evidence["terms"])
    # the numbers in the note never reach the runway screen: the tab's 15 months still stand until a person updates it
    assert "X-304" not in fl and "X-303" not in fl
    assert "X-105" not in fl


def test_term_sheet_withdrawn_without_a_prior_term_sheet_still_reviews(tmp_path: Path, cfg):
    pos = position(company="Halcyra", latest_post_money=42.5, ownership=0.10, invested=3.0, prior_mark=4.25)
    withdrawn = event(EventType.TERM_SHEET_WITHDRAWN, date=date(2026, 9, 29), company="Halcyra",
                      detail="Series B financing cancelled", notes="Lead investor walked; terms not disclosed.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [withdrawn]), cfg)
    c = run.by_company()["Halcyra"]
    fl = _flags(c)
    assert c.proposed_mark == pytest.approx(4.25) and "X-125" in fl and "X-126" not in fl
    assert fl["X-125"].evidence["term_sheet_indicated"] is None


def test_operating_update_holds_the_mark_and_points_at_the_tab(tmp_path: Path, cfg):
    pos = position(company="Brumewell", latest_post_money=60.0, ownership=0.08, invested=2.0, prior_mark=4.8)
    upd = event(EventType.OPERATING_UPDATE, date=date(2026, 9, 10), company="Brumewell", detail="Q3 board update",
                notes="ARR reached $6.2M; net burn cut to $0.3M a month; cash $5.0M.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [upd]), cfg)
    c = run.by_company()["Brumewell"]
    fl = _flags(c)
    assert c.proposed_mark == pytest.approx(4.8) and [s.rule_id for s in c.steps] == ["M-072"]
    assert "X-126" in fl and {"arr", "burn", "cash"} <= set(fl["X-126"].evidence["terms"]) and "M-999" not in fl
    bare = event(EventType.OPERATING_UPDATE, date=date(2026, 9, 10), company="Brumewell", detail="Board update", notes="")
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [bare], name="b.xlsx"), cfg)
    fl2 = _flags(run2.by_company()["Brumewell"])
    assert "X-126" in fl2 and fl2["X-126"].evidence.get("terms") is None


def test_spellings_of_the_two_new_event_types_normalise(cfg):
    ncfg = cfg.normalization
    for raw in ("Term Sheet Withdrawn", "term sheet cancelled", "Financing withdrawn", "Term-sheet rescinded"):
        assert nz.normalize_event_type(raw, ncfg)[0] == EventType.TERM_SHEET_WITHDRAWN.value, raw
    for raw in ("Operating Update", "Management update", "KPI Update", "board update"):
        assert nz.normalize_event_type(raw, ncfg)[0] == EventType.OPERATING_UPDATE.value, raw
