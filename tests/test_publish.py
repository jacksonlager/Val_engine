"""The publish gate and the executive view-model."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hc_valuation.api.app import create_app
from hc_valuation.api.exec_view import DRIVERS, build_exec_view
from hc_valuation.api.publish import (PublishBlocked, exec_payload, list_published, load_published, outstanding,
                                      publish_run)
from hc_valuation.export.exec_report import render_exec_report
from hc_valuation.pipeline import RunPaths, execute

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def result():
    return execute(RunPaths.default(REPO), generated_at=datetime(2026, 9, 30))


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    for d in ("data", "rules"):
        shutil.copytree(REPO / d, tmp_path / d,
                        ignore=shutil.ignore_patterns("published", "proposals", "precedent.yaml", "overrides.yaml",
                                                      "open_items_carry.yaml"))
    return tmp_path


# ------------------------------------------------------------------ view-model

def test_bridge_reconciles_prior_to_booked(result):
    v = build_exec_view(result.run, {})
    h = v["headline"]
    assert v["bridge"], "a quarter with 18 events must produce bridge bars"
    assert v["bridge"][-1]["running_total"] == pytest.approx(h["booked_nav"], abs=0.01)
    assert sum(b["delta"] for b in v["bridge"]) == pytest.approx(h["booked_nav"] - h["prior_nav"], abs=0.01)
    labels = [b["label"] for b in v["bridge"]]
    order = [lab for _, lab, _ in DRIVERS]
    assert labels == [lab for lab in order if lab in labels], "bars are drawn in the policy's driver order"


def test_bridge_drivers_classify_the_known_events(result):
    v = build_exec_view(result.run, {})
    by = {b["key"]: b for b in v["bridge"]}
    assert {c["company"] for c in by["ipo"]["companies"]} == {"Drayvenn"}
    assert {c["company"] for c in by["exits"]["companies"]} == {"Cindral"}
    assert {c["company"] for c in by["writeoffs"]["companies"]} == {"Larkspell", "Islewind"}
    assert {c["company"] for c in by["rounds_down"]["companies"]} == {"Oakenvale", "Tarnwick Aerospace"}
    assert {c["company"] for c in by["secondary"]["companies"]} == {"Marrowick Bio"}
    assert "overrides" not in by, "no committee overrides recorded in the base run"


def test_executives_see_booked_marks_and_actions_only(result):
    v = build_exec_view(result.run, {})
    assert {d["company"] for d in v["decisions"]} == {
        "Drayvenn", "Gryphonel", "Oakenvale", "Tarnwick Aerospace", "Duskfern", "Birchhollow", "Pellagrin"}
    for d in v["decisions"]:
        assert d["actions"], f"{d['company']} is blocked but shows no action for the committee"
        assert all(a["severity"] != "MONITOR" for a in d["actions"])
        assert all(a["action"] for a in d["actions"])
    assert v["meta"]["status"] == "proposed"
    assert v["headline"]["events"] == 18
    assert v["hierarchy"]["level1"]["count"] == 1


def test_marks_schedule_lists_every_position(result):
    v = build_exec_view(result.run, {})
    marks = v["marks"]
    assert len(marks) == len(result.run.companies) == 100
    assert {m["company"] for m in marks} == {c.company for c in result.run.companies}
    assert sum(m["booked"] for m in marks) == pytest.approx(v["headline"]["booked_nav"], abs=0.05)
    # default order: fund, then size of movement
    for a, b in zip(marks, marks[1:]):
        assert (a["fund"], -abs(a["delta"])) <= (b["fund"], -abs(b["delta"]))
    for key in ("company", "fund", "sector", "stage", "status", "fv_level", "prior", "proposed", "booked",
                "delta", "delta_pct", "disposition", "driver_kind", "driver_label"):
        assert key in marks[0]


def test_realized_exits_are_not_mark_downs(result):
    v = build_exec_view(result.run, {})
    realized = v["movers"]["realized"]
    assert [r["company"] for r in realized] == ["Cindral"]
    assert realized[0]["driver_kind"] == "realized" and realized[0]["driver_label"] == "Realized $28.2M"
    assert "Cindral" not in {r["company"] for r in v["movers"]["down"]}
    downs = {r["company"]: r["driver_kind"] for r in v["movers"]["down"]}
    assert downs["Larkspell"] == "written_off" and downs["Oakenvale"] == "round_down"
    assert all(r["driver_kind"] == "round_up" for r in v["movers"]["up"] if r["driver"] == "rounds_up")
    by = {b["key"]: b for b in v["bridge"]}
    assert by["exits"]["kind"] == "realized" and by["writeoffs"]["kind"] == "down"


def test_status_follows_the_publish_record(result):
    assert build_exec_view(result.run, {})["meta"]["status"] == "proposed"
    assert build_exec_view(result.run, {"status": "final"})["meta"]["status"] == "final"


def test_decision_actions_carry_suggestions(result):
    v = build_exec_view(result.run, {})
    actions = [a for d in v["decisions"] for a in d["actions"]]
    assert all("suggestions" in a and "points" in a for a in actions)
    with_suggestions = [a for a in actions if a["suggestions"]]
    assert with_suggestions, "at least one blocked flag should offer a numbered resolution"
    for sg in with_suggestions[0]["suggestions"]:
        assert set(sg) == {"key", "label", "reasons", "booked"} and isinstance(sg["booked"], float)


def test_composition_shares_sum_to_one(result):
    v = build_exec_view(result.run, {})
    for key in ("by_sector", "by_stage", "by_fund"):
        assert sum(s["share"] for s in v["composition"][key]) == pytest.approx(1.0, abs=0.01)


# ------------------------------------------------------------------ publish gate

def test_publish_writes_snapshot_and_latest(result, root):
    rec = publish_run(result.run, root, approver="Jackson Lagerwey", note="IC pack",
                      published_at=datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc), require_decisions=False)
    assert rec["slug"] == "2026Q3" and rec["status"] == "proposed"
    # status follows readiness: one position is Blocked (a missing input), 27 are not Ready
    assert len(rec["open_blocks"]) == 1 and len(rec["open_positions"]) == 27
    assert (root / "data" / "published" / "2026Q3.json").exists()
    assert json.loads((root / "data" / "published" / "latest.json").read_text())["slug"] == "2026Q3"
    pub, run = load_published(root)
    assert pub["published_by"] == "Jackson Lagerwey"
    assert run.totals.booked_nav == pytest.approx(result.run.totals.booked_nav)


def test_republish_keeps_history(result, root):
    publish_run(result.run, root, approver="A", published_at=datetime(2026, 10, 1, tzinfo=timezone.utc), require_decisions=False)
    publish_run(result.run, root, approver="B", note="second", published_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
                require_decisions=False)
    hist = list((root / "data" / "published" / "history").glob("2026Q3_*.json"))
    assert len(hist) == 1, "the earlier release is kept, never overwritten silently"
    assert load_published(root)[0]["published_by"] == "B"
    assert [r["published_by"] for r in list_published(root)] == ["B"]


def test_publish_requires_an_approver(result, root):
    with pytest.raises(ValueError):
        publish_run(result.run, root, approver="   ", require_decisions=False)


# ------------------------------------------------------------------ the decision gate

def test_outstanding_lists_every_block_and_review_with_its_flags(result):
    items = outstanding(result.run)
    by_disp = {}
    for i in items:
        by_disp.setdefault(i["disposition"], []).append(i)
    assert len(by_disp["BLOCK"]) == 7 and len(by_disp["REVIEW"]) == 20
    by_ready = {}
    for i in items:
        by_ready.setdefault(i["readiness"], []).append(i)
    # readiness splits the seven BLOCKs: one is missing an input, six are judgments
    assert len(by_ready["Blocked"]) == 1 and len(by_ready["Needs Review"]) == 26
    blocked = by_ready["Blocked"][0]
    assert blocked["company"] == "Drayvenn" and blocked["provisional"]
    assert "closing price" in blocked["why"], "a blocked item names the input it is missing"
    assert {i["why"] for i in items if not i["provisional"]} == {
        "Decision required before booking", "Check required to confirm the mark"}
    for i in items:
        assert i["rules"], f"{i['company']} is waiting but lists no flag to decide"
        assert all(r["severity"] in ("BLOCK", "REVIEW") for r in i["rules"])
    gry = next(i for i in items if i["company"] == "Gryphonel")
    assert [r["rule_id"] for r in gry["rules"]] == ["X-101"]      # the stale-round question is superseded by the signed deal
    assert all(c.disposition.value in ("MONITOR", "CLEAR") for c in result.run.companies
               if c.company not in {i["company"] for i in items})


def test_publish_refuses_an_undecided_book(result, root):
    with pytest.raises(PublishBlocked) as exc:
        publish_run(result.run, root, approver="Jackson Lagerwey")
    assert len(exc.value.items) == 27 and "27 position(s)" in str(exc.value) and "7 BLOCK and 20 REVIEW" in str(exc.value)
    assert not (root / "data" / "published").exists(), "nothing is written when the gate refuses"


def _decide_everything(client: TestClient, approver: str = "IC") -> int:
    """Resolve every outstanding position through the API the way the dashboard does: an E-01
    override addressed to each waiting flag, booking the engine's recommended number."""
    run = client.get("/api/run").json()
    n = 0
    for c in run["companies"]:
        if c["disposition"] not in ("BLOCK", "REVIEW"):
            continue
        waiting = [f for f in c["flags"] if f["severity"] in ("BLOCK", "REVIEW")]
        rec = next((f["recommendation"] for f in waiting if f.get("recommendation")), None)
        booked = rec["booked"] if rec else c["proposed_mark"]
        r = client.post("/api/overrides", json={"company": c["company"], "booked": booked, "approver": approver,
                                                "reason": "committee confirmed", "rule_ids_addressed": [f["rule_id"] for f in waiting]})
        assert r.status_code == 200, r.text
        n += 1
    return n


