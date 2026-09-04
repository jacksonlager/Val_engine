"""HTTP API: read routes serve the run; the override route writes the ledger and reruns."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from hc_valuation.api.app import create_app
from hc_valuation.config import repo_root
from hc_valuation.pipeline import RunPaths


@pytest.fixture()
def paths(tmp_path: Path) -> RunPaths:
    """A RunPaths whose ledgers live in a scratch copy of data/ so tests never dirty the repo."""
    root = repo_root()
    data = tmp_path / "data"
    shutil.copytree(root / "data", data, ignore=shutil.ignore_patterns("sample_run.json"))
    return RunPaths(
        root=root, policy=root / "rules" / "2026Q3.yaml", workbook=data / "HC_Mock_Portfolio_Data.xlsx",
        overrides=data / "overrides.yaml", proposals_dir=data / "proposals", precedent=data / "precedent.yaml",
        open_items_carry=data / "open_items_carry.yaml",
    )


@pytest.fixture()
def client(paths: RunPaths, tmp_path: Path) -> TestClient:
    return TestClient(create_app(paths, static_dir=tmp_path / "no-static"))


def test_health_and_run_totals(client: TestClient):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["quarter"] == "Q3 2026"
    run = client.get("/api/run").json()
    assert run["totals"]["positions"] == 100
    assert run["totals"]["prior_nav"] == pytest.approx(1139.3, abs=0.05)
    assert run["totals"]["proposed_nav"] == pytest.approx(1183.9, abs=0.05)
    assert run["totals"]["realized_quarter"] == pytest.approx(32.5, abs=0.05)
    assert run["totals"]["level1_positions"] == 1
    assert len(run["companies"]) == 100


def test_company_route(client: TestClient):
    c = client.get("/api/companies/Drayvenn").json()
    assert c["fv_level"] == 1 and c["disposition"] == "BLOCK"
    assert c["steps"][-1]["new_value"] == pytest.approx(c["proposed_mark"])
    assert client.get("/api/companies/Nobody").status_code == 404


def test_rules_and_proposals(client: TestClient):
    rules = client.get("/api/rules").json()
    ids = {r["id"] for r in rules}
    assert {"M-010", "M-040", "M-999"} <= ids
    m010 = next(r for r in rules if r["id"] == "M-010")
    assert set(m010) >= {"id", "version", "applies_to", "severity", "effective_from", "description", "source"}
    assert isinstance(client.get("/api/proposals").json(), list)


def test_override_changes_booked_not_proposed(client: TestClient, paths: RunPaths):
    before = client.get("/api/companies/Oakenvale").json()
    body = {"company": "Oakenvale", "booked": 2.0, "reason": "preference stack reviewed; haircut to 2.0",
            "approver": "committee-test"}
    r = client.post("/api/overrides", json=body)
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["proposed_mark"] == pytest.approx(before["proposed_mark"])
    assert after["booked_mark"] == pytest.approx(2.0)
    assert after["override"]["approver"] == "committee-test"
    assert after["steps"][-1]["rule_id"] == "E-01"
    # persisted to the scratch ledger, and visible on the next read
    ledger = yaml.safe_load(paths.overrides.read_text())
    assert ledger["overrides"][-1]["company"] == "Oakenvale"
    assert client.get("/api/companies/Oakenvale").json()["booked_mark"] == pytest.approx(2.0)
    run = client.get("/api/run").json()
    assert run["totals"]["booked_nav"] == pytest.approx(run["totals"]["proposed_nav"] - (before["proposed_mark"] - 2.0), abs=1e-6)
    assert client.post("/api/overrides", json={**body, "company": "Nobody"}).status_code == 404


def test_root_serves_fallback_report_without_bundle(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200 and "window.__HC_RUN__" in r.text


def test_root_serves_bundle_when_present(paths: RunPaths, tmp_path: Path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>dashboard</body></html>")
    c = TestClient(create_app(paths, static_dir=static))
    assert c.get("/").text == "<html><body>dashboard</body></html>"
    assert c.get("/api/health").status_code == 200


def test_decision_route_is_501_until_promote_exists(client: TestClient):
    try:
        from hc_valuation.adjudication import promote  # noqa: F401
    except ImportError:
        promote = None
    r = client.post("/api/proposals/nope/decision", json={"decision": "reject", "approver": "x", "reason": "test"})
    if promote is None or not hasattr(promote, "record_decision"):
        assert r.status_code == 501 and "adjudication" in r.text
    else:
        assert r.status_code == 404 and "nope" in r.text   # unknown proposal id, named by the adjudication module


def test_rerun(client: TestClient):
    r = client.post("/api/rerun")
    assert r.status_code == 200 and r.json()["booked_nav"] == pytest.approx(1183.9, abs=0.05)
