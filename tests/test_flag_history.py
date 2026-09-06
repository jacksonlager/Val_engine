"""The flag trail behind every position: last quarter's flags on the archive point, so the
review tool can say "this BLOCK was a MONITOR three months ago".

The first quarter on the engine has no released predecessor, so the previous quarter's flags
are reconstructed by re-screening the book the run started from at the prior close — the
same policy, no activity, no overrides — and labelled as such. A published snapshot wins.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ROOT, execute_real

from hc_valuation.api.history import build_history
from hc_valuation.prior_screen import prior_quarter_config, prior_screen_for, screen_prior_close


@pytest.fixture(scope="module")
def result():
    return execute_real()


def test_prior_quarter_config_rolls_the_dates_back(result):
    q = prior_quarter_config(result.config).quarter
    assert q.label == "Q2 2026" and str(q.measurement_date) == "2026-06-30"
    assert str(q.prior_close) == "2026-03-31" and str(q.window_start) == "2026-04-01" and str(q.window_end) == "2026-06-30"
    # thresholds are the current policy's: the reconstruction is today's view of the old book
    assert prior_quarter_config(result.config).exceptions == result.config.exceptions


def test_reconstruction_is_the_book_re_screened_at_the_prior_close(result):
    s = screen_prior_close(result.snapshot, result.config, result.market)
    assert set(s) == {c.company for c in result.run.companies} and all(v["quarter"] == "Q2 2026" for v in s.values())
    # Drayvenn listed in Q3: at the June close it was an ordinary 2023 round, two years old
    assert s["Drayvenn"]["disposition"] == "MONITOR" and [f["rule_id"] for f in s["Drayvenn"]["flags"]] == ["X-201"]
    # Fernwave repriced in Q3 (CLEAR now); at the June close its round was over four years old
    assert s["Fernwave"]["disposition"] == "REVIEW" and "X-202" in [f["rule_id"] for f in s["Fernwave"]["flags"]]
    # a company already exited at the June close carries nothing
    assert s["Kolvani Health"]["disposition"] == "CLEAR" and s["Kolvani Health"]["flags"] == []
    # no activity, no overrides: every position carried at the workbook's prior mark
    assert all(len(v["flags"]) <= 6 for v in s.values())
    assert prior_screen_for(result) == s   # memoised on the result


def test_archive_points_carry_flags_and_their_source(result):
    h = build_history(result.run, Path(ROOT), prior_screen=prior_screen_for(result))
    d = h["companies"]["Drayvenn"]
    prior, now = d[0], d[-1]
    assert prior["quarter"] == "Q2 2026" and prior["disposition"] == "MONITOR" and prior["flags_source"] == "reconstructed"
    assert prior["flags"] == [{"rule_id": "X-201", "severity": "MONITOR", "family": "staleness"}]
    assert now["quarter"] == "Q3 2026" and now["disposition"] == "BLOCK" and now["flags"][0]["rule_id"] == "X-101"
    assert now["flags_source"] in {"published", "live"}
    # without a reconstruction the prior point has no flags and says so
    h0 = build_history(result.run, Path(ROOT))
    p0 = h0["companies"]["Drayvenn"][0]
    assert p0["disposition"] is None and p0["flags"] == [] and p0["flags_source"] is None


def test_a_published_snapshot_beats_the_reconstruction(result, tmp_path):
    """Once a quarter is released its flags are the record; the reconstruction never overwrites them."""
    root = tmp_path
    (root / "data" / "published").mkdir(parents=True)
    run = json.loads(result.run.model_dump_json())
    for c in run["companies"]:
        c["flags"] = [{"rule_id": "X-999", "severity": "REVIEW", "family": "test", "message": "", "action": "",
                       "points": [], "suggestions": [], "recommendation": None, "evidence": {}}]
        c["disposition"] = "REVIEW"
    (root / "data" / "published" / "2026Q2.json").write_text(json.dumps({
        "publish": {"quarter": "Q2 2026", "run_id": "abc", "published_at": "2026-07-01T00:00:00+00:00", "status": "final", "slug": "2026Q2"},
        "run": run}))
    h = build_history(result.run, root, prior_screen=prior_screen_for(result))
    p = h["companies"]["Drayvenn"][0]
    assert p["source"] == "published" and p["flags_source"] == "published" and p["flags"][0]["rule_id"] == "X-999"


def test_backfill_can_record_flags(result, tmp_path):
    bf = tmp_path / "mark_history.yaml"
    bf.write_text("companies:\n  Drayvenn:\n    - {quarter: Q1 2026, mark: 78.0, disposition: review, flags: [X-202, {rule_id: X-303, severity: monitor}]}\n"
                  "  Oakenvale:\n    - {quarter: Q1 2026, mark: 5.0, flags: [{rule_id: X-1, severity: loud}]}\n")
    h = build_history(result.run, Path(ROOT), backfill_path=bf, prior_screen=prior_screen_for(result))
    p = h["companies"]["Drayvenn"][0]
    assert p["quarter"] == "Q1 2026" and p["source"] == "backfill" and p["disposition"] == "REVIEW" and p["flags_source"] == "backfill"
    assert [(f["rule_id"], f["severity"]) for f in p["flags"]] == [("X-202", None), ("X-303", "MONITOR")]
    assert any("Oakenvale" in e and "severity" in e for e in h["errors"])


def test_history_endpoint_carries_the_flags(tmp_path):
    from fastapi.testclient import TestClient
    from hc_valuation.api.app import create_app
    client = TestClient(create_app(static_dir=tmp_path / "no-static"))
    h = client.get("/api/history").json()
    assert h["companies"]["Drayvenn"][0]["flags_source"] == "reconstructed"
    assert h["companies"]["Gryphonel"][0]["disposition"] == "REVIEW"   # stale round, before the deal was signed
