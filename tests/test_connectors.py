"""Phase 07 — connectors. The stub feeds the engine vendor-shaped data without changing a
disposition; the live path degrades to the stub; comps only bite when the policy says so."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from hc_valuation.config import load_config, repo_root
from hc_valuation.connectors import resolve_provider
from hc_valuation.connectors.base import CompanyMetricsProvider, CompsProvider, MarketDataProvider, NewsSignalProvider
from hc_valuation.connectors.live import BASKET, LiveFeedError, StooqCompsProvider, ev_to_revenue, month_end_closes
from hc_valuation.connectors.stubs import (
    StubCompanyMetricsProvider, StubCompsProvider, StubIndexProvider, StubMarketDataProvider, StubNewsSignalProvider,
)
from hc_valuation.engine.inputs import EventType
from hc_valuation.pipeline import RunPaths, execute

ROOT = repo_root()
FIXTURES = ROOT / "data" / "mock_responses"
BASELINE = {"BLOCK": 7, "REVIEW": 15, "MONITOR": 44, "CLEAR": 34}


@pytest.fixture(scope="module")
def baseline():
    return execute(adjudicate=False)


def _policy_copy(tmp_path: Path, mutate) -> RunPaths:
    """A temp RunPaths whose policy is a mutated copy of the repo policy; data stays the repo's."""
    rules = tmp_path / "rules"
    rules.mkdir()
    raw = yaml.safe_load((ROOT / "rules" / "2026Q3.yaml").read_text())
    mutate(raw)
    p = rules / "2026Q3.yaml"
    p.write_text(yaml.safe_dump(raw, sort_keys=False))
    paths = RunPaths.default(ROOT)
    paths.policy = p
    paths.proposals_dir = tmp_path / "proposals"
    paths.precedent = tmp_path / "precedent.yaml"
    paths.overrides = tmp_path / "overrides.yaml"
    return paths


# ---------------------------------------------------------------- fixtures are vendor-shaped

@pytest.mark.parametrize("rel", ["pitchbook/comps_software.json", "sp_capiq/index_multiples.json",
                                 "foresight/company_metrics.json", "alphasense/news_signals.json"])
def test_fixtures_carry_envelopes_and_synthetic_note(rel):
    d = json.loads((FIXTURES / rel).read_text())
    assert d["_note"].startswith("synthetic")
    assert "requestId" in d and "asOfDate" in d and "pagination" in d
    assert "currency" in d or "query" in d


def test_pitchbook_history_covers_every_sector_and_month():
    comps = StubCompsProvider(ROOT)
    workbook_sectors = {"AI/ML", "Fintech", "Developer Tools", "Climate & Energy", "Cybersecurity", "Infrastructure",
                        "Enterprise SaaS", "Space & Defense", "Healthcare", "Data & Analytics", "Robotics", "Consumer"}
    assert workbook_sectors <= set(comps.sectors)
    for s in workbook_sectors:
        h = comps.history(s)
        assert h["2019-01"] > 0 and h["2026-09"] > 0 and len(h) == 93
        assert all(re.match(r"^\d{4}-\d{2}$", k) for k in h)
        # peak late 2021, trough late 2022, recovering since
        assert h["2021-11"] > h["2019-01"] and h["2021-11"] > h["2026-09"]
        assert h["2022-12"] < h["2021-11"] * 0.5 and h["2026-09"] > h["2022-12"]


def test_stubs_satisfy_protocols(baseline):
    feed_quotes = StubMarketDataProvider(feed=_feed())
    assert isinstance(feed_quotes, MarketDataProvider)
    assert isinstance(StubCompsProvider(ROOT), CompsProvider)
    assert isinstance(StubCompanyMetricsProvider(ROOT), CompanyMetricsProvider)
    assert isinstance(StubNewsSignalProvider(ROOT), NewsSignalProvider)


