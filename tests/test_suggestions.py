"""Suggestions: the one-to-three priced resolutions a BLOCK/REVIEW flag offers, and what
happens when a reviewer accepts one — an E-01 override addressed to that rule, which
re-runs into the booked mark, the disposition, the totals and every export."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from hc_valuation.api.app import create_app
from hc_valuation.config import repo_root
from hc_valuation.engine.inputs import Position, Status
from hc_valuation.engine.models import Severity
from hc_valuation.engine.state import Suggest, Working
from hc_valuation.export.tables import exceptions_table
from hc_valuation.pipeline import RunPaths, execute


@pytest.fixture(scope="module")
def run():
    return execute(RunPaths.default(), provider="stub").run


def _working(prior: float = 10.0, invested: float = 5.0) -> Working:
    pos = Position(company="Acme", fund="Fund I", sector="AI/ML", stage="Series A", status=Status.ACTIVE,
                   first_investment=date(2024, 1, 1), latest_round=date(2025, 1, 1), latest_post_money=100.0,
                   invested=invested, ownership=0.1, prior_mark=prior, realized=0.0, row_index=2)
    w = Working(pos=pos, quarter_label="Q3 2026", sheet_name="Q3 2026 Activity")
    w.equity_mark = prior
    return w


# ---------------------------------------------------------------- the contract on the real book

def test_every_actionable_flag_offers_one_to_three_priced_suggestions(run):
    for c in run.companies:
        for f in c.flags:
            if f.severity is Severity.MONITOR:
                assert f.suggestions == (), f"{c.company} {f.rule_id}: MONITOR has nothing to decide"
                continue
            assert 1 <= len(f.suggestions) <= 3, f"{c.company} {f.rule_id}: {len(f.suggestions)} suggestions"
            keys = [s.key for s in f.suggestions]
            assert len(set(keys)) == len(keys)
            booked = [s.booked for s in f.suggestions]
            assert len({round(b, 6) for b in booked}) == len(booked), f"{f.rule_id}: two suggestions book the same number"
            for s in f.suggestions:
                assert s.label.endswith(".") and len(s.label) <= 110, f"{f.rule_id}/{s.key}: label is one short sentence"
                assert len(s.reasons) == 2 and all(0 < len(r) <= 110 for r in s.reasons), f"{f.rule_id}/{s.key}"
                assert s.booked >= 0
                # every number is one the engine can stand behind
                candidates = {c.proposed_mark, c.prior_mark, 0.0, min(c.invested_after, c.proposed_mark),
                              *c.alternative_marks.values(), *(float(v) for v in f.evidence.values() if isinstance(v, (int, float)))}
                assert any(abs(s.booked - v) < 0.02 for v in candidates) or f.rule_id in {"X-101", "X-107", "X-115"}, \
                    f"{c.company} {f.rule_id}/{s.key}: {s.booked} is not a figure the engine computed"


def test_the_announced_deal_offers_weighted_full_and_hold(run):
    g = run.by_company()["Gryphonel"]
    f = next(f for f in g.flags if f.rule_id == "X-101")
    by = {s.key: s for s in f.suggestions}
    assert set(by) == {"as_proposed", "full_value", "hold_prior"}
    assert by["as_proposed"].booked == pytest.approx(g.proposed_mark)
    assert by["hold_prior"].booked == pytest.approx(g.prior_mark)
    assert by["full_value"].booked > by["as_proposed"].booked > by["hold_prior"].booked


def test_the_recap_offers_proposed_and_hold(run):
    t = run.by_company()["Tarnwick Aerospace"]
    f = next(f for f in t.flags if f.rule_id == "X-102")
    assert [s.key for s in f.suggestions] == ["as_proposed", "structure_adjusted", "hold_prior"]
    assert f.suggestions[0].booked == pytest.approx(t.proposed_mark) and f.suggestions[2].booked == pytest.approx(t.prior_mark)
    assert f.suggestions[1].booked == pytest.approx(t.proposed_mark * 0.75)      # the policy's structure haircut


# ---------------------------------------------------------------- resolution rules

def test_resolution_fills_numbers_and_drops_duplicates_and_missing_alternatives():
    w = _working(prior=10.0, invested=4.0)
    w.flag("X-999", "treatment", Severity.REVIEW, "Why this stopped.", action="Decide.",
           suggestions=(
               Suggest("as_proposed", "Book as proposed.", ("a", "b"), "proposed"),
               Suggest("hold", "Hold the prior mark.", ("a", "b"), "prior"),
               Suggest("cal", "Calibrate.", ("a", "b"), "alternative", value="calibrated_to_comps"),
           ))
    # proposal == prior: holding is the same decision as ratifying, so it collapses to one
    flags = w.resolved_flags(proposed=10.0, prior=10.0, invested=4.0)
    assert [s.key for s in flags[0].suggestions] == ["as_proposed"]
    assert flags[0].suggestions[0].booked == 10.0
    # proposal moved: both stand; the alternative appears only once the mark exists
    flags = w.resolved_flags(proposed=12.0, prior=10.0, invested=4.0)
    assert [s.key for s in flags[0].suggestions] == ["as_proposed", "hold"]
    w.alternative_marks["calibrated_to_comps"] = 11.5
    flags = w.resolved_flags(proposed=12.0, prior=10.0, invested=4.0)
    assert [(s.key, s.booked) for s in flags[0].suggestions] == [("as_proposed", 12.0), ("hold", 10.0), ("cal", 11.5)]


def test_cost_basis_is_a_floor_never_a_lift():
    w = _working(prior=3.0, invested=5.0)
    w.flag("X-999", "growth", Severity.REVIEW, "Why.", action="Decide.",
           suggestions=(Suggest("p", "Keep.", ("a", "b"), "proposed"), Suggest("c", "To cost.", ("a", "b"), "cost")))
    flags = w.resolved_flags(proposed=3.0, prior=3.0, invested=5.0)
    assert [s.key for s in flags[0].suggestions] == ["p"]          # cost above the mark: dropped as a duplicate of the floor
    flags = w.resolved_flags(proposed=8.0, prior=3.0, invested=5.0)
    assert [(s.key, s.booked) for s in flags[0].suggestions] == [("p", 8.0), ("c", 5.0)]


def test_flag_validates_suggestions():
    w = _working()
    with pytest.raises(ValueError, match="nothing to suggest"):
        w.flag("X-999", "treatment", Severity.MONITOR, "Context.", suggestions=(Suggest("k", "L.", ("a", "b"), "proposed"),))
    with pytest.raises(ValueError, match="exactly two reasons"):
        w.flag("X-999", "treatment", Severity.REVIEW, "Why.", action="Do.", suggestions=(Suggest("k", "L.", ("a",), "proposed"),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown basis"):
        w.flag("X-999", "treatment", Severity.REVIEW, "Why.", action="Do.", suggestions=(Suggest("k", "L.", ("a", "b"), "magic"),))
    with pytest.raises(ValueError, match="needs a number"):
        w.flag("X-999", "treatment", Severity.REVIEW, "Why.", action="Do.", suggestions=(Suggest("k", "L.", ("a", "b"), "value"),))
    with pytest.raises(ValueError, match="unique"):
        w.flag("X-999", "treatment", Severity.REVIEW, "Why.", action="Do.",
               suggestions=(Suggest("k", "L.", ("a", "b"), "proposed"), Suggest("k", "M.", ("a", "b"), "prior")))


# ---------------------------------------------------------------- accepting one, end to end

@pytest.fixture()
def scratch(tmp_path: Path) -> RunPaths:
    root = repo_root()
    data = tmp_path / "data"
    shutil.copytree(root / "data", data, ignore=shutil.ignore_patterns("sample_run.json", "published", "market_cache"))
    return RunPaths(
        root=tmp_path, policy=root / "rules" / "2026Q3.yaml", workbook=data / "HC_Mock_Portfolio_Data.xlsx",
        overrides=data / "overrides.yaml", proposals_dir=data / "proposals", precedent=data / "precedent.yaml",
        open_items_carry=data / "open_items_carry.yaml",
    )


def test_accepting_a_suggestion_flows_into_the_mark_the_disposition_and_the_totals(scratch: RunPaths, tmp_path: Path):
    client = TestClient(create_app(scratch, static_dir=tmp_path / "no-static"))
    before = client.get("/api/run").json()
    g = next(c for c in before["companies"] if c["company"] == "Gryphonel")
    assert g["disposition"] == "BLOCK"
    flag = next(f for f in g["flags"] if f["rule_id"] == "X-101")
    full = next(s for s in flag["suggestions"] if s["key"] == "full_value")

    r = client.post("/api/overrides", json={
        "company": "Gryphonel", "booked": full["booked"], "approver": "IC chair",
        "reason": f"Suggested: {full['label']} {' '.join(full['reasons'])}",
        "rule_ids_addressed": ["X-101"], "source_suggestion": "X-101/full_value",
    })
    assert r.status_code == 200, r.text
    after_c = r.json()
    assert after_c["booked_mark"] == pytest.approx(full["booked"])
    assert after_c["proposed_mark"] == pytest.approx(g["proposed_mark"])       # the proposal is never rewritten
    assert after_c["disposition"] != "BLOCK"                                  # the block is addressed
    assert after_c["override"]["source_suggestion"] == "X-101/full_value"
    assert "X-101" in after_c["override"]["rule_ids_addressed"]
    # the suggestion is still offered (the flag stays for the record), the decision is on the ledger
    ledger = yaml.safe_load(scratch.overrides.read_text())
    assert ledger["overrides"][-1]["source_suggestion"] == "X-101/full_value"

    after = client.get("/api/run").json()
    delta = full["booked"] - g["proposed_mark"]
    assert after["totals"]["booked_nav"] == pytest.approx(before["totals"]["booked_nav"] + delta, abs=1e-6)
    assert after["totals"]["dispositions"]["BLOCK"] == before["totals"]["dispositions"]["BLOCK"] - 1
    # ... and into the archive and the exports
    hist = client.get("/api/history").json()["companies"]["Gryphonel"][-1]
    assert hist["mark"] == pytest.approx(full["booked"]) and hist["overridden"] is True
    from hc_valuation.engine.models import ValuationRun
    t = exceptions_table(ValuationRun.model_validate(after))
    row = next(r for r in t.rows if r[0] == "Gryphonel" and r[2] == "X-101")
    assert "full deal value" in row[7].lower()


def test_a_second_suggestion_on_the_same_company_keeps_earlier_rules_addressed(scratch: RunPaths, tmp_path: Path):
    """One position carries one booked mark; addressing a second flag must not un-address the first."""
    client = TestClient(create_app(scratch, static_dir=tmp_path / "no-static"))
    run = client.get("/api/run").json()
    t = next(c for c in run["companies"] if c["company"] == "Tarnwick Aerospace")
    ids = [f["rule_id"] for f in t["flags"] if f["severity"] != "MONITOR"]
    assert "X-102" in ids and "X-302" in ids
    hold = next(s for f in t["flags"] if f["rule_id"] == "X-102" for s in f["suggestions"] if s["key"] == "hold_prior")
    c1 = client.post("/api/overrides", json={"company": "Tarnwick Aerospace", "booked": hold["booked"], "approver": "A",
                                             "reason": "hold", "rule_ids_addressed": ["X-102"],
                                             "source_suggestion": "X-102/hold_prior"}).json()
    assert c1["disposition"] == "REVIEW"        # the block is addressed; the ARR review is still open
    # the UI sends the union of what was already addressed plus the new rule
    keep = next(s for f in c1["flags"] if f["rule_id"] == "X-302" for s in f["suggestions"] if s["key"] == "as_proposed")
    c2 = client.post("/api/overrides", json={"company": "Tarnwick Aerospace", "booked": keep["booked"], "approver": "A",
                                             "reason": "keep", "rule_ids_addressed": ["X-102", "X-302"],
                                             "source_suggestion": "X-302/as_proposed"}).json()
    assert c2["disposition"] == "MONITOR"
    assert set(c2["override"]["rule_ids_addressed"]) == {"X-102", "X-302"}


# ---------------------------------------------------------------- the approver's own two routes

def _e01(company: dict) -> dict:
    return next(s for s in company["steps"] if s["rule_id"] == "E-01")


def test_a_mark_the_approver_typed_is_booked_and_the_chain_says_who_chose_it(scratch: RunPaths, tmp_path: Path):
    """The Decide panel's manual route: a number that is not one of the engine's options. The
    ledger keeps it under the approver's name with the reason they wrote, and the E-01 step
    says the number was entered by hand rather than picked from a priced option."""
    client = TestClient(create_app(scratch, static_dir=tmp_path / "no-static"))
    before = client.get("/api/run").json()
    g = next(c for c in before["companies"] if c["company"] == "Gryphonel")
    typed = round(g["proposed_mark"] * 0.9, 2)
    assert all(abs(s["booked"] - typed) > 1e-6 for f in g["flags"] for s in f["suggestions"])

    r = client.post("/api/overrides", json={
        "company": "Gryphonel", "booked": typed, "approver": "IC chair",
        "reason": "Haircut for the escrow dispute the engine cannot see; counsel's estimate.",
        "rule_ids_addressed": ["X-101"], "source_suggestion": "X-101/manual",
    })
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["booked_mark"] == pytest.approx(typed) and c["proposed_mark"] == pytest.approx(g["proposed_mark"])
    step = _e01(c)
    assert step["inputs"]["chosen_by"] == "mark entered by the approver"
    assert step["inputs"]["approver"] == "IC chair" and "counsel" in step["inputs"]["reason"]
    assert "mark entered by the approver" in step["rationale"]
    ledger = yaml.safe_load(scratch.overrides.read_text())["overrides"][-1]
    assert ledger["booked"] == pytest.approx(typed) and ledger["source_suggestion"] == "X-101/manual"
    assert ledger["approver"] == "IC chair"


def test_accepting_the_proposal_as_it_stands_records_a_decision_without_moving_the_mark(scratch: RunPaths, tmp_path: Path):
    """The Decide panel's accept route: booked equals proposed, so the total does not move, but
    the flag is now decided under a name and the block clears."""
    client = TestClient(create_app(scratch, static_dir=tmp_path / "no-static"))
    before = client.get("/api/run").json()
    g = next(c for c in before["companies"] if c["company"] == "Gryphonel")
    r = client.post("/api/overrides", json={
        "company": "Gryphonel", "booked": g["proposed_mark"], "approver": "IC chair",
        "reason": "Accepted the engine's proposed mark for X-101; no adjustment.",
        "rule_ids_addressed": ["X-101"], "source_suggestion": "X-101/proposed",
    })
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["booked_mark"] == pytest.approx(g["proposed_mark"])
    assert c["disposition"] != "BLOCK"
    assert _e01(c)["inputs"]["chosen_by"] == "proposed mark accepted"
    after = client.get("/api/run").json()
    assert after["totals"]["booked_nav"] == pytest.approx(before["totals"]["booked_nav"], abs=1e-6)


def test_a_manual_mark_still_needs_a_reason_and_a_name(scratch: RunPaths, tmp_path: Path):
    """The confirmation cannot be skipped server-side either."""
    client = TestClient(create_app(scratch, static_dir=tmp_path / "no-static"))
    for body in ({"reason": "", "approver": "IC chair"}, {"reason": "because", "approver": ""}):
        r = client.post("/api/overrides", json={"company": "Gryphonel", "booked": 4.0, "rule_ids_addressed": ["X-101"],
                                                "source_suggestion": "X-101/manual", **body})
        assert r.status_code == 422, r.text


# ---------------------------------------------------------------- supplying the missing price

_CLOSE = {"kind": "closing_price", "as_of": "2026-09-30", "market_cap_musd": 3712.0, "price": 41.2,
          "shares_m": 90.1, "source": "Nasdaq close via Bloomberg", "ownership": 0.028}


def test_a_closing_price_supplied_by_the_reviewer_travels_with_the_override(scratch: RunPaths, tmp_path: Path):
    """Drayvenn is Blocked because no quarter-end quote is on file (X-101 on a stub price). The
    reviewer's price is evidence, not an assertion: the ledger keeps the input, the E-01 step
    names the route and carries the evidence, and the rationale says where the price came from."""
    client = TestClient(create_app(scratch, static_dir=tmp_path / "no-static"))
    before = client.get("/api/run").json()
    d = next(c for c in before["companies"] if c["company"] == "Drayvenn")
    assert d["disposition"] == "BLOCK"
    flag = next(f for f in d["flags"] if f["rule_id"] == "X-101")
    assert "price_source" in flag["evidence"] and "seeded_to_ipo_print" in flag["evidence"]["price_source"]

    booked = round(_CLOSE["market_cap_musd"] * _CLOSE["ownership"], 3)
    r = client.post("/api/overrides", json={
        "company": "Drayvenn", "booked": booked, "approver": "IC chair",
        "reason": "30 Sep close obtained; marks the listed position to the measurement-date price.",
        "rule_ids_addressed": ["X-101"], "source_suggestion": "X-101/price", "evidence": _CLOSE,
    })
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["booked_mark"] == pytest.approx(booked) and c["disposition"] != "BLOCK"
    assert c["override"]["evidence"] == _CLOSE
    step = _e01(c)
    assert step["inputs"]["chosen_by"] == "closing price supplied"
    assert step["inputs"]["evidence"] == _CLOSE
    assert "closing price supplied: market cap $3,712M at 2026-09-30 from Nasdaq close via Bloomberg × 2.8% held" in step["rationale"]
    ledger = yaml.safe_load(scratch.overrides.read_text())["overrides"][-1]
    assert ledger["evidence"] == _CLOSE and ledger["source_suggestion"] == "X-101/price"
    # an override without evidence writes no key at all, so older readers see the ledger they expect
    client.post("/api/overrides", json={"company": "Gryphonel", "booked": 4.0, "approver": "A", "reason": "r",
                                        "rule_ids_addressed": ["X-101"], "source_suggestion": "X-101/manual"})
    assert "evidence" not in yaml.safe_load(scratch.overrides.read_text())["overrides"][-1]


def test_closing_price_evidence_must_carry_a_positive_market_cap_and_a_source(scratch: RunPaths, tmp_path: Path):
    client = TestClient(create_app(scratch, static_dir=tmp_path / "no-static"))
    base = {"company": "Drayvenn", "booked": 100.0, "approver": "IC chair", "reason": "close obtained",
            "rule_ids_addressed": ["X-101"], "source_suggestion": "X-101/price"}
    bad = (
        {**_CLOSE, "source": ""}, {k: v for k, v in _CLOSE.items() if k != "source"},
        {**_CLOSE, "market_cap_musd": 0}, {**_CLOSE, "market_cap_musd": -5.0},
        {k: v for k, v in _CLOSE.items() if k != "market_cap_musd"},
        {**_CLOSE, "kind": ""}, {k: v for k, v in _CLOSE.items() if k != "kind"},
    )
    for evidence in bad:
        r = client.post("/api/overrides", json={**base, "evidence": evidence})
        assert r.status_code == 422, (evidence, r.text)
        assert "message" in r.json()["detail"]
    # other kinds are only asked to name themselves
    r = client.post("/api/overrides", json={**base, "evidence": {"kind": "counsel_memo", "ref": "2026-09-14"}})
    assert r.status_code == 200, r.text
    assert not yaml.safe_load(scratch.overrides.read_text())["overrides"][-1].get("evidence", {}).get("source")


def test_a_ledger_written_with_evidence_reloads_with_it_intact(scratch: RunPaths, tmp_path: Path):
    from hc_valuation.api.app import append_override
    append_override(scratch.overrides, {
        "company": "Drayvenn", "quarter": "Q3 2026", "proposed": 110.068, "booked": 103.936,
        "reason": "close obtained", "approver": "IC chair", "created_at": "2026-10-02",
        "rule_ids_addressed": ["X-101"], "source_suggestion": "X-101/price", "evidence": _CLOSE,
    })
    client = TestClient(create_app(scratch, static_dir=tmp_path / "no-static"))
    d = next(c for c in client.get("/api/run").json()["companies"] if c["company"] == "Drayvenn")
    assert d["override"]["evidence"] == _CLOSE
    assert d["override"]["evidence"]["as_of"] == "2026-09-30"          # stays a string through YAML
    assert _e01(d)["inputs"]["chosen_by"] == "closing price supplied"
