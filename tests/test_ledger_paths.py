"""The decision ledgers can be moved off `data/` — and when they are, nothing leaks back.

A rehearsal quarter, a synthetic test chain or a second reviewer's sandbox records overrides,
proposals, precedents and published snapshots. If those landed in `data/overrides.yaml` and
`data/published/` they would (a) become E-01 records the real book re-applies, (b) feed the
mark archive `api/history.py` reads, and (c) change the run id of the committed deliverable.
`RunPaths.default(ledger_dir=…)` / `--ledger-dir` give a chain its own folder; these tests pin
that every writer honours it and that the repo's own ledger is byte-identical afterwards.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hc_valuation.api.app import create_app
from hc_valuation.api.history import build_history
from hc_valuation.api.publish import list_published, load_published, publish_run
from hc_valuation.cli import app as cli_app
from hc_valuation.config import repo_root
from hc_valuation.pipeline import RunPaths, execute

ROOT = repo_root()
REAL_LEDGER = ROOT / "data" / "overrides.yaml"
REAL_PUBLISHED = ROOT / "data" / "published"


def _snapshot_real_ledger() -> tuple[bytes, list[str]]:
    return REAL_LEDGER.read_bytes(), sorted(str(p.relative_to(REAL_PUBLISHED)) for p in REAL_PUBLISHED.rglob("*"))


# ------------------------------------------------------------------ RunPaths

def test_default_paths_keep_the_real_ledger_under_data():
    p = RunPaths.default(root=ROOT)
    assert p.overrides == ROOT / "data" / "overrides.yaml"
    assert p.published_dir == ROOT / "data" / "published"
    assert p.ledger_dir == ROOT / "data"


def test_ledger_dir_moves_every_decision_record_together(tmp_path: Path):
    p = RunPaths.default(root=ROOT, ledger_dir=tmp_path / "chain")
    assert p.overrides == tmp_path / "chain" / "overrides.yaml"
    assert p.proposals_dir == tmp_path / "chain" / "proposals"
    assert p.precedent == tmp_path / "chain" / "precedent.yaml"
    assert p.published_dir == tmp_path / "chain" / "published"
    assert p.ledger_dir == tmp_path / "chain"
    # the workbook and the policy are not ledgers: they stay where they were asked for
    assert p.workbook == ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx"
    assert p.policy == ROOT / "rules" / "2026Q3.yaml"


def test_overrides_alone_moves_only_the_e01_file(tmp_path: Path):
    p = RunPaths.default(root=ROOT, overrides=tmp_path / "mine.yaml")
    assert p.overrides == tmp_path / "mine.yaml"
    assert p.published_dir == ROOT / "data" / "published"
    # ... and wins over ledger_dir for that one file
    q = RunPaths.default(root=ROOT, overrides=tmp_path / "mine.yaml", ledger_dir=tmp_path / "chain")
    assert q.overrides == tmp_path / "mine.yaml" and q.published_dir == tmp_path / "chain" / "published"


def test_older_seven_field_construction_still_publishes_under_data(tmp_path: Path):
    """Tests and callers written before `published_dir` existed keep the old default."""
    p = RunPaths(root=tmp_path, policy=ROOT / "rules" / "2026Q3.yaml", workbook=ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx",
                 overrides=tmp_path / "o.yaml", proposals_dir=tmp_path / "p", precedent=tmp_path / "pr.yaml",
                 open_items_carry=tmp_path / "carry.yaml")
    assert p.published_dir == tmp_path / "data" / "published"


# ------------------------------------------------------------------ the writers

@pytest.fixture()
def chain(tmp_path: Path) -> RunPaths:
    """A run over the real workbook whose every decision record lands under tmp/chain."""
    return RunPaths.default(root=ROOT, ledger_dir=tmp_path / "chain")


def test_api_override_appends_to_the_chain_ledger_and_not_to_data(chain: RunPaths, tmp_path: Path):
    before = _snapshot_real_ledger()
    client = TestClient(create_app(chain, static_dir=tmp_path / "no-static"))
    h = client.get("/api/health").json()
    assert h["ledger"]["overrides"] == str(chain.overrides)
    assert h["ledger"]["published_dir"] == str(chain.published_dir)
    r = client.post("/api/overrides", json={"company": "Gryphonel", "booked": 4.6592, "reason": "rehearsal",
                                            "approver": "Tester", "rule_ids_addressed": ["X-101"]})
    assert r.status_code == 200, r.text
    assert chain.overrides.exists()
    recs = yaml.safe_load(chain.overrides.read_text())["overrides"]
    assert [x["company"] for x in recs] == ["Gryphonel"]
    assert _snapshot_real_ledger() == before, "the repo's own ledger must be byte-identical"


def test_publish_and_history_read_the_chain_folder(chain: RunPaths, tmp_path: Path):
    before = _snapshot_real_ledger()
    r = execute(chain, provider="stub", generated_at=datetime(2026, 9, 30), adjudicate=False)
    rec = publish_run(r.run, chain.root, approver="Tester", published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                      require_decisions=False, published=chain.published_dir)
    assert (chain.published_dir / f"{rec['slug']}.json").exists()
    assert (chain.published_dir / "latest.json").exists()
    assert [x["published_by"] for x in list_published(chain.root, chain.published_dir)] == ["Tester"]
    assert load_published(chain.root, published=chain.published_dir)[0]["published_by"] == "Tester"
    # the archive assembled for the chain sees its own snapshot; the repo's snapshot is not read
    h = build_history(r.run, chain.root, published=chain.published_dir)
    assert h["counts"]["published"] == 100
    assert all(pt["published_at"] == "2026-10-01T00:00:00+00:00" for pts in h["companies"].values() for pt in pts if pt["quarter"] == "Q3 2026")
    assert _snapshot_real_ledger() == before


def test_api_publish_lands_in_the_chain_folder(chain: RunPaths, tmp_path: Path):
    """The dashboard's Publish button, on a chain whose every position has been decided."""
    before = _snapshot_real_ledger()
    client = TestClient(create_app(chain, static_dir=tmp_path / "no-static"))
    out = client.get("/api/publish/readiness").json()["outstanding"]
    for item in out:
        booked = item["proposed_mark"]
        r = client.post("/api/overrides", json={"company": item["company"], "booked": booked, "reason": "rehearsal decision",
                                                "approver": "Reviewer A", "rule_ids_addressed": [x["rule_id"] for x in item["rules"]]})
        assert r.status_code == 200, r.text
    assert client.get("/api/publish/readiness").json()["ready"]
    r = client.post("/api/publish", json={"approver": "Reviewer B", "note": "chain"})
    assert r.status_code == 200, r.text
    assert (chain.published_dir / "2026Q3.json").exists()
    assert client.get("/api/published").json()[0]["published_by"] == "Reviewer B"
    assert _snapshot_real_ledger() == before