def test_api_gate_opens_only_after_every_item_is_decided(root):
    c = TestClient(create_app(RunPaths.default(root)))
    ready = c.get("/api/publish/readiness").json()
    assert ready["ready"] is False and len(ready["outstanding"]) == 27
    r = c.post("/api/publish", json={"approver": "Jackson Lagerwey", "note": ""})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert len(detail["outstanding"]) == 27 and "before the book can be published" in detail["message"]
    assert c.get("/api/exec").status_code == 404, "nothing reached the executives"
    # decide all but one: still locked, and the popup list names exactly the one left
    assert _decide_everything(c) == 27
    ready = c.get("/api/publish/readiness").json()
    assert ready["ready"] is True and ready["outstanding"] == []
    run = c.get("/api/run").json()
    assert all(x["disposition"] in ("MONITOR", "CLEAR") for x in run["companies"])
    r = c.post("/api/publish", json={"approver": "Jackson Lagerwey", "note": "all decided"})
    assert r.status_code == 200 and r.json()["status"] == "final" and r.json()["open_blocks"] == []
    assert c.get("/api/exec").json()["meta"]["status"] == "final"


def test_publish_needs_a_second_pair_of_eyes(root):
    """The person who approved this quarter's overrides may not be the one who releases them."""
    from hc_valuation.api.publish import SecondApproverRequired
    c = TestClient(create_app(RunPaths.default(root)))
    _decide_everything(c, approver="Jackson Lagerwey")
    r = c.post("/api/publish", json={"approver": "jackson lagerwey", "note": ""})       # same person, case-folded
    assert r.status_code == 409 and r.json()["detail"]["second_approver"] is True
    assert "27 position(s)" in r.json()["detail"]["message"] and "second person" in r.json()["detail"]["message"]
    assert c.get("/api/exec").status_code == 404
    r = c.post("/api/publish", json={"approver": "Tom Moore", "note": "released after review"})
    assert r.status_code == 200 and r.json()["published_by"] == "Tom Moore" and r.json()["status"] == "final"
    # the library call says the same thing, and the policy switch turns it off
    run = c.get("/api/run").json()
    from hc_valuation.pipeline import execute
    res = execute(RunPaths.default(root))
    with pytest.raises(SecondApproverRequired):
        publish_run(res.run, root, approver="Jackson Lagerwey")
    publish_run(res.run, root, approver="Jackson Lagerwey", require_second_approver=False)


