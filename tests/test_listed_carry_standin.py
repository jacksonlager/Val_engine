"""A listed position carried on a stand-in quote must block *with a finding a decision can name*.

Found by the synthetic chain (HARDENING_REPORT.md, D-3): in the quarter after Drayvenn's IPO the
listed carry (M-041) ran on the fixture's seeded quote, the mark was provisional and the position
Blocked — with no flag at all. The provisional rule fell back to "M-041", which is not a flag, and the
API refuses an override naming a rule id that is not on the position, so nothing a reviewer could do
from the dashboard would ever clear it. M-041 now raises X-113 whenever the quote is a stand-in.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hc_valuation.api.app import create_app
from hc_valuation.config import repo_root
from hc_valuation.engine.models import MarketData, MarketQuote, OverrideLedger, OverrideRecord, Readiness
from hc_valuation.engine.marking import is_standin_price
from hc_valuation.pipeline import RunPaths
from tests.conftest import make_workbook, position, run_workbook

ROOT = repo_root()
MD = date(2026, 9, 30)


def _listed(**kw):
    return position(company="Listed Co", stage="Public", latest_round=date(2026, 6, 20), latest_post_money=3931.0,
                    ownership=0.028, prior_mark=110.068, invested=20.0, arr=148.9, arr_growth=0.43, **kw)


def test_standin_sources_are_recognised():
    assert is_standin_price("stub:carried_listing") and is_standin_price("ipo_print") and is_standin_price("Nasdaq seeded")
    assert not is_standin_price("Nasdaq close via Bloomberg") and not is_standin_price(None)


def test_listed_carry_on_a_seeded_quote_raises_x113_and_blocks(tmp_path: Path, cfg):
    quote = MarketQuote(company="Listed Co", market_cap_musd=3931.0, as_of=MD, source="stub:carried_listing", note="seeded")
    run, _ = run_workbook(make_workbook(tmp_path, [_listed()], []), cfg, market=MarketData(quotes={"Listed Co": quote}, as_of=MD))
    c = run.by_company()["Listed Co"]
    assert c.listed and c.provisional and c.readiness is Readiness.BLOCKED
    x113 = [f for f in c.flags if f.rule_id == "X-113"]
    assert x113 and x113[0].severity.value == "BLOCK" and x113[0].evidence["price_source"] == "stub:carried_listing"
    assert c.proposed_mark == pytest.approx(0.028 * 3931.0)          # the stand-in is used so the arithmetic is visible
    assert [s.rule_id for s in c.steps] == ["M-041"]


def test_a_real_quote_raises_nothing(tmp_path: Path, cfg):
    quote = MarketQuote(company="Listed Co", market_cap_musd=4100.0, as_of=MD, source="Nasdaq close via Bloomberg")
    run, _ = run_workbook(make_workbook(tmp_path, [_listed()], []), cfg, market=MarketData(quotes={"Listed Co": quote}, as_of=MD))
    c = run.by_company()["Listed Co"]
    assert not c.provisional and c.readiness is Readiness.READY and not [f for f in c.flags if f.rule_id == "X-113"]


def test_a_decision_naming_x113_with_the_close_clears_the_block(tmp_path: Path, cfg):
    quote = MarketQuote(company="Listed Co", market_cap_musd=3931.0, as_of=MD, source="stub:carried_listing")
    ledger = OverrideLedger(records=(OverrideRecord(
        company="Listed Co", quarter="Q3 2026", proposed=round(0.028 * 3931.0, 6), booked=round(0.028 * 4100.0, 6),
        reason="Quarter-end market cap supplied", approver="Reviewer", created_at=date(2026, 10, 2),
        rule_ids_addressed=("X-113",), source_suggestion="X-113/price",
        evidence={"kind": "closing_price", "as_of": "2026-09-30", "market_cap_musd": 4100.0, "source": "Nasdaq"}),))
    run, _ = run_workbook(make_workbook(tmp_path, [_listed()], []), cfg, market=MarketData(quotes={"Listed Co": quote}, as_of=MD),
                          overrides=ledger)
    c = run.by_company()["Listed Co"]
    assert c.readiness is Readiness.READY and c.booked_mark == pytest.approx(0.028 * 4100.0)
    # ... and a decision that names some other rule does not: the stand-in was not knowingly accepted
    other = OverrideLedger(records=(ledger.records[0].model_copy(update={"rule_ids_addressed": ("X-401",)}),))
    run2, _ = run_workbook(make_workbook(tmp_path, [_listed()], [], name="b.xlsx"), cfg,
                           market=MarketData(quotes={"Listed Co": quote}, as_of=MD), overrides=other)
    assert run2.by_company()["Listed Co"].readiness is Readiness.BLOCKED


def test_the_dashboard_route_can_clear_it(tmp_path: Path, cfg):
    """End to end through the API: the fixture quote feed seeds the listing to its prior close, X-113
    is on the position, and POST /api/overrides naming it with closing-price evidence makes it Ready."""
    wb = make_workbook(tmp_path, [_listed()], [])
    paths = RunPaths.default(root=ROOT, workbook=wb, policy=ROOT / "rules" / "2026Q3.yaml", ledger_dir=tmp_path / "ledger")
    client = TestClient(create_app(paths, provider="stub", static_dir=tmp_path / "no-static"))
    c = client.get("/api/companies/Listed%20Co").json()
    assert c["readiness"] == "Blocked" and c["provisional"] and any(f["rule_id"] == "X-113" for f in c["flags"])
    r = client.post("/api/overrides", json={
        "company": "Listed Co", "booked": round(0.028 * 4100.0, 6), "reason": "30 Sep close supplied", "approver": "Reviewer",
        "rule_ids_addressed": ["X-113"], "source_suggestion": "X-113/price",
        "evidence": {"kind": "closing_price", "as_of": "2026-09-30", "market_cap_musd": 4100.0, "source": "Nasdaq"}})
    assert r.status_code == 200, r.text
    assert r.json()["readiness"] == "Ready"
    assert client.get("/api/publish/readiness").json()["ready"]
