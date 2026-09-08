"""The market data's date and the Refresh button behind it.

`/api/health` says where the comps came from and when they were fetched; `POST /api/market/refresh`
refetches the live feed over its cache and reruns the book, and refuses (400) for a workbook priced
from the fixture or from synthetic data, which have nothing to refresh. On start the dashboard
refetches once a day on its own when the cache was fetched before today; that decision is a pure
function of the cache's meta file and the date, pinned here.
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hc_valuation.api.app import create_app, market_cache_is_stale_today
from hc_valuation.config import repo_root
from hc_valuation.connectors.cache import MarketCache
from hc_valuation.pipeline import RunPaths

ROOT = repo_root()
REAL = ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx"


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "rules", tmp_path / "rules")
    (tmp_path / "data").mkdir()
    shutil.copytree(ROOT / "data" / "mock_responses", tmp_path / "data" / "mock_responses")
    (tmp_path / "data" / "overrides.yaml").write_text("overrides: []\n")
    return tmp_path


def test_health_carries_the_market_status_and_the_fixture_is_not_refreshable(root: Path, tmp_path: Path):
    paths = RunPaths.default(root=root, workbook=REAL, policy=root / "rules" / "2026Q3.yaml", ledger_dir=root / "ledger")
    client = TestClient(create_app(paths, provider="stub", static_dir=tmp_path / "no-static", auto_refresh_market=False))
    h = client.get("/api/health").json()
    assert h["market"]["source"] == "stub" and h["market"]["refreshable"] is False and h["market"]["fetched_at"] is None
    r = client.post("/api/market/refresh")
    assert r.status_code == 400 and "nothing to refresh" in r.json()["detail"]["message"]
    assert client.get("/api/health").json()["run_id"] == h["run_id"]          # nothing reran


def test_empty_app_has_nothing_to_refresh(root: Path, tmp_path: Path):
    client = TestClient(create_app(None, provider="stub", static_dir=tmp_path / "no-static", start_empty=True, root=root, auto_refresh_market=False))
    assert client.get("/api/health").json()["market"]["source"] is None
    assert client.post("/api/market/refresh").status_code == 404


def test_the_cache_is_stale_when_it_was_fetched_before_today(root: Path):
    policy = root / "rules" / "2026Q3.yaml"
    assert market_cache_is_stale_today(root, policy, today=date(2026, 9, 7))          # no cache at all
    cache = MarketCache(root, date(2026, 9, 30))
    cache.dir.mkdir(parents=True, exist_ok=True)
    (cache.dir / "meta.json").write_text(json.dumps({"fetched_at": "2026-09-07T14:02:11Z", "as_of": "2026-09-30"}))
    assert not market_cache_is_stale_today(root, policy, today=date(2026, 9, 7))      # fetched today
    assert market_cache_is_stale_today(root, policy, today=date(2026, 9, 8))          # yesterday's fetch
    (cache.dir / "meta.json").write_text("not json")
    assert market_cache_is_stale_today(root, policy, today=date(2026, 9, 7))          # unreadable: refetch