def _feed():
    from hc_valuation.ingest.reader import read_workbook
    cfg = load_config(ROOT / "rules" / "2026Q3.yaml")
    _, feed = read_workbook(ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx", cfg)
    return feed


def test_ipo_quote_is_seeded_to_print_and_says_so():
    feed = _feed()
    ipo = next(e for e in feed.events if e.event_type == EventType.IPO.value)
    q = StubMarketDataProvider(feed).quote(ipo.company, date(2026, 9, 30))
    assert q is not None and q.market_cap_musd == pytest.approx(ipo.value)
    assert q.source == "stub:seeded_to_ipo_print" and "no live feed" in q.note.lower()
    assert StubMarketDataProvider(feed).quote("Nobody Inc", date(2026, 9, 30)) is None
    drifted = StubMarketDataProvider(feed, drift_pct=0.10).quote(ipo.company, date(2026, 9, 30))
    assert drifted.market_cap_musd == pytest.approx(ipo.value * 1.10) and "drift" in drifted.source


def test_metrics_and_news_stubs_read_fixtures():
    m = StubCompanyMetricsProvider(ROOT).metrics("Gryphonel")
    assert m and m["metrics"]["arr"] > 0 and m["confidence"]
    news = StubNewsSignalProvider(ROOT).signals("Gryphonel", since=date(2026, 7, 1))
    assert len(news) == 2 and any("regulator" in n["title"].lower() for n in news)
    assert StubNewsSignalProvider(ROOT).signals("Gryphonel", since=date(2026, 9, 1)) == news[1:]


# ---------------------------------------------------------------- assembler + gate

def test_gate_dispositions_unchanged_with_stub_comps(baseline):
    run = baseline.run
    assert run.totals.dispositions == BASELINE
    assert run.manifest.market_data_source == "stub"
    assert set(baseline.market.comps) >= {"AI/ML", "Fintech", "Consumer"}
    assert baseline.market.comp_history["AI/ML"]["2026-09"] == baseline.market.comps["AI/ML"].ev_to_arr
    assert baseline.market.as_of == date(2026, 9, 30)
    assert "Drayvenn" in baseline.market.quotes and baseline.market.quotes["Drayvenn"].source.startswith("stub:")


def test_provider_resolution(monkeypatch):
    monkeypatch.delenv("HC_MARKET_PROVIDER", raising=False)
    assert resolve_provider(None) == "stub"
    monkeypatch.setenv("HC_MARKET_PROVIDER", "stooq")
    assert resolve_provider(None) == "live"
    assert resolve_provider("stub") == "stub"
    assert resolve_provider("bloomberg") == "stub"


def test_relative_to_comps_changes_valuation_flags(tmp_path, baseline):
    def mutate(raw):
        raw["exceptions"]["multiple"]["mode"] = "relative_to_comps"
    paths = _policy_copy(tmp_path, mutate)
    rel = execute(paths, adjudicate=False)
    base_flags = {(c.company, f.rule_id) for c in baseline.run.companies for f in c.flags if f.rule_id in ("X-401", "X-402")}
    rel_flags = {(c.company, f.rule_id) for c in rel.run.companies for f in c.flags if f.rule_id in ("X-401", "X-402")}
    assert rel_flags != base_flags
    assert any("sector comp" in f.message for c in rel.run.companies for f in c.flags if f.rule_id in ("X-401", "X-402"))
    # comps are a screen, never a mark
    assert [c.proposed_mark for c in rel.run.companies] == [c.proposed_mark for c in baseline.run.companies]


def test_calibration_writes_alternative_only(tmp_path, baseline):
    def mutate(raw):
        raw["marking"]["calibration"]["enabled"] = True
    paths = _policy_copy(tmp_path, mutate)
    cal = execute(paths, adjudicate=False)
    calibrated = [c for c in cal.run.companies if "calibrated_to_comps" in c.alternative_marks]
    assert len(calibrated) >= 20
    for c in calibrated:
        assert c.arr is not None and not c.listed
        assert any(s.rule_id == "M-080" for s in c.steps)
    base_by = baseline.run.by_company()
    for c in cal.run.companies:
        assert c.proposed_mark == base_by[c.company].proposed_mark
    assert cal.run.totals.dispositions == BASELINE


def test_temp_root_without_fixtures_still_gets_comps(tmp_path):
    """A tmp root (tests) falls back to the repo fixtures rather than silently returning no comps."""
    paths = RunPaths.default(ROOT)
    paths.root = tmp_path
    r = execute(paths, adjudicate=False)
    assert r.market.comps and r.run.totals.dispositions == BASELINE


# ---------------------------------------------------------------- live path

def test_live_helpers():
    closes = {"2026-08-03": 100.0, "2026-08-28": 110.0, "2026-09-01": 120.0}
    assert month_end_closes(closes) == {"2026-08": 110.0, "2026-09": 120.0}
    sym = next(iter(BASKET))
    shares, net_cash, revenue = BASKET[sym]
    assert ev_to_revenue(10.0, sym) == pytest.approx((10.0 * shares - net_cash) / revenue)


def test_live_falls_back_to_stub_on_network_failure(monkeypatch, caplog):
    import hc_valuation.connectors.live as live

    def boom(symbol, timeout_s=5.0):
        raise LiveFeedError(f"{symbol}: simulated outage")
    monkeypatch.setattr(live, "fetch_daily_closes", boom)
    stub = StubCompsProvider(ROOT)
    with caplog.at_level("WARNING"):
        p = StooqCompsProvider(stub, StubIndexProvider(ROOT))
    assert not p.reached_live and p.source == stub.source and "falling back" in caplog.text
    assert p.sector_multiples(date(2026, 9, 30)) == stub.sector_multiples(date(2026, 9, 30))

    r = execute(adjudicate=False, provider="live")
    assert r.run.manifest.market_data_source == "stub"
    assert r.run.totals.dispositions == BASELINE


def test_live_rebases_sector_spreads_when_reached(monkeypatch):
    import hc_valuation.connectors.live as live

    def fake(symbol, timeout_s=5.0):
        shares, net_cash, revenue = BASKET[symbol]
        # price each name so its EV/Revenue is exactly 12x in every month -> index 12x
        px = (12.0 * revenue + net_cash) / shares
        return {"2026-08-31": px, "2026-09-15": px}
    monkeypatch.setattr(live, "fetch_daily_closes", fake)
    stub, index = StubCompsProvider(ROOT), StubIndexProvider(ROOT)
    p = StooqCompsProvider(stub, index)
    assert p.reached_live and p.source == "live:stooq" and p.live_index["2026-09"] == pytest.approx(12.0)
    ref = index.series["2026-09"]
    assert p.history("AI/ML")["2026-09"] == pytest.approx(stub.history("AI/ML")["2026-09"] * 12.0 / ref, rel=1e-3)
    assert p.history("AI/ML")["2019-01"] == stub.history("AI/ML")["2019-01"]     # untouched where no live data
    comps = p.sector_multiples(date(2026, 9, 30))
    assert comps["AI/ML"].source.startswith("live:stooq@")


def test_real_stooq_either_reaches_or_falls_back_cleanly():
    """Whatever the sandbox's egress, the live provider must construct and answer."""
    stub = StubCompsProvider(ROOT)
    p = StooqCompsProvider(stub, StubIndexProvider(ROOT), timeout_s=5.0)
    assert p.source in ("live:stooq", stub.source)
    assert set(p.sector_multiples(date(2026, 9, 30))) == set(stub.sectors)
