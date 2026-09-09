"""HTTP API: read routes serve the run; the override route writes the ledger and reruns."""
from __future__ import annotations

import shutil
import time
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
    shutil.copytree(root / "data", data, ignore=shutil.ignore_patterns("sample_run.json", "overrides.yaml", "published", "open_items_carry.yaml", "Q? ???? *.xlsx"))
    (data / "overrides.yaml").write_text("overrides: []\n")
    return RunPaths(
        root=root, policy=root / "rules" / "2026Q3.yaml", workbook=data / "HC_Mock_Portfolio_Data.xlsx",
        overrides=data / "overrides.yaml", precedent=data / "precedent.yaml",
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
    assert run["totals"]["proposed_nav"] == pytest.approx(1184.3, abs=0.05)
    assert run["totals"]["realized_quarter"] == pytest.approx(32.5, abs=0.05)
    assert run["totals"]["level1_positions"] == 1
    assert len(run["companies"]) == 100


def test_company_route(client: TestClient):
    c = client.get("/api/companies/Drayvenn").json()
    assert c["fv_level"] == 1 and c["disposition"] == "BLOCK"
    assert c["steps"][-1]["new_value"] == pytest.approx(c["proposed_mark"])
    assert client.get("/api/companies/Nobody").status_code == 404


def test_rules(client: TestClient):
    rules = client.get("/api/rules").json()
    ids = {r["id"] for r in rules}
    assert {"M-010", "M-040", "M-999"} <= ids
    m010 = next(r for r in rules if r["id"] == "M-010")
    assert set(m010) >= {"id", "version", "applies_to", "severity", "effective_from", "description", "source"}


def test_override_changes_booked_not_proposed(client: TestClient, paths: RunPaths):
    before = client.get("/api/companies/Oakenvale").json()
    body = {"company": "Oakenvale", "booked": 2.0, "reason": "preference stack reviewed; haircut to 2.0",
            "approver": "committee-test"}
    # a decision names what it decides: an override on a flagged position must list the rule ids
    r = client.post("/api/overrides", json=body)
    assert r.status_code == 422 and "rule_ids_addressed" in r.json()["detail"]["message"], r.text
    assert set(r.json()["detail"]["flags"]) == {f["rule_id"] for f in before["flags"]}
    r = client.post("/api/overrides", json={**body, "rule_ids_addressed": ["X-999"]})
    assert r.status_code == 422 and "X-999" in r.json()["detail"]["message"], r.text
    body["rule_ids_addressed"] = [before["flags"][0]["rule_id"]]
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


def test_the_proposal_routes_are_gone(client: TestClient):
    """Drafting a treatment for an unrecognised event was removed: an event no rule covers blocks
    on M-999 and a rule for it is written into the policy file by a person. Nothing serves a draft."""
    assert client.get("/api/proposals").status_code == 404
    r = client.post("/api/proposals/nope/decision", json={"decision": "reject", "approver": "x", "reason": "test"})
    assert r.status_code in (404, 405)


def test_rerun(client: TestClient):
    r = client.post("/api/rerun")
    assert r.status_code == 200 and r.json()["booked_nav"] == pytest.approx(1184.3, abs=0.05)


def test_signals_route_lines_vendor_metrics_up_against_the_workbook(client: TestClient):
    """The Foresight / AlphaSense slots: context beside a position, never a mark input."""
    s = client.get("/api/signals").json()
    assert set(s) >= {"as_of", "since", "providers", "note", "companies"}
    assert s["providers"]["metrics"]["live"] is False and "Foresight" in s["providers"]["metrics"]["name"]
    assert s["providers"]["news"]["protocol"].endswith("NewsSignalProvider")
    fern = s["companies"]["Fernwave"]["metrics"]
    rows = {r["key"]: r for r in fern["rows"]}
    assert rows["arr"]["vendor"] == 81.4 and rows["arr"]["workbook"] == pytest.approx(80.1)
    assert rows["arr"]["material"] is False and rows["cash"]["material"] is True   # 210 vs 66.1: a restatement to look at
    assert fern["extra"] == {"netRevenueRetention": 1.24}
    gry = s["companies"]["Gryphonel"]["news"]
    assert gry and gry[0]["published_at"].startswith("2026-") and gry[0]["topics"]
    # a company neither feed covers is simply absent, not an empty shell
    assert "Aravine" not in s["companies"]
    # and nothing about the run changed because a vendor said so
    run = client.get("/api/run").json()
    assert next(c for c in run["companies"] if c["company"] == "Fernwave")["arr"] == pytest.approx(80.1)


def test_watch_mode_recomputes_when_an_input_changes(paths: RunPaths, tmp_path: Path):
    """`hc-valuation run --watch`: a ledger written while serving becomes a new run id."""
    import time

    from hc_valuation.api.app import watch_inputs

    app = create_app(paths, static_dir=tmp_path / "no-static")
    client = TestClient(app)
    before = client.get("/api/health").json()["generated_at"]   # the id is input|policy|engine; the stamp moves
    seen: list[str] = []
    watch_inputs(app, interval_s=0.2, log=seen.append)
    time.sleep(0.5)
    paths.overrides.write_text(yaml.safe_dump({"overrides": [{
        "company": "Aravine", "quarter": "Q3 2026", "proposed": 13.878, "booked": 12.0,
        "reason": "watch test", "approver": "T", "created_at": "2026-09-04", "rule_ids_addressed": [],
    }]}))
    deadline = time.time() + 5
    while time.time() < deadline and not seen:
        time.sleep(0.1)
    assert seen and "recomputed run" in seen[0]
    after = client.get("/api/health").json()["generated_at"]
    assert after != before
    assert client.get("/api/companies/Aravine").json()["booked_mark"] == pytest.approx(12.0)


def test_output_workbook_route_names_the_file_the_close_will_write(client: TestClient, paths: RunPaths):
    """The executive dashboard asks "where is the file?". The route answers before the close has
    written it too, so the dialog can say where it *will* appear rather than showing nothing."""
    r = client.get("/api/output-workbook")
    assert r.status_code == 200
    d = r.json()
    assert d["quarter"] == "Q3 2026" and d["next_quarter"] == "Q4 2026"
    assert d["filename"] == "Q4 2026 HC Mock Portfolio Data.xlsx"
    assert d["folder"] == str(paths.workbook.parent)
    assert d["path"] == str(paths.workbook.parent / d["filename"])
    assert d["source_workbook"] == paths.workbook.name
    # nothing has been published in this scratch ledger, so the file does not exist yet
    assert d["exists"] is False and d["download_url"] is None and d["written_at"] is None


def test_output_workbook_download_is_offered_only_once_the_file_exists(client: TestClient, paths: RunPaths):
    """A download link that 404s is worse than no link, so the dialog is told whether to show one."""
    assert client.get("/api/output-workbook/download").status_code == 404

    out = paths.workbook.parent / "Q4 2026 HC Mock Portfolio Data.xlsx"
    shutil.copyfile(paths.workbook, out)                      # stand in for what the close writes
    d = client.get("/api/output-workbook").json()
    assert d["exists"] is True and d["download_url"] == "/api/output-workbook/download"
    assert d["size_bytes"] == out.stat().st_size and d["written_at"]

    got = client.get("/api/output-workbook/download")
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    # FastAPI percent-encodes the spaces in the filename, so compare the decoded header
    from urllib.parse import unquote
    cd = unquote(got.headers.get("content-disposition", ""))
    assert cd.startswith("attachment") and d["filename"] in cd
    assert got.content[:2] == b"PK" and len(got.content) == out.stat().st_size   # a real xlsx zip container


def test_override_on_a_ready_position_needs_no_finding(client: TestClient):
    """A reviewer who does not accept a Ready mark records their own: the API takes an override that
    names no finding when the position has none to decide (no flag, or watch items only)."""
    for name in ("Rivenmark", "Lumetra"):                      # no flag at all; a MONITOR watch item only
        before = client.get(f"/api/companies/{name}").json()
        assert before["readiness"] == "Ready" and all(f["severity"] == "MONITOR" for f in before["flags"]), name
        r = client.post("/api/overrides", json={"company": name, "booked": 1.25, "reason": "reviewer disagrees with the carry",
                                                "approver": "committee-test", "source_suggestion": "ready/manual"})
        assert r.status_code == 200, r.text
        after = r.json()
        assert after["booked_mark"] == 1.25 and after["proposed_mark"] == before["proposed_mark"]
        assert after["readiness"] == "Ready" and after["override"]["rule_ids_addressed"] == []
        assert any(s["rule_id"] == "E-01" for s in after["steps"]) and after["approval"] != "Pending"


def test_an_explicit_ledger_dir_outlives_upload_and_reset(tmp_path: Path):
    """`hc-valuation run --ledger-dir X`: an upload and a reset used to rebuild the paths from the
    root alone, so the server silently went back to recording in data/ — the committee's ledger."""
    import shutil
    from hc_valuation.config import repo_root
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    shutil.copy(repo_root() / "data" / "HC_Mock_Portfolio_Data.xlsx", root / "data" / "HC_Mock_Portfolio_Data.xlsx")
    shutil.copytree(repo_root() / "rules", root / "rules")
    shutil.copytree(repo_root() / "data" / "mock_responses", root / "data" / "mock_responses")
    ledger = tmp_path / "my_ledger"
    app = create_app(start_empty=True, root=root, provider="stub", static_dir=tmp_path / "no-static", ledger_dir_explicit=ledger)
    client = TestClient(app)
    assert Path(app.state.paths.ledger_dir) == ledger, "empty state already points at the operator's ledger"
    with open(repo_root() / "data" / "HC_Mock_Portfolio_Data.xlsx", "rb") as fh:
        job = client.post("/api/upload", files={"file": ("HC_Mock_Portfolio_Data.xlsx", fh.read())}).json()
    for _ in range(600):
        j = client.get(f"/api/upload/{job['id']}").json()
        if j["done"] or j["error"]:
            break
        time.sleep(0.2)
    assert j["done"] and not j["error"], j
    assert Path(app.state.paths.ledger_dir) == ledger, "the upload keeps recording where the operator said"
    r = client.post("/api/overrides", json={"company": "Rivenmark", "booked": 2.5, "reason": "t", "approver": "T", "source_suggestion": "ready/manual"})
    assert r.status_code == 200 and "Rivenmark" in (ledger / "overrides.yaml").read_text()
    assert not (root / "data" / "overrides.yaml").exists() or "Rivenmark" not in (root / "data" / "overrides.yaml").read_text()
    assert client.post("/api/reset", json={"confirm": "RESET"}).status_code == 200
    assert Path(app.state.paths.ledger_dir) == ledger, "and so does a reset"
    assert client.get("/api/health").json()["ledger"]["overrides"] == str(ledger / "overrides.yaml")
