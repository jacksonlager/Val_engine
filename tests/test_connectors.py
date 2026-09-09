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
from hc_valuation.connectors import fetch as fetch_mod
from hc_valuation.connectors.fetch import FetchError
from hc_valuation.connectors.live import PublicCompsProvider, month_end_closes
from hc_valuation.connectors.stubs import (
    StubCompanyMetricsProvider, StubCompsProvider, StubMarketDataProvider, StubNewsSignalProvider,
)
from hc_valuation.engine.inputs import EventType
from hc_valuation.pipeline import RunPaths, execute

ROOT = repo_root()
FIXTURES = ROOT / "data" / "mock_responses"
BASELINE = {"BLOCK": 7, "REVIEW": 20, "MONITOR": 39, "CLEAR": 34}


@pytest.fixture(scope="module")
def baseline():
    return execute()


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
    paths.precedent = tmp_path / "precedent.yaml"
    paths.overrides = tmp_path / "overrides.yaml"
    return paths


# ---------------------------------------------------------------- fixtures are vendor-shaped

@pytest.mark.parametrize("rel", ["pitchbook/comps_software.json",
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
    """Policy 0.2 is relative_to_comps but gated to a live history, so on the fixture the screens are the
    absolute bounds (the baseline). Waiving the gate lets the fixture's sector multiples set the bounds."""
    gated = execute(RunPaths.default(ROOT))
    assert {(c.company, f.rule_id) for c in gated.run.companies for f in c.flags if f.rule_id in ("X-401", "X-402")} == \
        {(c.company, f.rule_id) for c in baseline.run.companies for f in c.flags if f.rule_id in ("X-401", "X-402")}

    def mutate(raw):
        raw["exceptions"]["multiple"]["require_live_comps"] = False
    paths = _policy_copy(tmp_path, mutate)
    rel = execute(paths)
    base_flags = {(c.company, f.rule_id) for c in baseline.run.companies for f in c.flags if f.rule_id in ("X-401", "X-402")}
    rel_flags = {(c.company, f.rule_id) for c in rel.run.companies for f in c.flags if f.rule_id in ("X-401", "X-402")}
    assert rel_flags != base_flags
    assert any("sector median" in f.message for c in rel.run.companies for f in c.flags if f.rule_id in ("X-401", "X-402"))
    # comps are a screen, never a mark
    assert [c.proposed_mark for c in rel.run.companies] == [c.proposed_mark for c in baseline.run.companies]


def test_calibration_writes_alternative_only(tmp_path, baseline):
    """On the fixture comps the gate holds (no alternatives); waived, the fixture history calibrates
    alternatives only — proposals and dispositions are untouched either way."""
    gated = execute(RunPaths.default(ROOT))
    assert not any("calibrated_to_comps" in c.alternative_marks for c in gated.run.companies)

    def mutate(raw):
        raw["marking"]["calibration"]["require_live_history"] = False
    paths = _policy_copy(tmp_path, mutate)
    cal = execute(paths)
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
    r = execute(paths)
    assert r.market.comps and r.run.totals.dispositions == BASELINE


# ---------------------------------------------------------------- live path (the detail is in test_market_feed.py)

def test_live_helpers():
    closes = {"2026-08-03": 100.0, "2026-08-28": 110.0, "2026-09-01": 120.0}
    assert month_end_closes(closes) == {"2026-08": 110.0, "2026-09": 120.0}
    assert month_end_closes(closes, date(2026, 8, 31)) == {"2026-08": 110.0}


def test_live_falls_back_to_stub_on_network_failure(monkeypatch, caplog, tmp_path):
    def boom(url, headers=None, timeout_s=8.0):
        raise FetchError("simulated outage")
    monkeypatch.setattr(fetch_mod, "fetch_text", boom)
    paths = RunPaths.default(ROOT)
    paths.root = tmp_path                     # an empty cache: every fetch is attempted and fails
    with caplog.at_level("WARNING"):
        r = execute(paths, provider="live")
    assert r.run.manifest.market_data_source == "stub" and "falling back" in caplog.text
    assert r.run.totals.dispositions == BASELINE
    assert not r.market_report["reached_live"] and r.market_report["errors"]
    assert isinstance(PublicCompsProvider, type)
