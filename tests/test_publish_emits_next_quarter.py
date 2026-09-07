"""A FINAL publish emits next quarter's input beside the workbook just closed — and a book re-run
after its own close does not read the sidecar it wrote.

The close is the moment the next quarter's opening book exists: booked marks become Prior Mark,
ownership / invested / realized are post-activity, the activity tab is empty and named for the new
quarter, and `open_items_carry.yaml` beside it carries the open items, the explained departures,
the staleness anchors and the note legs. The file appears in the review tool's Workbook select.
"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import openpyxl
import pytest
import yaml
from fastapi.testclient import TestClient

from hc_valuation.api.app import create_app
from hc_valuation.config import load_config, repo_root
from hc_valuation.pipeline import RunPaths, execute, next_quarter_input_name, previous_quarter_label, sidecar_for

ROOT = repo_root()


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "rules", tmp_path / "rules")
    (tmp_path / "data").mkdir()
    shutil.copy(ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx", tmp_path / "data" / "HC_Mock_Portfolio_Data.xlsx")
    shutil.copytree(ROOT / "data" / "mock_responses", tmp_path / "data" / "mock_responses")
    (tmp_path / "data" / "overrides.yaml").write_text("overrides: []\n")     # never the working ledger
    return tmp_path


def test_names_and_quarters():
    assert next_quarter_input_name(Path("HC_Mock_Portfolio_Data.xlsx"), "Q4 2026") == "Q4 2026 HC Mock Portfolio Data.xlsx"
    assert next_quarter_input_name(Path("Q4 2026 HC Mock Portfolio Data.xlsx"), "Q1 2027") == "Q1 2027 HC Mock Portfolio Data.xlsx"
    assert previous_quarter_label("Q1 2027") == "Q4 2026" and previous_quarter_label("Q4 2026") == "Q3 2026"


def _decide_everything(client: TestClient) -> None:
    for item in client.get("/api/publish/readiness").json()["outstanding"]:
        r = client.post("/api/overrides", json={"company": item["company"], "booked": item["proposed_mark"], "reason": "walkthrough",
                                                "approver": "Reviewer A", "rule_ids_addressed": [x["rule_id"] for x in item["rules"]]})
        assert r.status_code == 200, r.text


def test_final_publish_writes_next_quarter_beside_the_workbook(root: Path, tmp_path: Path):
    paths = RunPaths.default(root=root, workbook=root / "data" / "HC_Mock_Portfolio_Data.xlsx", policy=root / "rules" / "2026Q3.yaml")
    client = TestClient(create_app(paths, provider="stub", static_dir=tmp_path / "no-static"))
    _decide_everything(client)
    r = client.post("/api/publish", json={"approver": "Tom Moore", "note": "close"})
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["status"] == "final"
    nxt = Path(rec["next_quarter_input"])
    assert nxt == root / "data" / "Q4 2026 HC Mock Portfolio Data.xlsx" and nxt.exists()
    sidecar = root / "data" / "open_items_carry.yaml"
    assert yaml.safe_load(sidecar.read_text())["quarter"] == "Q3 2026"
    wb = openpyxl.load_workbook(nxt)
    assert "Q4 2026 Activity" in wb.sheetnames and wb["Q4 2026 Activity"].max_row == 1
    # the booked book is the opening book
    booked = {c["company"]: c["booked_mark"] for c in client.get("/api/run").json()["companies"] if c["status_after"] == "Active"}
    ws = wb["Portfolio"]; hdr = [c.value for c in ws[1]]
    rows = {r[0]: dict(zip(hdr, r)) for r in ws.iter_rows(min_row=2, values_only=True)}
    for name, mark in booked.items():
        assert rows[name]["Prior Mark ($M)"] == pytest.approx(mark, abs=1e-6), name
    # nothing to review yet: an empty activity tab keeps it out of the Workbook select ...
    assert "Q4 2026" not in [w["quarter"] for w in client.get("/api/workbooks").json()["workbooks"]]
    # ... until the quarter's first row is entered; then it is a real quarter, on the committee ledger, under its own policy
    from datetime import datetime
    wb["Q4 2026 Activity"].append([datetime(2026, 10, 5), "Gryphonel", "Acquisition (Closed)", "All-cash acquisition", 133.0, None, None, 4.788, "Closed."])
    wb.save(nxt)
    from hc_valuation.config import write_next_policy
    if not (root / "rules" / "2026Q4.yaml").exists():      # the repo may already carry it
        write_next_policy(root / "rules" / "2026Q3.yaml")
    q4 = next(w for w in client.get("/api/workbooks").json()["workbooks"] if w["quarter"] == "Q4 2026")
    assert not q4["synthetic"] and q4["ledger_dir"] == "data" and q4["usable"] and q4["policy"] == "rules/2026Q4.yaml"
    assert q4["provider"] != "synthetic"


def test_a_proposed_publish_emits_nothing(root: Path, tmp_path: Path):
    from hc_valuation.api.publish import publish_run
    paths = RunPaths.default(root=root, workbook=root / "data" / "HC_Mock_Portfolio_Data.xlsx", policy=root / "rules" / "2026Q3.yaml")
    r = execute(paths, provider="stub", adjudicate=False)
    rec = publish_run(r.run, root, approver="Tom Moore", require_decisions=False)
    assert rec["status"] == "proposed"
    assert not list((root / "data").glob("Q4 2026 *.xlsx"))


def test_a_book_rerun_after_its_own_close_ignores_the_sidecar_it_wrote(root: Path):
    """The Q3 close leaves data/open_items_carry.yaml (quarter: Q3 2026) beside the Q3 workbook.
    Re-running Q3 must not read it as prior state — its own open items would age against itself."""
    paths = RunPaths.default(root=root, workbook=root / "data" / "HC_Mock_Portfolio_Data.xlsx", policy=root / "rules" / "2026Q3.yaml")
    before = execute(paths, provider="stub", adjudicate=False).run
    (root / "data" / "open_items_carry.yaml").write_text(yaml.safe_dump({
        "quarter": "Q3 2026", "open_items": [{"company": "Gryphonel", "kind": "pending_acquisition", "opened": "2026-09-08",
                                              "opened_quarter": "Q3 2026", "age_quarters": 3, "escalated": True, "detail": "x"}],
        "mark_basis": [], "staleness_anchors": [], "note_legs": []}))
    paths2 = RunPaths.default(root=root, workbook=root / "data" / "HC_Mock_Portfolio_Data.xlsx", policy=root / "rules" / "2026Q3.yaml")
    assert paths2.open_items_carry.exists()
    assert not sidecar_for(paths2, load_config(paths2.policy)).exists()
    after = execute(paths2, provider="stub", adjudicate=False).run
    assert after.manifest.run_id == before.manifest.run_id and after.model_dump_json() == before.model_dump_json()
    # a sidecar from the quarter before is read
    (root / "data" / "open_items_carry.yaml").write_text(yaml.safe_dump({"quarter": "Q2 2026", "open_items": [], "mark_basis": [],
                                                                         "staleness_anchors": [], "note_legs": []}))
    assert sidecar_for(paths2, load_config(paths2.policy)).exists()
