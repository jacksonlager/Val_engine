"""Stress tests for the human-intervention controls.

The claim under test: *unresolved material issues cannot silently become approved marks, and
AI suggestions cannot bypass these controls.* Every test asserts a concrete outcome.

Sections
  A. readiness invariants over the real run and a few synthetic runs
  B. the publish gate (API, library and CLI), including the `--proposed` bypass
  C. override controls: what an E-01 record can and cannot resolve
  D. the AI seams: the recommender and the adjudicator cannot reach a mark or a readiness
  E. a hunt for any path to "Approved and published" on an open position

Defect protocol: a real gap is asserted as the CORRECT behaviour and marked
`xfail(strict=True, reason="DEFECT: ...")`; a debatable one is asserted as observed and listed
under POLICY QUESTIONS in the report. Nothing under src/, rules/ or data/ is touched: the API
tests run on a scratch copy of data/ and rules/.
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from conftest import GENERATED_AT, event, make_workbook, only, position, with_policy
from hc_valuation.adjudication import load_proposal, proposal_path
from hc_valuation.adjudication.promote import record_decision
from hc_valuation.adjudication.schema import Provenance, TreatmentProposal, catalogue_version_for, validation_scope
from hc_valuation.api.app import append_override, create_app
from hc_valuation.api.exec_view import build_exec_view
from hc_valuation.api.history import build_history
from hc_valuation.api.publish import PublishBlocked, exec_payload, load_published, publish_run
from hc_valuation.cli import app as cli_app
from hc_valuation.config import RuleConfig, load_config, repo_root
from hc_valuation.engine.models import (Approval, OverrideLedger, OverrideRecord, PositionRecommendation, Readiness,
                                        Recommendation, Severity, ValuationRun)
from hc_valuation.engine.readiness import MISSING_INPUT_RULES
from hc_valuation.engine.run import build_registry
from hc_valuation.pipeline import RunPaths, execute
from hc_valuation.recommend import (POSITION_PROMPT, ClaudeChooser, PolicyChooser, actionable,
                                    build_brief, build_position_brief, recommend_run)

ROOT = repo_root()
ACTIONABLE = (Severity.BLOCK, Severity.REVIEW)
PROVISIONAL_COMPANY = "Drayvenn"        # listed, no measurement-date quote: X-101 on a stand-in price


# ============================================================================ helpers

@pytest.fixture()
def scratch(tmp_path: Path) -> RunPaths:
    """A private copy of data/ and rules/ so ledgers, snapshots and the policy file can be
    written freely. The policy is copied too (unlike test_suggestions' fixture) so a test can
    flip a switch in it and rerun."""
    data = tmp_path / "data"
    shutil.copytree(ROOT / "data", data, ignore=shutil.ignore_patterns("sample_run.json", "published", "market_cache", "overrides.yaml", "published", "open_items_carry.yaml", "Q? ???? *.xlsx"))
    shutil.copytree(ROOT / "rules", tmp_path / "rules")
    (data / "overrides.yaml").write_text("overrides: []\n")
    return RunPaths(
        root=tmp_path, policy=tmp_path / "rules" / "2026Q3.yaml", workbook=data / "HC_Mock_Portfolio_Data.xlsx",
        overrides=data / "overrides.yaml", proposals_dir=data / "proposals", precedent=data / "precedent.yaml",
        open_items_carry=data / "open_items_carry.yaml",
    )


def _client(scratch: RunPaths) -> TestClient:
    return TestClient(create_app(scratch, static_dir=scratch.root / "no-static"))


def _edit_policy(path: Path, **dotted: Any) -> None:
    raw = yaml.safe_load(path.read_text())
    for key, value in dotted.items():
        node = raw
        *parents, leaf = key.split(".")
        for k in parents:
            node = node[k]
        node[leaf] = value
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    load_config(path)   # the edited file still validates


def _company(client: TestClient, name: str) -> dict:
    r = client.get(f"/api/companies/{name}")
    assert r.status_code == 200, r.text
    return r.json()


def _actionable(c: dict) -> list[dict]:
    return [f for f in c["flags"] if f["severity"] in ("BLOCK", "REVIEW")]


def _decide(client: TestClient, c: dict, approver: str) -> dict:
    """The dashboard's happy path for one position: accept the FIRST suggestion of its first
    actionable flag and name every actionable rule id on the position."""
    flags = _actionable(c)
    first, sugg = flags[0], flags[0]["suggestions"][0]
    r = client.post("/api/overrides", json={
        "company": c["company"], "booked": sugg["booked"], "approver": approver,
        "reason": f"Suggested: {sugg['label']}", "rule_ids_addressed": [f["rule_id"] for f in flags],
        "source_suggestion": f"{first['rule_id']}/{sugg['key']}",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _decide_everything(client: TestClient, approver: str) -> list[str]:
    run = client.get("/api/run").json()
    done = []
    for c in run["companies"]:
        if c["readiness"] == "Ready":
            continue
        after = _decide(client, c, approver)
        assert after["readiness"] == "Ready", (c["company"], after["readiness"], [f["rule_id"] for f in _actionable(after)])
        assert after["approval"] == "Decision recorded"
        done.append(c["company"])
    return done


def _ledger_record(company: str, quarter: str, proposed: float, booked: float, rule_ids: list[str], approver: str = "By Hand") -> dict:
    return {"company": company, "quarter": quarter, "proposed": proposed, "booked": booked, "reason": "hand-written record",
            "approver": approver, "created_at": "2026-10-01", "rule_ids_addressed": rule_ids}


def _months(a: date, b: date) -> float:
    return (b - a).days / 30.4375


# ============================================================================ A. readiness invariants

def _open_flags(c) -> list:
    """The spec's own reading of `unresolved`: an override names what it resolves; one naming
    nothing clears BLOCKs and leaves every REVIEW open; MONITOR is never a gate."""
    addressed = set(c.override.rule_ids_addressed) if c.override else set()
    if c.override and not addressed:
        return [f for f in c.flags if f.severity is Severity.REVIEW]
    return [f for f in c.flags if f.severity is not Severity.MONITOR and f.rule_id not in addressed]


def _provisional_addressed(c) -> bool:
    if not c.override:
        return False
    addressed = set(c.override.rule_ids_addressed)
    treatment = [f.rule_id for f in c.flags if f.family == "treatment"]
    return bool(addressed & set(treatment))


def _is_material(c, cfg: RuleConfig) -> list[str]:
    """Material by the policy's own REVIEW thresholds, for a going concern only: a terminal
    position (Cindral, Larkspell) carries no runway or growth screen by design."""
    if c.status_after.value != "Active":
        return []
    x = cfg.exceptions
    why = []
    if c.runway_months_aged is not None and c.runway_months_aged < x.runway.review_below_mo:
        why.append(f"runway {c.runway_months_aged} < {x.runway.review_below_mo}")
    if c.arr_growth is not None and c.arr_growth < x.arr_growth.review_below:
        why.append(f"arr_growth {c.arr_growth} < {x.arr_growth.review_below}")
    deal_priced = any(i.kind.value == "pending_acquisition" for i in c.open_items)
    if not c.listed and not deal_priced and _months(c.staleness_anchor, cfg.quarter.measurement_date) > x.staleness.review_months:
        why.append(f"round {c.staleness_anchor} is > {x.staleness.review_months} months old")
    return why


def check_readiness_invariants(run: ValuationRun, cfg: RuleConfig) -> None:
    tally = {r.value: 0 for r in Readiness}
    monitors = 0
    for c in run.companies:
        open_flags = _open_flags(c)
        missing = any(f.rule_id in MISSING_INPUT_RULES for f in open_flags)
        blocked = (c.provisional and not _provisional_addressed(c)) or missing
        needs_review = bool(open_flags) and not blocked
        expected = Readiness.BLOCKED if blocked else Readiness.NEEDS_REVIEW if needs_review else Readiness.READY
        assert c.readiness is expected, (c.company, c.readiness, expected, [(f.rule_id, f.severity.value) for f in c.flags], c.override)
        if c.readiness is not Readiness.READY:
            actionable = [f for f in c.flags if f.severity in ACTIONABLE]
            well_formed = [f for f in actionable if f.action and 2 <= len(f.points) <= 3 and len(f.suggestions) >= 1]
            assert well_formed or (c.provisional and c.provisional_reason), \
                (c.company, [(f.rule_id, f.action, len(f.points), len(f.suggestions)) for f in actionable])
        else:
            # nothing material is Ready unless a named decision is on file for it
            assert not _is_material(c, cfg) or c.override is not None, (c.company, _is_material(c, cfg))
            assert not [f for f in open_flags], (c.company, "Ready with an open BLOCK/REVIEW")
        assert c.monitor == any(f.severity is Severity.MONITOR for f in c.flags), c.company
        # approval: a decision on file is "Decision recorded"; the engine never says published
        assert c.approval is (Approval.DECIDED if c.override else Approval.NONE), (c.company, c.approval)
        tally[c.readiness.value] += 1
        monitors += c.monitor
    assert run.totals.readiness == tally
    assert run.totals.monitor_positions == monitors
    # a Blocked position always says what is missing, in words
    for c in run.companies:
        if c.readiness is Readiness.BLOCKED:
            assert c.provisional_reason or any(f.rule_id in MISSING_INPUT_RULES and f.action for f in c.flags), c.company


def test_A_readiness_invariants_hold_on_the_real_run(run_real, cfg):
    check_readiness_invariants(run_real, cfg)
    assert run_real.totals.readiness == {"Blocked": 1, "Needs Review": 26, "Ready": 73}
    d = run_real.by_company()[PROVISIONAL_COMPANY]
    assert d.readiness is Readiness.BLOCKED and d.provisional and "closing price" in (d.provisional_reason or "")


def test_A_real_run_every_material_position_is_held(run_real, cfg):
    """Every going concern past a REVIEW threshold is Needs Review or Blocked — none is Ready."""
    held = []
    for c in run_real.companies:
        why = _is_material(c, cfg)
        if why:
            assert c.readiness is not Readiness.READY, (c.company, why)
            held.append(c.company)
    assert len(held) >= 10, held   # the Q3 book carries plenty of short runways, contractions and stale rounds


_SYNTHETIC: dict[str, tuple[list[dict], list[dict]]] = {
    "clean": ([position()], []),
    "short_runway": ([position(cash=2.0, net_burn=1.0)], []),
    "arr_contraction": ([position(arr_growth=-0.30)], []),
    "stale_round": ([position(latest_round=date(2021, 1, 15), first_investment=date(2020, 1, 1))], []),
    "listed_no_quote": ([position(stage="Public")], []),
    "novel_event": ([position()], [event("SPAC Merger", detail="Business combination", value=500.0, ownership_after=0.03)]),
    "two_reviews_escalate": ([position(cash=2.0, net_burn=1.0, arr_growth=-0.30)], []),
    "mixed_book": ([position(company="Alpha"), position(company="Beta", cash=2.0, net_burn=1.0),
                    position(company="Gamma", stage="Public"), position(company="Delta", arr_growth=-0.5)], []),
}


@pytest.mark.parametrize("case", sorted(_SYNTHETIC))
def test_A_readiness_invariants_hold_on_synthetic_runs(build, cfg, case):
    positions, events = _SYNTHETIC[case]
    run, _ = build(positions, events)
    check_readiness_invariants(run, cfg)
    expected_ready = {"clean": 1, "mixed_book": 1}.get(case, 0)
    assert run.totals.readiness["Ready"] == expected_ready, run.totals.readiness


@pytest.mark.parametrize("rule_ids, expected", [
    ((), Readiness.NEEDS_REVIEW),               # nameless: BLOCKs clear, the REVIEW stays open
    (("X-304",), Readiness.NEEDS_REVIEW),       # names the runway review, not the growth one
    (("X-304", "X-302"), Readiness.READY),      # names both
])
def test_A_readiness_invariants_hold_with_overrides(build, cfg, rule_ids, expected):
    ledger = OverrideLedger(records=(OverrideRecord(
        company="Alpha", quarter=cfg.quarter.label, proposed=10.0, booked=9.0, reason="r", approver="A",
        created_at=date(2026, 9, 30), rule_ids_addressed=rule_ids),))
    run, _ = build([position(cash=2.0, net_burn=1.0, arr_growth=-0.30)], [], overrides=ledger)
    check_readiness_invariants(run, cfg)
    c = only(run)
    assert c.readiness is expected and c.booked_mark == 9.0 and c.approval is Approval.DECIDED


# ============================================================================ B. the publish gate

def test_B_api_publish_refused_while_outstanding_then_opens_and_needs_a_second_name(scratch: RunPaths):
    client = _client(scratch)
    before = client.get("/api/run").json()
    waiting = [c["company"] for c in before["companies"] if c["readiness"] != "Ready"]
    assert len(waiting) == 27 and PROVISIONAL_COMPANY in waiting

    r = client.post("/api/publish", json={"approver": "Tom Moore", "note": "try"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert sorted(i["company"] for i in detail["outstanding"]) == sorted(waiting)
    assert {i["readiness"] for i in detail["outstanding"]} == {"Blocked", "Needs Review"}
    assert all(i["rules"] for i in detail["outstanding"]), "every outstanding position names the flags a person must decide"
    assert not (scratch.root / "data" / "published").exists(), "a refused publish writes nothing"
    assert client.get("/api/exec").status_code == 404

    decided = _decide_everything(client, approver="IC chair")
    assert sorted(decided) == sorted(waiting)
    assert client.get("/api/publish/readiness").json() == {"ready": True, "outstanding": []}

    # four eyes: the person who decided may not release (case- and whitespace-insensitive)
    r = client.post("/api/publish", json={"approver": "  ic CHAIR ", "note": ""})
    assert r.status_code == 409 and r.json()["detail"]["second_approver"] is True, r.text
    assert client.get("/api/exec").status_code == 404

    r = client.post("/api/publish", json={"approver": "Tom Moore", "note": "released"})
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["status"] == "final" and rec["open_blocks"] == [] and rec["published_by"] == "Tom Moore"
    view = client.get("/api/exec").json()
    assert view["meta"]["status"] == "final" and view["meta"]["published_by"] == "Tom Moore"

    # even after a final release the review run never labels a mark "Approved and published":
    # that state exists in the enum and nothing sets it. The exec snapshot's status is the signal.
    after = client.get("/api/run").json()
    assert {c["approval"] for c in after["companies"]} == {"Decision recorded", "Not approved"}
    _, snap = load_published(scratch.root)
    assert all(c.approval is not Approval.PUBLISHED for c in snap.companies)


def test_B_second_approver_switch_lives_in_the_policy(scratch: RunPaths):
    client = _client(scratch)
    _decide_everything(client, approver="IC chair")
    assert client.post("/api/publish", json={"approver": "IC chair"}).status_code == 409
    _edit_policy(scratch.policy, **{"publish.require_second_approver": False})
    client.post("/api/rerun")
    r = client.post("/api/publish", json={"approver": "IC chair"})
    assert r.status_code == 200 and r.json()["status"] == "final", r.text


def test_B_second_approver_is_only_a_name_comparison(scratch: RunPaths):
    """POLICY QUESTION: segregation of duties is enforced on the typed name alone. The same
    person under a different spelling releases their own decisions."""
    client = _client(scratch)
    _decide_everything(client, approver="Jackson Lagerwey")
    assert client.post("/api/publish", json={"approver": "jackson  lagerwey"}).status_code == 409
    r = client.post("/api/publish", json={"approver": "J. Lagerwey"})
    assert r.status_code == 200 and r.json()["published_by"] == "J. Lagerwey"


@pytest.fixture()
def cli(scratch: RunPaths, monkeypatch):
    """`hc-valuation` resolves its root from the installed package; point it at the scratch copy
    so the CLI reads the scratch ledger and writes the scratch publish directory."""
    import hc_valuation.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "repo_root", lambda: scratch.root)
    monkeypatch.delenv("HC_MARKET_PROVIDER", raising=False)
    monkeypatch.delenv("HC_LEDGER_DIR", raising=False)     # the scratch root's data/ is the ledger here
    runner = CliRunner()

    def invoke(*args: str):
        return runner.invoke(cli_app, ["publish", "--input", str(scratch.workbook), "--policy", str(scratch.policy), *args])
    return invoke


def test_B_cli_publish_exits_non_zero_while_outstanding(scratch: RunPaths, cli):
    repo_snapshots = sorted(p.name for p in (ROOT / "data" / "published").rglob("*"))
    r = cli("--approver", "Tom Moore")
    assert r.exit_code != 0, r.output
    assert "refused" in r.output and "27 position(s)" in r.output
    assert not (scratch.root / "data" / "published").exists()
    assert sorted(p.name for p in (ROOT / "data" / "published").rglob("*")) == repo_snapshots   # the repo's own ledger untouched


def test_B_cli_proposed_publish_is_recorded_as_proposed_everywhere(scratch: RunPaths, cli):
    r = cli("--approver", "Tom Moore", "--proposed", "--note", "preview")
    assert r.exit_code == 0, r.output
    assert "as PROPOSED" in r.output and "27 position(s) not ready, 1 blocked" in r.output
    rec, snap = load_published(scratch.root)
    assert rec["status"] == "proposed" and len(rec["open_positions"]) == 27 and rec["open_blocks"] == ["Drayvenn"]
    assert rec["status"] != "final"
    view = exec_payload(scratch.root)
    assert view["meta"]["status"] == "proposed"
    assert view["history"][0]["status"] == "proposed"
    # the frozen run carries its open findings and no per-company approval beyond "Not approved"
    assert snap.totals.readiness == {"Blocked": 1, "Needs Review": 26, "Ready": 73}
    assert {c.approval for c in snap.companies} == {Approval.NONE}
    assert view["decisions"], "the executive view still lists the undecided BLOCK positions"


def test_B_proposed_publish_of_an_all_review_book_is_still_proposed(build, tmp_path: Path):
    """A `--proposed` release of a book whose only open items are REVIEW findings (readiness
    Needs Review) is recorded as proposed. (Fixed: `publish_run` used to derive `status` from
    disposition == BLOCK only, so a Needs-Review book bypassed with require_decisions=False was
    written as final, and the executive view then said final.)"""
    run, _ = build([position(company="Alpha", cash=2.0, net_burn=1.0), position(company="Beta", arr_growth=-0.3)], [])
    assert run.totals.readiness == {"Blocked": 0, "Needs Review": 2, "Ready": 0}
    with pytest.raises(PublishBlocked):
        publish_run(run, tmp_path, approver="Tom Moore")
    rec = publish_run(run, tmp_path, approver="Tom Moore", require_decisions=False)
    view = build_exec_view(run, rec)
    assert view["meta"]["status"] == rec["status"] == "proposed"
    assert rec["open_positions"] == ["Alpha", "Beta"] and rec["open_blocks"] == []


def test_B_proposed_status_follows_readiness(build, tmp_path: Path):
    """Fixed defect: a book with one Needs-Review position releases as proposed, not final."""
    run, _ = build([position(company="Alpha", cash=2.0, net_burn=1.0)], [])
    rec = publish_run(run, tmp_path, approver="Tom Moore", require_decisions=False)
    assert rec["status"] == "proposed"


def test_B_publish_gate_keys_on_readiness_not_on_disposition(run_real):
    """A Needs-Review position whose disposition is BLOCK (two REVIEW families escalated) and a
    Blocked position with a REVIEW disposition are both outstanding: the gate reads readiness."""
    from hc_valuation.api.publish import outstanding
    items = {i["company"]: i for i in outstanding(run_real)}
    by = run_real.by_company()
    assert set(items) == {c.company for c in run_real.companies if c.readiness is not Readiness.READY}
    escalated = [n for n, i in items.items() if i["disposition"] == "BLOCK" and i["readiness"] == "Needs Review"]
    assert "Pellagrin" in escalated and all(not by[n].provisional for n in escalated)
    assert items[PROVISIONAL_COMPANY]["readiness"] == "Blocked" and "closing price" in items[PROVISIONAL_COMPANY]["why"]


# ============================================================================ C. override controls

def test_C1_override_naming_a_monitor_rule_leaves_the_review_open(scratch: RunPaths):
    client = _client(scratch)
    b = _company(client, "Beltrix")
    assert [(f["rule_id"], f["severity"]) for f in b["flags"]] == [("X-201", "MONITOR"), ("X-304", "REVIEW")]
    r = client.post("/api/overrides", json={"company": "Beltrix", "booked": b["proposed_mark"], "approver": "A",
                                            "reason": "acknowledged the round age", "rule_ids_addressed": ["X-201"]})
    assert r.status_code == 200, r.text          # X-201 is on the position, so the server accepts the record
    c = r.json()
    assert c["readiness"] == "Needs Review" and c["disposition"] == "REVIEW" and c["approval"] == "Decision recorded"
    assert client.post("/api/publish", json={"approver": "Tom Moore"}).status_code == 409


def test_C2_empty_rule_ids_refused_by_the_api_and_a_hand_written_one_clears_blocks_only(scratch: RunPaths):
    client = _client(scratch)
    for name in ("Beltrix", "Pellagrin", "Tarnwick Aerospace", PROVISIONAL_COMPANY):
        c = _company(client, name)
        r = client.post("/api/overrides", json={"company": name, "booked": c["proposed_mark"], "approver": "A",
                                                "reason": "blanket", "rule_ids_addressed": []})
        assert r.status_code == 422 and "must name the flag" in r.json()["detail"]["message"], (name, r.text)
        assert _company(client, name)["override"] is None
    # the ledger has no such check: written by hand, [] clears the BLOCK (X-102) but not the REVIEW (X-302)
    t = _company(client, "Tarnwick Aerospace")
    append_override(scratch.overrides, _ledger_record("Tarnwick Aerospace", "Q3 2026", t["proposed_mark"], t["proposed_mark"], []))
    client.post("/api/rerun")
    t2 = _company(client, "Tarnwick Aerospace")
    assert t2["override"]["rule_ids_addressed"] == [] and t2["disposition"] == "REVIEW"
    assert t2["readiness"] == "Needs Review" and t2["approval"] == "Decision recorded"


def test_C2_hand_written_empty_override_on_a_missing_input_block(build, cfg):
    """A ledger record naming no rule id books its number but leaves a listed-with-no-quote
    position (X-113, a MISSING_INPUT rule) Blocked — the same way a nameless record leaves
    Drayvenn's provisional stand-in Blocked. (Fixed: it used to clear every BLOCK.)"""
    run, _ = build([position(stage="Public")], [])
    c = only(run)
    assert c.readiness is Readiness.BLOCKED and [f.rule_id for f in c.flags] == ["X-113"]
    ledger = OverrideLedger(records=(OverrideRecord(company="Alpha", quarter=cfg.quarter.label, proposed=c.proposed_mark,
                                                    booked=7.0, reason="r", approver="A", created_at=date(2026, 9, 30)),))
    run2, _ = build([position(stage="Public")], [], overrides=ledger)
    assert only(run2).readiness is Readiness.BLOCKED and only(run2).booked_mark == 7.0
    # naming the missing-input rule is what moves it on: a person has seen what is missing
    named = OverrideLedger(records=(OverrideRecord(company="Alpha", quarter=cfg.quarter.label, proposed=c.proposed_mark,
                                                   booked=7.0, reason="r", approver="A", created_at=date(2026, 9, 30),
                                                   rule_ids_addressed=("X-113",)),))
    run3, _ = build([position(stage="Public")], [], overrides=named)
    assert only(run3).readiness is Readiness.READY


def test_C2_nameless_override_does_not_clear_a_missing_input_block(build, cfg):
    ledger = OverrideLedger(records=(OverrideRecord(company="Alpha", quarter=cfg.quarter.label, proposed=10.0,
                                                    booked=7.0, reason="r", approver="A", created_at=date(2026, 9, 30)),))
    run, _ = build([position(stage="Public")], [], overrides=ledger)
    assert only(run).readiness is Readiness.BLOCKED


def test_C3_provisional_position_stays_blocked_until_its_rule_is_named(scratch: RunPaths):
    client = _client(scratch)
    d = _company(client, PROVISIONAL_COMPANY)
    assert d["readiness"] == "Blocked" and d["provisional"] and [f["rule_id"] for f in d["flags"]] == ["X-101"]
    # the API cannot record a decision on Drayvenn that does not name X-101 (its only flag) ...
    for ids in ([], ["X-201"]):
        r = client.post("/api/overrides", json={"company": PROVISIONAL_COMPANY, "booked": d["proposed_mark"], "approver": "A",
                                                "reason": "r", "rule_ids_addressed": ids})
        assert r.status_code == 422, (ids, r.text)
    # ... and a hand-written record that names nothing leaves the stand-in Blocked
    append_override(scratch.overrides, _ledger_record(PROVISIONAL_COMPANY, "Q3 2026", d["proposed_mark"], 100.0, []))
    client.post("/api/rerun")
    d2 = _company(client, PROVISIONAL_COMPANY)
    assert d2["override"] is not None and d2["readiness"] == "Blocked" and d2["booked_mark"] == 100.0
    assert d2["approval"] == "Decision recorded"          # a decision is on file, and it still cannot be booked
    assert any(i["company"] == PROVISIONAL_COMPANY for i in client.get("/api/publish/readiness").json()["outstanding"])
    # naming X-101 accepts the stand-in knowingly: Ready, decision recorded
    price = next(s for f in d["flags"] for s in f["suggestions"])
    r = client.post("/api/overrides", json={"company": PROVISIONAL_COMPANY, "booked": price["booked"], "approver": "IC chair",
                                            "reason": "stand-in accepted pending the close", "rule_ids_addressed": ["X-101"],
                                            "source_suggestion": f"X-101/{price['key']}"})
    assert r.status_code == 200, r.text
    d3 = r.json()
    assert d3["readiness"] == "Ready" and d3["approval"] == "Decision recorded" and d3["provisional"] is True
    assert d3["booked_mark"] == pytest.approx(price["booked"])


def test_C4_policy_drift_after_an_override_reopens_the_review_and_keeps_the_booked_figure(scratch: RunPaths):
    client = _client(scratch)
    g = _company(client, "Gryphonel")
    full = next(s for f in g["flags"] if f["rule_id"] == "X-101" for s in f["suggestions"] if s["key"] == "full_value")
    r = client.post("/api/overrides", json={"company": "Gryphonel", "booked": full["booked"], "approver": "IC chair",
                                            "reason": "book the signed deal", "rule_ids_addressed": ["X-101"],
                                            "source_suggestion": "X-101/full_value"})
    assert r.status_code == 200 and r.json()["readiness"] == "Ready", r.text
    proposed_before = g["proposed_mark"]

    # the announced-deal probability moves: the proposal Gryphonel's decision was measured against moves with it
    _edit_policy(scratch.policy, **{"marking.announced.close_probability": 0.80})
    client.post("/api/rerun")
    g2 = _company(client, "Gryphonel")
    assert g2["proposed_mark"] != pytest.approx(proposed_before)
    drift = next(f for f in g2["flags"] if f["rule_id"] == "E-01")
    assert drift["severity"] == "REVIEW" and "booked figure stands" in drift["message"]
    assert g2["readiness"] == "Needs Review" and g2["approval"] == "Decision recorded"
    assert g2["booked_mark"] == pytest.approx(full["booked"])          # the human decision is not overwritten
    assert g2["override"]["proposed"] == pytest.approx(proposed_before)  # ... and the record says what it was measured against
    r = client.post("/api/publish", json={"approver": "Tom Moore"})
    assert r.status_code == 409 and [i["company"] for i in r.json()["detail"]["outstanding"] if i["company"] == "Gryphonel"]
    # re-confirming against the new proposal names E-01 and closes it again
    r = client.post("/api/overrides", json={"company": "Gryphonel", "booked": full["booked"], "approver": "IC chair",
                                            "reason": "re-confirmed", "rule_ids_addressed": ["X-101", "E-01"],
                                            "source_suggestion": "E-01/reconfirm"})
    assert r.status_code == 200 and r.json()["readiness"] == "Ready", r.text
    assert not any(f["rule_id"] == "E-01" and f["severity"] == "REVIEW" for f in r.json()["flags"])


def test_C5_override_cannot_address_a_rule_that_is_not_on_the_position(scratch: RunPaths):
    client = _client(scratch)
    o = _company(client, "Ostrella")
    assert [f["rule_id"] for f in o["flags"]] == ["X-202"]
    for ids in (["X-304"], ["X-202", "X-304"], ["E-01"], ["M-999"], ["x-202"]):
        r = client.post("/api/overrides", json={"company": "Ostrella", "booked": o["proposed_mark"], "approver": "A",
                                                "reason": "r", "rule_ids_addressed": ids})
        assert r.status_code == 422, (ids, r.text)
        assert "not a flag on Ostrella" in r.json()["detail"]["message"] and r.json()["detail"]["flags"] == ["X-202"]
    assert _company(client, "Ostrella")["override"] is None
    assert not yaml.safe_load(scratch.overrides.read_text())["overrides"]


def test_C6_booked_has_no_server_side_sanity_bound(scratch: RunPaths):
    """Observed: any float is accepted as the booked mark. A $1,000,000M mark on a $5M
    position books, clears the flag and is Ready. Drift (E-01) does not catch it either — the
    override records the proposal it was measured against, not the size of the departure."""
    client = _client(scratch)
    b = _company(client, "Beltrix")
    r = client.post("/api/overrides", json={"company": "Beltrix", "booked": 1e6, "approver": "A", "reason": "fat finger",
                                            "rule_ids_addressed": ["X-304"], "source_suggestion": "X-304/manual"})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["booked_mark"] == 1e6 and c["readiness"] == "Ready" and c["approval"] == "Decision recorded"
    assert not any(f["rule_id"] == "E-01" for f in c["flags"])
    run = client.get("/api/run").json()
    assert run["totals"]["booked_nav"] > 1e6 and run["totals"]["proposed_nav"] < 2e3
    assert c["override"]["booked"] == 1e6 and c["override"]["proposed"] == pytest.approx(b["proposed_mark"])
    # the size of the departure is visible on the record and in the bridge; it is not a gate
    view = build_exec_view(ValuationRun.model_validate(run), {})
    assert any(bar["key"] == "overrides" for bar in view["bridge"])


def test_C6_negative_booked_is_refused(scratch: RunPaths):
    client = _client(scratch)
    r = client.post("/api/overrides", json={"company": "Umberly", "booked": -5.0, "approver": "A", "reason": "typo",
                                            "rule_ids_addressed": ["X-304"]})
    assert r.status_code == 422, r.text


def test_C6_zero_booked_is_a_write_off_and_allowed(scratch: RunPaths):
    client = _client(scratch)
    r = client.post("/api/overrides", json={"company": "Umberly", "booked": 0.0, "approver": "A", "reason": "written off",
                                            "rule_ids_addressed": ["X-304"]})
    assert r.status_code == 200 and r.json()["booked_mark"] == 0.0


def test_C7_override_on_a_clean_position_needs_no_rule_id(scratch: RunPaths):
    """POLICY QUESTION: a position with no flags takes a custom override with an empty
    rule_ids_addressed, moves its booked mark, stays Ready, and only the bridge and the
    `overridden` marker say so. Here: a fully exited position re-marked to a positive figure."""
    client = _client(scratch)
    cindral = _company(client, "Cindral")
    assert cindral["readiness"] == "Ready" and cindral["flags"] == [] and cindral["booked_mark"] == 0.0
    r = client.post("/api/overrides", json={"company": "Cindral", "booked": 12.5, "approver": "A", "reason": "escrow receivable?",
                                            "rule_ids_addressed": []})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["readiness"] == "Ready" and c["booked_mark"] == 12.5 and c["status_after"] == "Acquired"
    assert c["approval"] == "Decision recorded" and c["override"]["rule_ids_addressed"] == []
    assert client.post("/api/publish", json={"approver": "Tom Moore"}).status_code == 409   # the rest of the book still waits


# ============================================================================ D. AI cannot bypass

class _Fake(ClaudeChooser):
    """The network call replaced by a canned reply (or an exception)."""
    def __init__(self, cache_dir: Path, reply: str | Exception):
        super().__init__(cache_dir, api_key="test-key")
        self.reply = reply

    def _call(self, brief):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _reply(choice: str, **extra: Any) -> str:
    return json.dumps({"choice": choice, "label": "Take this one.", "reasons": ["because", "and because"],
                       "rationale": "the brief says so", "confidence": 0.99, **extra})


def _multi_choice(run: ValuationRun):
    for c in run.companies:
        for f in c.flags:
            if f.severity in ACTIONABLE and len(f.suggestions) >= 2:
                return c, f
    raise AssertionError("no flag with two candidates")


def test_D1_choice_outside_the_candidates_falls_back_to_policy_and_says_so(run_real, tmp_path: Path):
    c, f = _multi_choice(run_real)
    for bogus in ("write_up_to_1e9", "", None, 42):
        ch = _Fake(tmp_path / "rec", _reply(bogus))
        rec = ch.choose(build_brief(c, f, run_real), f)
        assert rec.source == "policy" and rec.key == f.suggestions[0].key and rec.booked == f.suggestions[0].booked
        assert rec.note and "not a candidate" in rec.note and rec.model is None and rec.confidence is None, rec
        assert ch.fallbacks and not list((tmp_path / "rec").glob("*.json")), "a rejected reply is never cached"


def test_D2_the_reply_cannot_price(run_real, tmp_path: Path):
    c, f = _multi_choice(run_real)
    other = f.suggestions[1]
    brief = build_brief(c, f, run_real)
    # a reply that smuggles its own number is rejected outright (extra key) and the policy default stands
    ch = _Fake(tmp_path / "a", _reply(other.key, booked=other.booked * 10, booked_musd=1e9))
    rec = ch.choose(brief, f)
    assert rec.source == "policy" and rec.booked == f.suggestions[0].booked and "reply keys" in (rec.note or "")
    # a valid choice whose wording claims a different number books the CANDIDATE's number
    ch = _Fake(tmp_path / "b", json.dumps({"choice": other.key, "label": "Book this at $999,999.00M today.",
                                           "reasons": ["Worth $999,999M.", "Trust me."],
                                           "rationale": "book 999999", "confidence": 0.99}))
    rec = ch.choose(brief, f)
    assert rec.source == "claude" and rec.key == other.key and rec.confidence == 0.99
    assert rec.booked == other.booked and rec.booked != 999999.0
    assert "999,999" in rec.label                      # the words are the model's, the number is the engine's


def test_D3_malformed_reply_or_exception_falls_back_without_raising(run_real, tmp_path: Path):
    c, f = _multi_choice(run_real)
    brief = build_brief(c, f, run_real)
    cases = {
        "not json": "I would choose the first one.",
        "json list": json.dumps([{"choice": f.suggestions[1].key}]),
        "fenced garbage": "```json\n{'choice': 'x'}\n```",
        "missing keys": json.dumps({"choice": f.suggestions[1].key}),
        "confidence > 1": _reply(f.suggestions[1].key).replace("0.99", "1.5"),
        "exception": RuntimeError("socket closed"),
        "timeout-shaped": TimeoutError("read timed out"),
    }
    for name, reply in cases.items():
        ch = _Fake(tmp_path / name.replace(" ", "_"), reply)
        rec = ch.choose(brief, f)                  # never raises
        assert rec.source == "policy" and rec.key == f.suggestions[0].key, (name, rec)
        assert rec.note and "policy default" in rec.note, (name, rec.note)
    # and through the run: every flag still carries one recommendation, the run is intact
    ch = _Fake(tmp_path / "run", RuntimeError("down"))
    out = recommend_run(run_real, ch, None)
    assert out.manifest.recommender == f"claude:{ch.model}"
    for c2 in out.companies:
        for g in c2.flags:
            if g.severity in ACTIONABLE and g.suggestions:
                assert g.recommendation is not None and g.recommendation.source == "policy"


class _Hostile:
    """A chooser that ignores the candidates entirely and returns a made-up recommendation with a
    made-up number — the worst thing the seam could hand back."""
    name = "claude"
    model = "hostile"

    def choose(self, brief, f) -> Recommendation:
        return Recommendation(key="write_up", label="Write it up.", reasons=("a", "b"), booked=9.99e9, source="claude",
                              model=self.model, rationale="because", confidence=1.0)

    def choose_position(self, brief, c) -> PositionRecommendation:
        # names a finding that is not on the position, a key that does not exist, and a wild number
        return PositionRecommendation(rule_id="X-999", key="write_up", label="Write the whole book up.",
                                      reasons=("a", "b"), booked=9.99e9, covers=("X-999",), source="claude",
                                      model=self.model, rationale="because", confidence=1.0)


def test_D4_the_recommender_runs_after_the_engine_and_reaches_nothing(run_real):
    before = json.loads(run_real.model_dump_json())
    after_run = recommend_run(run_real, _Hostile(), None)
    after = json.loads(after_run.model_dump_json())
    # the manifest labels the chooser by its class, not by what it returned: a foreign chooser reads as "policy"
    # the label is derived from the chooser's class, not its self-declared name: a hostile object
    # claiming to be claude is labelled policy, so the manifest cannot be spoofed either
    assert after_run.manifest.recommender == "policy"
    n = 0
    for a, b in zip(before["companies"], after["companies"]):
        for key in ("proposed_mark", "booked_mark", "readiness", "disposition", "approval", "provisional", "steps", "override", "monitor"):
            assert a[key] == b[key], (a["company"], key)
        assert [(f["rule_id"], f["severity"], f["action"], f["suggestions"]) for f in a["flags"]] == \
               [(f["rule_id"], f["severity"], f["action"], f["suggestions"]) for f in b["flags"]]
        for f in b["flags"]:
            if f["severity"] != "MONITOR" and f["suggestions"]:
                assert f["recommendation"]["booked"] == 9.99e9    # it is displayed ...
                n += 1
    assert n > 20
    assert after["totals"] == before["totals"]                   # ... and reaches no total
    assert after["rollups"] == before["rollups"]
    # and the pipeline order is fixed: the engine has no notion of a recommender at all
    import inspect
    from hc_valuation.engine import run as engine_run
    src = inspect.getsource(engine_run)
    assert "recommend" not in src and "anthropic" not in src


def test_D4_accepting_a_recommendation_is_an_ordinary_named_override(scratch: RunPaths):
    """Even a recommendation is only a menu item: booking it takes a named approver and a reason,
    and the server checks both."""
    client = _client(scratch)
    b = _company(client, "Beltrix")
    rec = next(f["recommendation"] for f in b["flags"] if f["rule_id"] == "X-304")
    assert rec["source"] == "policy" and rec["booked"] == pytest.approx(b["flags"][1]["suggestions"][0]["booked"])
    for body in ({"approver": "", "reason": "r"}, {"approver": "IC", "reason": ""}, {"approver": " ", "reason": "r"}, {}):
        r = client.post("/api/overrides", json={"company": "Beltrix", "booked": rec["booked"], "rule_ids_addressed": ["X-304"],
                                                "source_suggestion": f"X-304/{rec['key']}", **body})
        assert r.status_code == 422, (body, r.text)
    assert _company(client, "Beltrix")["readiness"] == "Needs Review"


def _spac_paths(tmp_path: Path, cfg_edit: dict[str, Any] | None = None) -> RunPaths:
    (tmp_path / "rules").mkdir()
    shutil.copy(ROOT / "rules" / "2026Q3.yaml", tmp_path / "rules" / "2026Q3.yaml")
    if cfg_edit:
        _edit_policy(tmp_path / "rules" / "2026Q3.yaml", **cfg_edit)
    wb = make_workbook(tmp_path, [position()], [event("SPAC Merger", detail="Business combination", value=500.0, ownership_after=0.03)])
    return RunPaths(root=tmp_path, policy=tmp_path / "rules" / "2026Q3.yaml", workbook=wb,
                    overrides=tmp_path / "overrides.yaml", proposals_dir=tmp_path / "proposals",
                    precedent=tmp_path / "precedent.yaml", open_items_carry=tmp_path / "carry.yaml")


def test_D5_adjudication_confidence_gates_nothing(tmp_path: Path, cfg):
    """fixed: an unhandled event type is a missing input (M-999 in MISSING_INPUT_RULES), so the
    position is Blocked and carries at the prior mark until a named decision is booked."""
    paths = _spac_paths(tmp_path)
    r = execute(paths, generated_at=GENERATED_AT)
    c = only(r.run)
    assert c.readiness is Readiness.BLOCKED and c.disposition.value == "BLOCK" and c.booked_mark == c.proposed_mark == 10.0
    assert len(r.proposals) == 1 and r.proposals[0].status == "pending"
    # a proposal at 0.99 confidence is still pending: there is no auto-accept, and the policy cannot enable one
    with validation_scope(r.config, build_registry(r.config)):
        prov = Provenance(model="test", prompt_sha256="0" * 64,
                          catalogue_version=catalogue_version_for(r.config.policy_version, build_registry(r.config)),
                          created_at=GENERATED_AT)
        p = TreatmentProposal(event_signature="spac merger", event_type="SPAC Merger", company="Alpha", event_row_index=2,
                              quarter_label=cfg.quarter.label, proposed_mark_at_proposal=10.0, analogue_rule_id="M-040",
                              proposed_kind="reuse", formula="ownership_after * deal_value", parameter_map={},
                              suggested_severity=Severity.BLOCK, rationale="like an IPO", missing_facts=["closing market cap"],
                              confidence=0.99, provenance=prov)
    assert p.status == "pending" and p.decision is None
    with pytest.raises(Exception):
        with_policy(cfg, **{"adjudication.auto_accept": "always"})
    with pytest.raises(Exception):
        with_policy(cfg, **{"adjudication.auto_accept": "above_confidence"})
    # decisions need a named approver
    pid = r.proposals[0].proposal_id
    for who in ("", "   "):
        with pytest.raises(ValueError, match="named approver"):
            record_decision(paths, pid, "accept_once", approver=who, reason="x", booked=15.0)
    assert not paths.overrides.exists() and not paths.precedent.exists()
    assert load_proposal(proposal_path(paths.proposals_dir, pid), r.config).status == "pending"


def test_D5_tampered_proposal_file_books_nothing(tmp_path: Path):
    """Editing the cached proposal to say `accepted_once` by hand changes what the proposals
    endpoint reports and nothing else: only the override ledger books, and only through a decision."""
    paths = _spac_paths(tmp_path)
    r = execute(paths, generated_at=GENERATED_AT)
    path = proposal_path(paths.proposals_dir, r.proposals[0].proposal_id)
    raw = json.loads(path.read_text())
    raw["status"] = "accepted_once"
    raw["decision"] = {"decision": "accept_once", "approver": "nobody", "booked": 15.0}
    raw["confidence"] = 1.0
    path.write_text(json.dumps(raw))
    r2 = execute(paths, generated_at=GENERATED_AT)
    assert r2.proposals[0].status == "accepted_once"     # the file says so ...
    c = only(r2.run)
    assert c.booked_mark == 10.0 and c.override is None and c.readiness is Readiness.BLOCKED   # ... the book does not
    assert any(f.rule_id == "M-999" for f in c.flags) and c.approval is Approval.NONE
    assert not paths.overrides.exists()


def test_D5_decision_api_refuses_a_blank_approver(tmp_path: Path):
    paths = _spac_paths(tmp_path)
    client = TestClient(create_app(paths, static_dir=tmp_path / "no-static"))
    pid = client.get("/api/proposals").json()[0]["proposal_id"]
    r = client.post(f"/api/proposals/{pid}/decision", json={"decision": "accept_once", "approver": "", "booked": 15.0})
    assert r.status_code == 422
    r = client.post(f"/api/proposals/{pid}/decision", json={"decision": "accept_once", "approver": "   ", "booked": 15.0})
    assert r.status_code == 400 and "named approver" in r.text
    r = client.post(f"/api/proposals/{pid}/decision", json={"decision": "auto", "approver": "IC", "booked": 15.0})
    assert r.status_code == 400
    assert _company(client, "Alpha")["booked_mark"] == 10.0 and _company(client, "Alpha")["override"] is None
    # test_edge_cases::test_custom_rule_not_yet_effective_falls_back_to_m999 covers the future effective_from case


# ============================================================================ E. silent-approval hunt

def test_E_approved_and_published_is_unreachable_for_an_open_position(scratch: RunPaths, cli):
    """The one approval state that says "published" is never produced by the engine, the API or a
    snapshot: not by `--proposed`, not by a re-run after a snapshot exists, not by a decision."""
    assert cli("--approver", "Tom Moore", "--proposed").exit_code == 0
    rec, snap = load_published(scratch.root)
    assert rec["status"] == "proposed"
    assert all(c.approval is Approval.NONE for c in snap.companies)
    client = _client(scratch)          # a later run with the proposed snapshot on disk
    run = client.get("/api/run").json()
    assert {c["approval"] for c in run["companies"]} == {"Not approved"}
    assert {c["readiness"] for c in run["companies"] if c["company"] in rec["open_blocks"]} <= {"Blocked", "Needs Review"}
    _decide(client, _company(client, "Beltrix"), "IC chair")
    assert _company(client, "Beltrix")["approval"] == "Decision recorded"
    # a snapshot cannot be re-read into a run as an approval: the loader only reads the ledger
    import inspect
    from hc_valuation import pipeline
    assert "published" not in inspect.getsource(pipeline.execute)
    # the exec view of the proposed snapshot never calls itself final
    assert exec_payload(scratch.root)["meta"]["status"] == "proposed"


def test_E_override_for_another_quarter_is_ignored(scratch: RunPaths):
    client = _client(scratch)
    b = _company(client, "Beltrix")
    for quarter in ("Q2 2026", "Q4 2026", "2026Q3", "q3 2026", "Q3 2026 "):
        append_override(scratch.overrides, _ledger_record("Beltrix", quarter, b["proposed_mark"], 1.0, ["X-304"]))
    client.post("/api/rerun")
    b2 = _company(client, "Beltrix")
    assert b2["override"] is None and b2["readiness"] == "Needs Review" and b2["approval"] == "Not approved"
    assert b2["booked_mark"] == pytest.approx(b["proposed_mark"])
    assert len(yaml.safe_load(scratch.overrides.read_text())["overrides"]) == 5   # on file, not in force


def test_E_history_tags_a_proposed_snapshot_as_published(scratch: RunPaths, cli):
    """POLICY QUESTION: the archive's `published` source label carries no proposed/final status.
    After `--proposed`, every current-quarter point reads `source: published` while the
    position is still Blocked or Needs Review in the same point."""
    assert cli("--approver", "Tom Moore", "--proposed").exit_code == 0
    r = execute(scratch, adjudicate=False)
    hist = build_history(r.run, scratch.root)
    pt = hist["companies"]["Beltrix"][-1]
    assert pt["quarter"] == "Q3 2026" and pt["source"] == "published" and pt["disposition"] == "REVIEW"
    assert pt["status"] == "Active"                       # the company's status; the point has no publish status
    assert not {k for k in pt if "proposed" in k or "final" in k or "publish_status" in k}
    assert hist["counts"]["published"] == 100


def test_E_a_final_snapshot_does_not_survive_a_later_decision_unnoticed(scratch: RunPaths):
    """Publish final, then change a decision: the live run's id moves, the archive says the
    published mark and the live mark disagree, and the executives' snapshot is unchanged."""
    client = _client(scratch)
    _decide_everything(client, approver="IC chair")
    rec = client.post("/api/publish", json={"approver": "Tom Moore"}).json()
    assert rec["status"] == "final"
    b = _company(client, "Beltrix")
    r = client.post("/api/overrides", json={"company": "Beltrix", "booked": b["booked_mark"] * 0.5, "approver": "IC chair",
                                            "reason": "second thoughts", "rule_ids_addressed": ["X-304"]})
    assert r.status_code == 200
    run = client.get("/api/run").json()
    assert run["manifest"]["run_id"] != rec["run_id"]
    pt = client.get("/api/history").json()["companies"]["Beltrix"][-1]
    assert pt["source"] == "live" and "has not been re-published" in pt["note"]
    assert client.get("/api/exec").json()["meta"]["run_id"] == rec["run_id"]
    # and the second-approver check still binds on the re-release
    assert client.post("/api/publish", json={"approver": "IC chair"}).status_code == 409


def test_E_novel_event_block_reads_as_blocked(build):
    """fixed: an unhandled event type (X-909 / M-999, severity BLOCK) is a missing treatment;
    M-999 is now in MISSING_INPUT_RULES, so the position reads Blocked with a disposition of
    BLOCK, and the M-999 flag says in words what is missing."""
    run, issues = build([position()], [event("SPAC Merger", detail="Business combination", value=500.0, ownership_after=0.03)])
    c = only(run)
    assert [i.rule_id for i in issues] == ["X-909"] and issues[0].blocking
    assert "M-999" in MISSING_INPUT_RULES
    assert c.readiness is Readiness.BLOCKED and c.disposition.value == "BLOCK"
    m999 = next(f for f in c.flags if f.rule_id == "M-999")
    assert m999.severity is Severity.BLOCK and m999.action
    assert c.proposed_mark == c.prior_mark == 10.0


# ============================================================================ F. the position-level step

def _step_reply(**over: Any) -> str:
    body = {"rule_id": "X-304", "choice": "to_cost", "label": "Mark down to cost pending the raise.",
            "reasons": ["Three months of cash.", "Cost is a defensible floor."], "covers": ["X-304"],
            "rationale": "Runway first: the round that saves it may reprice below this mark.", "confidence": 0.7}
    body.update(over)
    return json.dumps(body)


def _umberly(run_real: ValuationRun):
    return next(c for c in run_real.companies if c.company == "Umberly")


def _chooser(tmp_path: Path, reply: str) -> ClaudeChooser:
    ch = ClaudeChooser(tmp_path / "rec", model="test-model", api_key="k", use_cache=False)
    ch._call = lambda brief, system=None: reply          # the SDK seam
    return ch


def test_F_one_step_per_position_not_one_per_flag(run_real, tmp_path: Path):
    """The card asks for one next step. The chooser sees every actionable finding at once and
    picks the finding to lead with, not a step per flag."""
    c = _umberly(run_real)
    assert {f.rule_id for f in c.flags} >= {"X-201", "X-304"}
    brief = build_position_brief(c, run_real)
    assert [f["rule_id"] for f in brief["findings"]] == ["X-304"], "MONITOR findings are not steps"
    assert brief["findings"][0]["candidates"], "every actionable finding arrives with its priced options"
    assert "flag" not in brief and "candidates" not in brief, "the per-flag framing is gone"
    step = _chooser(tmp_path, _step_reply()).choose_position(brief, c)
    assert step.rule_id == "X-304" and step.key == "to_cost" and step.source == "claude"
    assert step.covers == ("X-304",) and step.confidence == 0.7


def test_F_a_missing_input_leads_and_the_prompt_says_so(run_real, tmp_path: Path):
    """Drayvenn's mark stands in for a price nobody fetched. Whatever else is on the position,
    the finding that says an input is missing is the one presented first."""
    d = next(c for c in run_real.companies if c.company == PROVISIONAL_COMPANY)
    brief = build_position_brief(d, run_real)
    assert brief["findings"][0]["rule_id"] == "X-101"
    assert brief["findings"][0]["blocks_for_a_missing_input"] is True
    assert "A missing input outranks a judgment" in POSITION_PROMPT


@pytest.mark.parametrize("bad, why", [
    ({"rule_id": "X-999"}, "a finding that is not on the position"),
    ({"rule_id": "X-201"}, "a MONITOR finding, which carries no priced option"),
    ({"choice": "write_up"}, "a candidate key that does not exist"),
    ({"covers": ["X-304", "X-777"]}, "covers naming a finding that is not actionable here"),
    ({"confidence": 1.7}, "confidence outside [0, 1]"),
    ({"label": "x" * 200}, "a label that does not fit the card"),
])
def test_F_a_step_that_does_not_fit_the_position_falls_back_to_policy(run_real, tmp_path: Path, bad: dict, why: str):
    c = _umberly(run_real)
    ch = _chooser(tmp_path, _step_reply(**bad))
    step = ch.choose_position(build_position_brief(c, run_real), c)
    assert step.source == "policy", why
    assert step.rule_id == "X-304" and step.note and "claude unavailable" in step.note
    assert ch.fallbacks and "Umberly (position)" in ch.fallbacks[0]


def test_F_the_number_always_comes_from_the_engines_candidate(run_real, tmp_path: Path):
    """A reply carrying its own figure cannot smuggle it in: `booked` is read off the named
    suggestion, and the reply has no field for a number at all."""
    c = _umberly(run_real)
    priced = {s.key: s.booked for f in c.flags if f.rule_id == "X-304" for s in f.suggestions}
    step = _chooser(tmp_path, _step_reply()).choose_position(build_position_brief(c, run_real), c)
    assert step.booked == priced["to_cost"]
    with pytest.raises(ValueError, match="reply keys"):
        ClaudeChooser.parse_position(_step_reply(booked=9.99e9), c)


def test_F_covers_may_name_several_findings_and_is_validated(run_real, tmp_path: Path):
    """A step that genuinely settles more than one finding may say so — but only findings that
    are actually actionable on this position, and always including the one it leads with."""
    j = next(c for c in run_real.companies if c.company == "Pellagrin")
    ids = [f.rule_id for f in actionable(j)]
    assert len(ids) >= 2, ids
    reply = json.dumps({"rule_id": ids[0], "choice": actionable(j)[0].suggestions[0].key,
                        "label": "One step that settles both.", "reasons": ["a", "b"],
                        "covers": [ids[1]],       # omits its own id on purpose
                        "rationale": "r", "confidence": 0.5})
    step = _chooser(tmp_path, reply).choose_position(build_position_brief(j, run_real), j)
    assert step.covers[0] == ids[0] and set(step.covers) == {ids[0], ids[1]}, "its own finding is always included"


def test_F_policy_default_leads_with_the_first_finding_and_claims_only_it(run_real):
    c = _umberly(run_real)
    step = PolicyChooser().choose_position(build_position_brief(c, run_real), c)
    assert step.source == "policy" and step.rule_id == "X-304" and step.covers == ("X-304",)
    assert step.booked == next(s.booked for f in c.flags if f.rule_id == "X-304" for s in f.suggestions[:1])


def test_F_a_ready_position_has_no_step(run_real):
    ready = next(c for c in run_real.companies if c.readiness is Readiness.READY)
    assert actionable(ready) == []
    assert PolicyChooser().choose_position({}, ready) is None


def test_F_the_step_changes_no_mark_flag_or_readiness(run_real, tmp_path: Path):
    before = json.loads(run_real.model_dump_json())
    after = json.loads(recommend_run(run_real, _chooser(tmp_path, _step_reply()), None).model_dump_json())
    for b, a in zip(before["companies"], after["companies"]):
        for k in ("proposed_mark", "booked_mark", "readiness", "approval", "disposition", "provisional"):
            assert b[k] == a[k], (b["company"], k)
        assert [f["rule_id"] for f in b["flags"]] == [f["rule_id"] for f in a["flags"]]
    assert before["totals"] == after["totals"]
