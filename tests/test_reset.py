"""Reset: back to "nothing uploaded yet" — the uploads, the decisions and the published snapshots go;
the market cache, the fixtures, the policies and the repository's own workbook stay.

POST /api/reset needs the word RESET; `hc-valuation reset` needs --yes. After a reset the app is
empty (health `empty`, /api/run 404) and an upload works again.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hc_valuation.api.app import create_app
from hc_valuation.cli import app as cli_app
from hc_valuation.config import repo_root
from hc_valuation.pipeline import RunPaths
from hc_valuation.reset import EMPTY_LEDGER, reset_workspace

ROOT = repo_root()
REAL = ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx"


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "rules", tmp_path / "rules")
    for p in (tmp_path / "rules").glob("*.yaml"):
        if p.name not in ("2026Q3.yaml", "comps_baskets.yaml", "rationale.yaml"):
            p.unlink()
    (tmp_path / "data").mkdir()
    shutil.copytree(ROOT / "data" / "mock_responses", tmp_path / "data" / "mock_responses")
    shutil.copy(REAL, tmp_path / "data" / REAL.name)
    (tmp_path / "data" / "market_cache" / "2026-09-30").mkdir(parents=True)
    (tmp_path / "data" / "market_cache" / "2026-09-30" / "meta.json").write_text("{}")
    (tmp_path / "data" / "quarters" / "synthetic").mkdir(parents=True)
    (tmp_path / "data" / "quarters" / "synthetic" / "keep.txt").write_text("chain")
    (tmp_path / "data" / "overrides.yaml").write_text("overrides: []\n")
    return tmp_path


def _wait(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/upload/{job_id}").json()
        if job["done"]:
            return job
        time.sleep(0.1)
    raise AssertionError("upload did not finish")


def _upload(client: TestClient) -> dict:
    r = client.post("/api/upload", files={"file": ("HC_Mock_Portfolio_Data.xlsx", REAL.read_bytes())})
    assert r.status_code == 200, r.text
    job = _wait(client, r.json()["id"])
    assert job["error"] is None, job
    return job


def _decide_and_publish(client: TestClient) -> None:
    for item in client.get("/api/publish/readiness").json()["outstanding"]:
        r = client.post("/api/overrides", json={"company": item["company"], "booked": item["proposed_mark"], "reason": "walkthrough",
                                                "approver": "Reviewer A", "rule_ids_addressed": [x["rule_id"] for x in item["rules"]]})
        assert r.status_code == 200, r.text
    assert client.post("/api/publish", json={"approver": "Tom Moore", "note": "close"}).status_code == 200


def test_reset_needs_the_word(root: Path, tmp_path: Path):
    client = TestClient(create_app(None, provider="stub", static_dir=tmp_path / "no-static", start_empty=True, root=root))
    _upload(client)
    assert client.post("/api/reset", json={}).status_code == 400
    assert client.post("/api/reset", json={"confirm": "reset"}).status_code == 400
    assert client.get("/api/health").json()["status"] == "ok"          # nothing happened


def test_reset_removes_the_work_and_keeps_the_inputs(root: Path, tmp_path: Path):
    client = TestClient(create_app(None, provider="stub", static_dir=tmp_path / "no-static", start_empty=True, root=root))
    _upload(client)
    _decide_and_publish(client)
    assert (root / "data" / "uploads" / "2026Q3" / "HC_Mock_Portfolio_Data.xlsx").exists()
    assert (root / "data" / "uploads" / "2026Q3" / "Q4 2026 HC Mock Portfolio Data.xlsx").exists()   # the close emitted next quarter
    assert (root / "data" / "published" / "2026Q3.json").exists()
    assert yaml.safe_load((root / "data" / "overrides.yaml").read_text())["overrides"]

    r = client.post("/api/reset", json={"confirm": "RESET"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "empty" and out["files"] >= 3
    assert "data/uploads/" in out["removed"] and "data/published/" in out["removed"] and "data/overrides.yaml (decisions cleared)" in out["removed"]
    # removed
    assert not (root / "data" / "uploads").exists() and not (root / "data" / "published").exists()
    assert (root / "data" / "overrides.yaml").read_text() == EMPTY_LEDGER
    # kept
    assert (root / "data" / REAL.name).exists()
    assert (root / "data" / "market_cache" / "2026-09-30" / "meta.json").exists()
    assert (root / "data" / "mock_responses").is_dir() and (root / "rules" / "2026Q3.yaml").exists()
    assert (root / "data" / "quarters" / "synthetic" / "keep.txt").exists()
    # empty
    h = client.get("/api/health").json()
    assert h["status"] == "empty" and h["run_id"] is None
    assert client.get("/api/run").status_code == 404
    assert client.get("/api/published").json() == []
    assert client.get("/api/workbooks").json() == {"current": None, "workbooks": []}
    # ... and an upload works again, undecided and unpublished
    job = _upload(client)
    assert job["result"]["quarter"] == "Q3 2026"
    assert client.get("/api/publish/readiness").json()["ready"] is False
    assert client.get("/api/published").json() == []


def test_reset_workspace_respects_a_moved_ledger(root: Path):
    paths = RunPaths.default(root=root, ledger_dir=root / "chain")
    (root / "chain").mkdir()
    (root / "chain" / "overrides.yaml").write_text(yaml.safe_dump({"overrides": [{"company": "X", "quarter": "Q3 2026", "proposed": 1, "booked": 2,
                                                                                    "reason": "r", "approver": "a", "created_at": "2026-10-01"}]}))
    (root / "chain" / "published").mkdir()
    (root / "chain" / "published" / "latest.json").write_text("{}")
    (root / "data" / "overrides.yaml").write_text("overrides: [{company: Real}]\n")
    out = reset_workspace(paths)
    assert out["ledger"] == "chain/overrides.yaml"
    assert (root / "chain" / "overrides.yaml").read_text() == EMPTY_LEDGER and not (root / "chain" / "published").exists()
    assert (root / "data" / "overrides.yaml").read_text() == "overrides: [{company: Real}]\n"    # not this run's ledger: untouched


def test_cli_reset_refuses_without_yes(root: Path, monkeypatch):
    import hc_valuation.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "repo_root", lambda: root)
    monkeypatch.delenv("HC_LEDGER_DIR", raising=False)
    (root / "data" / "uploads" / "2026Q3").mkdir(parents=True)
    (root / "data" / "uploads" / "2026Q3" / "book.xlsx").write_bytes(b"x")
    r = CliRunner().invoke(cli_app, ["reset"])
    assert r.exit_code == 2 and "refused" in r.output and "--yes" in r.output
    assert (root / "data" / "uploads" / "2026Q3" / "book.xlsx").exists()
    r = CliRunner().invoke(cli_app, ["reset", "--yes"])
    assert r.exit_code == 0, r.output
    assert "removed data/uploads/" in r.output and not (root / "data" / "uploads").exists()
    assert (root / "data" / "overrides.yaml").read_text() == EMPTY_LEDGER and (root / "data" / REAL.name).exists()