# ------------------------------------------------------------------ the command line

def test_cli_ledger_dir_publishes_into_the_folder_and_leaves_data_alone(tmp_path: Path):
    before = _snapshot_real_ledger()
    ledger = tmp_path / "chain"
    r = CliRunner().invoke(cli_app, ["publish", "--approver", "Tom Moore", "--proposed", "--ledger-dir", str(ledger)])
    assert r.exit_code == 0, r.output
    assert (ledger / "published" / "2026Q3.json").exists()
    assert json.loads((ledger / "published" / "latest.json").read_text())["slug"] == "2026Q3"
    assert _snapshot_real_ledger() == before


def test_cli_overrides_flag_points_the_run_at_another_ledger(tmp_path: Path):
    ledger = tmp_path / "mine.yaml"
    ledger.write_text(yaml.safe_dump({"overrides": [{
        "company": "Gryphonel", "quarter": "Q3 2026", "proposed": 4.6592, "booked": 3.5, "reason": "hold until close",
        "approver": "Tester", "created_at": "2026-10-01", "rule_ids_addressed": ["X-101"]}]}))
    out = tmp_path / "dist"
    r = CliRunner().invoke(cli_app, ["export", "--overrides", str(ledger), "--out", str(out), "--provider", "stub"])
    assert r.exit_code == 0, r.output
    marks = (out / "marks.csv").read_text()
    row = next(line for line in marks.splitlines() if line.startswith("Gryphonel"))
    assert ",3.5," in row or ",3.50," in row, row