def test_api_gate_names_the_last_undecided_position(root):
    c = TestClient(create_app(RunPaths.default(root)))
    run = c.get("/api/run").json()
    waiting = [x for x in run["companies"] if x["disposition"] in ("BLOCK", "REVIEW")]
    keep = waiting[-1]["company"]
    for x in waiting[:-1]:
        flags = [f for f in x["flags"] if f["severity"] in ("BLOCK", "REVIEW")]
        assert c.post("/api/overrides", json={"company": x["company"], "booked": x["proposed_mark"], "approver": "IC",
                                              "reason": "confirmed", "rule_ids_addressed": [f["rule_id"] for f in flags]}).status_code == 200
    r = c.post("/api/publish", json={"approver": "Jackson Lagerwey", "note": ""})
    assert r.status_code == 409 and [i["company"] for i in r.json()["detail"]["outstanding"]] == [keep]


def test_exec_payload_and_static_report(result, root):
    assert exec_payload(root) is None
    publish_run(result.run, root, approver="Jackson Lagerwey", published_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
                require_decisions=False)
    view = exec_payload(root)
    assert view["meta"]["published_by"] == "Jackson Lagerwey" and view["history"][0]["slug"] == "2026Q3"
    html = render_exec_report(view, static_dir=root / "does-not-exist")
    assert "window.__HC_EXEC__" in html and "Drayvenn" in html


# ------------------------------------------------------------------ API

def test_api_publish_then_exec(root):
    c = TestClient(create_app(RunPaths.default(root)))
    assert c.get("/api/exec").status_code == 404
    assert c.post("/api/publish", json={"approver": " ", "note": ""}).status_code == 400
    assert c.post("/api/publish", json={"approver": "Jackson Lagerwey", "note": ""}).status_code == 409, "undecided book"
    _decide_everything(c)
    r = c.post("/api/publish", json={"approver": "Jackson Lagerwey", "note": "Q3 final"})
    assert r.status_code == 200 and r.json()["status"] == "final"
    v = c.get("/api/exec").json()
    assert v["headline"]["booked_nav"] == pytest.approx(1184.28, abs=0.01)
    assert c.get("/api/exec/2026Q3").status_code == 200
    assert c.get("/api/exec/nope").status_code == 404
    assert [p["quarter"] for p in c.get("/api/published").json()] == ["Q3 2026"]
    page = c.get("/exec/")
    # With the executive bundle built, /exec/ serves the SPA (which fetches /api/exec); without it, the
    # fallback page inlines the view-model. Either way the executive site is reachable.
    assert page.status_code == 200 and ("__HC_EXEC__" in page.text or 'id="root"' in page.text)
