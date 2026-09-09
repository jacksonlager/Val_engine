"""E-03 — same input → byte-identical output; a policy change is visible and named."""
from __future__ import annotations

import json

import pytest

import yaml

from conftest import GOLDEN_PATH, POLICY_PATH, canonical, diff_runs, execute_real


def test_two_runs_serialize_byte_identical():
    a = execute_real().run.model_dump_json()
    b = execute_real().run.model_dump_json()
    assert a == b
    assert a.encode() == b.encode()


def test_serialisation_is_stable_across_json_round_trip(run_real):
    once = json.dumps(canonical(run_real), sort_keys=True)
    twice = json.dumps(json.loads(once), sort_keys=True)
    assert once == twice


def test_threshold_change_fails_golden_with_a_readable_diff(tmp_path):
    raw = yaml.safe_load(POLICY_PATH.read_text())
    assert raw["exceptions"]["runway"]["review_below_mo"] == 6
    raw["exceptions"]["runway"]["review_below_mo"] = 12   # every X-303 becomes an X-304
    policy = tmp_path / "2026Q3_runway12.yaml"
    policy.write_text(yaml.safe_dump(raw, sort_keys=False))

    changed = canonical(execute_real(policy=policy).run)
    golden = json.loads(GOLDEN_PATH.read_text())
    diff = diff_runs(golden, changed)

    assert diff, "changing a threshold must change the output"
    text = "\n".join(diff)
    # the diff names the company and the field, not just "something changed"
    company_lines = [l for l in diff if l.startswith("run.companies[")]
    assert company_lines, text
    assert any("X-304" in l or ".disposition" in l or ".flags" in l for l in company_lines), text
    named = {l.split("[", 1)[1].split("]", 1)[0] for l in company_lines}
    assert named and all(n for n in named), text
    assert "run.totals.dispositions" in text, "queue counts must move when the runway threshold moves"


def test_generated_at_does_not_leak_into_run_id(run_real):
    """run_id hashes input + policy + engine; the clock is recorded but never identifies a run."""
    from datetime import datetime
    from hc_valuation import pipeline
    from conftest import ROOT, WORKBOOK_PATH
    other = pipeline.execute(pipeline.RunPaths.default(root=ROOT, workbook=WORKBOOK_PATH), generated_at=datetime(2026, 10, 1, 12, 0)).run
    assert other.manifest.run_id == run_real.manifest.run_id
    assert other.manifest.generated_at != run_real.manifest.generated_at
    assert canonical(other)["companies"] == canonical(run_real)["companies"]


def test_a_decision_changes_the_run_id(run_real):
    """The ledger is an input: an override recorded after a publish must give the live run a new
    identity, or the review tool cannot tell executives are looking at an older book."""
    from hc_valuation.engine.models import OverrideLedger, OverrideRecord
    from hc_valuation.engine.run import run_valuation
    from conftest import execute_real
    r = execute_real()
    rec = OverrideRecord(company="Gryphonel", quarter=r.config.quarter.label, proposed=4.6592, booked=4.0,
                         reason="test", approver="t", created_at=r.config.quarter.measurement_date, rule_ids_addressed=("X-101",))
    from hc_valuation.ingest.reader import read_workbook
    snapshot, feed = read_workbook(r.paths.workbook, r.config)
    with_override = run_valuation(snapshot, feed, r.market, OverrideLedger(records=(rec,)), r.config,
                                  input_sha256=r.run.manifest.input_sha256, generated_at=r.run.manifest.generated_at)
    assert with_override.manifest.run_id != run_real.manifest.run_id
    assert with_override.by_company()["Gryphonel"].booked_mark == pytest.approx(4.0)
