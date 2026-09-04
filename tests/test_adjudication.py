"""Phase 08 — E-09 novel-case adjudication.

A synthetic workbook with one company and one "SPAC Merger" event: the engine blocks it
with M-999; the adjudicator drafts a proposal by analogy (M-040) that names missing facts;
the DSL rejects a formula outside the whitelist before any model output is trusted; the
cache makes re-runs reproduce; promote / accept-once / reject each land in the right
ledger; and with adjudication off the run is byte-for-byte the same block.

Everything writes under tmp paths via `RunPaths`, so `data/proposals/` and
`data/precedent.yaml` stay clean.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import openpyxl
import pytest
import yaml

from hc_valuation.adjudication import load_proposal, novel_events, proposal_path
from hc_valuation.adjudication.promote import next_quarter, record_decision, suggest_promotion
from hc_valuation.adjudication.proposer import (
    ClaudeProposer, StubProposer, build_packet, policy_markdown_catalogue,
)
from hc_valuation.adjudication.schema import (
    DSLError, Provenance, TreatmentProposal, catalogue_version_for, make_proposal_id, to_custom_rule_spec, validation_scope,
)
from hc_valuation.config import load_config, repo_root
from hc_valuation.engine.models import Severity
from hc_valuation.engine.run import build_registry
from hc_valuation.ingest.schema import ACTIVITY_COLUMNS, PORTFOLIO_COLUMNS
from hc_valuation.pipeline import RunPaths, execute

ROOT = repo_root()
COMPANY = "Vantrix Labs"
GENERATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------- fixtures

def _write_workbook(path: Path, quarter_label: str, event_type: str = "SPAC Merger",
                    detail: str = "Business combination with Halcyon Acquisition Corp II", notes: str = "") -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio"
    ws.append(list(PORTFOLIO_COLUMNS))
    # prior mark 6.0 = 5% × $120M post, so X-904 reconciliation passes
    ws.append([COMPANY, "Fintech", "Fund II", "Series B", "Active", date(2022, 3, 1), date(2024, 5, 1),
               120.0, 5.0, 0.05, 6.0, 0.0, 1.2, 4.0, 0.30, 0.70, 0.5, 10.0, 20.0, 60])
    act = wb.create_sheet(f"{quarter_label} Activity")
    act.append(list(ACTIVITY_COLUMNS))
    act.append([date(2026, 8, 15), COMPANY, event_type, detail, 500.0, None, 0.03, None, notes])
    wb.save(path)


@pytest.fixture
def paths(tmp_path: Path) -> RunPaths:
    (tmp_path / "rules").mkdir()
    (tmp_path / "docs").mkdir()
    shutil.copy(ROOT / "rules" / "2026Q3.yaml", tmp_path / "rules" / "2026Q3.yaml")
    shutil.copy(ROOT / "docs" / "valuation-policy.md", tmp_path / "docs" / "valuation-policy.md")
    cfg = load_config(tmp_path / "rules" / "2026Q3.yaml")
    wb = tmp_path / "synthetic.xlsx"
    _write_workbook(wb, cfg.quarter.label)
    return RunPaths(root=tmp_path, policy=tmp_path / "rules" / "2026Q3.yaml", workbook=wb,
                    overrides=tmp_path / "overrides.yaml", proposals_dir=tmp_path / "proposals",
                    precedent=tmp_path / "precedent.yaml", open_items_carry=tmp_path / "carry.yaml")


def _company(result):
    return result.run.by_company()[COMPANY]


# ---------------------------------------------------------------- the run blocks; the draft explains

def test_spac_blocks_with_m999_and_yields_m040_proposal(paths):
    r = execute(paths, generated_at=GENERATED_AT)
    c = _company(r)
    assert c.disposition.value == "BLOCK"
    assert [f.rule_id for f in c.flags if f.rule_id == "M-999"] == ["M-999"]
    assert c.proposed_mark == pytest.approx(6.0)          # unchanged: never a silent carry, never a model number

    assert len(r.proposals) == 1
    p = r.proposals[0]
    assert p.company == COMPANY and p.event_type == "SPAC Merger"
    assert p.analogue_rule_id == "M-040" and p.proposed_kind == "reuse"
    assert p.suggested_severity in (Severity.REVIEW, Severity.BLOCK)
    assert p.missing_facts and p.missing_facts != ["none"]
    assert p.formula == "ownership_after * deal_value"
    assert p.status == "pending" and p.decision is None
    assert p.provenance.model == "stub-heuristics" and p.provenance.catalogue_version.startswith(r.config.policy_version)
    assert p.proposal_id == make_proposal_id(p.event_signature, p.provenance.catalogue_version)
    assert proposal_path(paths.proposals_dir, p.proposal_id).exists()
    # the proposal sits beside the run; the run itself is untouched
    assert r.run.manifest.adjudication_enabled and _company(r).proposed_mark == 6.0


def test_novel_events_matches_flag_to_feed_row(paths):
    r = execute(paths, adjudicate=False)
    from hc_valuation.ingest.reader import read_workbook
    _, feed = read_workbook(paths.workbook, r.config)
    assert novel_events(r.run, feed) == [(COMPANY, "spac merger", 2)]


# ---------------------------------------------------------------- schema is hostile to the model

def _prov(cfg):
    return Provenance(model="test", prompt_sha256="0" * 64,
                      catalogue_version=catalogue_version_for(cfg.policy_version, build_registry(cfg)), created_at=GENERATED_AT)


def _draft(cfg, **over):
    data = dict(event_signature="spac merger", event_type="SPAC Merger", company=COMPANY, event_row_index=2,
                quarter_label=cfg.quarter.label, proposed_mark_at_proposal=6.0, analogue_rule_id="M-040",
                proposed_kind="reuse", formula="ownership_after * deal_value", parameter_map={},
                suggested_severity=Severity.BLOCK, rationale="like an IPO", missing_facts=["closing market cap"],
                confidence=0.5, provenance=_prov(cfg))
    data.update(over)
    return TreatmentProposal(**data)


def test_formula_outside_whitelist_is_rejected_by_the_dsl(paths):
    cfg = load_config(paths.policy)
    with validation_scope(cfg, build_registry(cfg)):
        with pytest.raises(DSLError, match="evil_field"):
            _draft(cfg, formula="ownership_after * evil_field")
        with pytest.raises(DSLError):
            _draft(cfg, formula="__import__('os').system('rm -rf /')")
        with pytest.raises(DSLError):
            _draft(cfg, formula="ownership_after ** 2")
    # outside any scope the engine's own vocabulary is the ceiling
    with pytest.raises(DSLError):
        _draft(cfg, formula="ownership_after * market_cap")


def test_schema_constraints(paths):
    cfg = load_config(paths.policy)
    with validation_scope(cfg, build_registry(cfg)):
        with pytest.raises(ValueError, match="not a registered rule"):
            _draft(cfg, analogue_rule_id="M-777")
        with pytest.raises(ValueError, match="can never be below REVIEW"):
            _draft(cfg, suggested_severity=Severity.MONITOR)
        with pytest.raises(ValueError, match="missing_facts"):
            _draft(cfg, missing_facts=[])
        with pytest.raises(ValueError):
            _draft(cfg, missing_facts=["none", "also this"])
        assert _draft(cfg, missing_facts=["none"]).missing_facts == ["none"]
        with pytest.raises(ValueError):
            _draft(cfg, confidence=1.5)
        with pytest.raises(ValueError, match="proposal_id"):
            _draft(cfg, proposal_id="deadbeef")
        p = _draft(cfg)
        with pytest.raises(Exception):
            p.formula = "prior_mark"        # frozen
        # round-trips through JSON with the same id
        assert TreatmentProposal.from_json(p.to_json()) == p


def test_to_custom_rule_spec(paths):
    cfg = load_config(paths.policy)
    with validation_scope(cfg, build_registry(cfg)):
        p = _draft(cfg)
    spec = to_custom_rule_spec(p, approver="Tom Moore", effective_from=date(2026, 7, 1), rule_id="M-100")
    assert spec.event_type == "SPAC Merger" and spec.formula == p.formula and spec.severity == "BLOCK"
    assert spec.fv_level == 1 and not spec.terminal and spec.source_proposal == p.proposal_id
    assert "M-040" in spec.rationale


# ---------------------------------------------------------------- stub heuristics + packet

@pytest.mark.parametrize("event_type,detail,analogue,formula", [
    ("SPAC Merger", "de-SPAC with a sponsor", "M-040", "ownership_after * deal_value"),
    ("Direct Listing", "NYSE direct listing", "M-040", "ownership_after * deal_value"),
    ("Chapter 11 Filing", "bankruptcy petition", "M-021", "0"),
    ("Escrow Release", "holdback released", "M-020", "proceeds"),
    ("Warrant Exercise", "warrants exercised", "M-060", "prior_mark + hc_investment"),
    ("Tender Offer", "company buyback", "M-030", "ownership_after * post_money"),
    ("Cash Dividend", "special distribution", "M-000", "prior_mark"),
    ("Token Generation Event", "utility token launch", "M-999", "prior_mark"),
])
def test_stub_heuristics(event_type, detail, analogue, formula):
    h = StubProposer().match(event_type, detail, "")
    assert (h.analogue, h.formula) == (analogue, formula)
    assert h.missing_facts
    if analogue == "M-999":
        assert h.kind == "new_rule" and h.severity == Severity.BLOCK


def test_packet_carries_catalogue_and_principles(paths):
    r = execute(paths, adjudicate=False)
    cfg = r.config
    reg = build_registry(cfg)
    from hc_valuation.ingest.reader import read_workbook
    snap, feed = read_workbook(paths.workbook, cfg)
    pk = build_packet(feed.events[0], snap.by_company()[COMPANY], _company(r), cfg, reg, paths.root / "docs" / "valuation-policy.md")
    ids = {c["rule_id"] for c in pk.catalogue}
    assert {"M-000", "M-040", "M-999"} <= ids
    m040 = next(c for c in pk.catalogue if c["rule_id"] == "M-040")
    assert "market_cap" in m040["formula"]            # pulled from the policy markdown table
    assert any(p.startswith("Mechanical rules produce a number") for p in pk.principles)
    assert pk.position["company"] == COMPANY and pk.allowed_fields == cfg.adjudication.allowed_fields
    json.dumps(pk.to_dict(), default=str)           # serialisable for a model call
    rules, principles = policy_markdown_catalogue(paths.root / "nope.md")
    assert rules == {} and principles == []


# ---------------------------------------------------------------- claude proposer never raises

def test_claude_proposer_falls_back_without_key(paths, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = execute(paths, adjudicate=False)
    cfg = r.config
    reg = build_registry(cfg)
    from hc_valuation.ingest.reader import read_workbook
    _, feed = read_workbook(paths.workbook, cfg)
    pk = build_packet(feed.events[0], None, _company(r), cfg, reg, None)
    cp = ClaudeProposer(model="claude-sonnet-4-5")
    assert not cp.available
    with validation_scope(cfg, reg):
        p = cp.propose(pk)
    assert p.provenance.model == "stub-fallback" and p.analogue_rule_id == "M-040"

    # a key that leads to a failing / malformed call also falls back, never raises
    bad = ClaudeProposer(api_key="sk-not-real")
    monkeypatch.setattr(bad, "_call", lambda packet: "this is not json")
    with validation_scope(cfg, reg):
        assert bad.propose(pk).provenance.model == "stub-fallback"
    monkeypatch.setattr(bad, "_call", lambda packet: json.dumps({
        "analogue_rule_id": "M-040", "proposed_kind": "reuse", "formula": "ownership_after * evil_field",
        "parameter_map": {}, "suggested_severity": "BLOCK", "rationale": "x", "missing_facts": ["y"], "confidence": 0.9}))
    with validation_scope(cfg, reg):
        assert bad.propose(pk).provenance.model == "stub-fallback"     # whitelist violation -> DSLError -> fallback
    good = json.dumps({"analogue_rule_id": "M-040", "proposed_kind": "reuse", "formula": "ownership_after * deal_value",
                       "parameter_map": {"deal_value": "pro-forma EV"}, "suggested_severity": "REVIEW", "rationale": "listing",
                       "missing_facts": ["none"], "confidence": 0.8})
    monkeypatch.setattr(bad, "_call", lambda packet: "```json\n" + good + "\n```")
    with validation_scope(cfg, reg):
        p = bad.propose(pk)
    assert p.provenance.model == "claude-sonnet-4-5" and p.suggested_severity == Severity.REVIEW


# ---------------------------------------------------------------- cache

def test_second_run_hits_cache(paths):
    r1 = execute(paths, generated_at=GENERATED_AT)
    files = sorted(paths.proposals_dir.glob("*.json"))
    assert len(files) == 1
    mtime = files[0].stat().st_mtime_ns
    r2 = execute(paths, generated_at=GENERATED_AT)
    assert sorted(paths.proposals_dir.glob("*.json")) == files
    assert files[0].stat().st_mtime_ns == mtime
    assert r2.proposals[0] == r1.proposals[0] and r2.proposals[0].proposal_id == r1.proposals[0].proposal_id
    # determinism of the run itself is untouched by adjudication
    assert r1.run.model_dump_json() == r2.run.model_dump_json()


def test_cache_key_moves_with_policy_version(paths):
    r1 = execute(paths, generated_at=GENERATED_AT)
    raw = yaml.safe_load(paths.policy.read_text())
    raw["policy_version"] = "2026Q3-0.2"
    paths.policy.write_text(yaml.safe_dump(raw, sort_keys=False))
    r2 = execute(paths, generated_at=GENERATED_AT)
    assert r2.proposals[0].proposal_id != r1.proposals[0].proposal_id
    assert len(list(paths.proposals_dir.glob("*.json"))) == 2


# ---------------------------------------------------------------- decisions

def test_promote_writes_rule_and_next_run_applies_it(paths):
    r = execute(paths, generated_at=GENERATED_AT)
    pid = r.proposals[0].proposal_id
    out = record_decision(paths, pid, "promote", approver="Tom Moore", reason="SPAC = listing; treat as M-040")
    assert out["status"] == "promoted" and out["rule"]["rule_id"] == "M-100"

    cur = yaml.safe_load(paths.policy.read_text())
    assert cur["custom_rules"][0]["rule_id"] == "M-100" and cur["custom_rules"][0]["approver"] == "Tom Moore"
    assert cur["custom_rules"][0]["source_proposal"] == pid
    assert "# Every threshold the engine uses lives here" in paths.policy.read_text()   # comments survived
    nxt = paths.policy.parent / "2026Q4.yaml"
    assert nxt.exists()
    nraw = yaml.safe_load(nxt.read_text())
    assert nraw["inherits"] == "2026Q3.yaml" and nraw["quarter"]["label"] == "Q4 2026"
    assert nraw["custom_rules"][0]["rule_id"] == "M-100"
    ncfg = load_config(nxt)
    assert ncfg.quarter.measurement_date == date(2026, 12, 31) and ncfg.custom_rules[0].rule_id == "M-100"

    r2 = execute(paths, generated_at=GENERATED_AT)
    c = _company(r2)
    assert "M-100" in [s.rule_id for s in c.steps]
    assert not any(f.rule_id == "M-999" for f in c.flags)
    assert c.proposed_mark == pytest.approx(0.03 * 500.0)       # the ENGINE computed it, from the promoted formula
    assert c.fv_level == 1 and c.ownership_after == 0.03
    assert r2.proposals == []                                    # nothing left to adjudicate

    prop = load_proposal(proposal_path(paths.proposals_dir, pid), load_config(paths.policy))
    assert prop.status == "promoted" and prop.decision["approver"] == "Tom Moore" and prop.decision["rule_id"] == "M-100"
    prec = yaml.safe_load(paths.precedent.read_text())
    assert prec["precedents"]["spac merger"]["promoted"] and prec["precedents"]["spac merger"]["repeat_count"] == 1
    assert prec["decisions"][0]["decision"] == "promote"
    with pytest.raises(ValueError, match="already promoted"):
        record_decision(paths, pid, "reject", approver="Tom Moore", reason="changed my mind")


def test_promoted_rule_respects_effective_dating(paths):
    r = execute(paths, generated_at=GENERATED_AT)
    record_decision(paths, r.proposals[0].proposal_id, "promote", approver="Tom Moore", reason="x",
                    effective_from=date(2026, 10, 1))
    r2 = execute(paths, generated_at=GENERATED_AT)
    # effective next quarter: this quarter still blocks under M-999 — a Q4 rule never rewrites Q3
    assert any(f.rule_id == "M-999" for f in _company(r2).flags)


def test_accept_once_writes_override_and_books_it(paths):
    r = execute(paths, generated_at=GENERATED_AT)
    pid = r.proposals[0].proposal_id
    with pytest.raises(ValueError, match="booked"):
        record_decision(paths, pid, "accept_once", approver="Tom Moore", reason="no number")
    out = record_decision(paths, pid, "accept_once", approver="Tom Moore", reason="book at pro-forma", booked=15.0)
    assert out["status"] == "accepted_once"
    ov = yaml.safe_load(paths.overrides.read_text())["overrides"]
    assert len(ov) == 1 and ov[0]["company"] == COMPANY and ov[0]["booked"] == 15.0 and ov[0]["source_proposal"] == pid
    assert ov[0]["proposed"] == 6.0 and ov[0]["rule_ids_addressed"] == ["M-999"] and "Tom Moore" == ov[0]["approver"]

    r2 = execute(paths, generated_at=GENERATED_AT)
    c = _company(r2)
    assert c.booked_mark == 15.0 and c.proposed_mark == 6.0 and c.override.source_proposal == pid
    assert any(s.rule_id == "E-01" for s in c.steps) and any(f.rule_id == "M-999" for f in c.flags)   # no rule was created
    assert yaml.safe_load(paths.policy.read_text())["custom_rules"] == []
    assert load_proposal(proposal_path(paths.proposals_dir, pid), r2.config).status == "accepted_once"


def test_accept_once_keeps_existing_overrides(paths):
    paths.overrides.write_text(yaml.dump({"overrides": [{"company": "Other", "quarter": "Q3 2026", "proposed": 1.0, "booked": 2.0,
                                                          "reason": "r", "approver": "a", "created_at": "2026-09-30"}]}))
    r = execute(paths, generated_at=GENERATED_AT)
    record_decision(paths, r.proposals[0].proposal_id, "accept_once", approver="Tom Moore", reason="x", booked=15.0)
    ov = yaml.safe_load(paths.overrides.read_text())["overrides"]
    assert [o["company"] for o in ov] == ["Other", COMPANY]


def test_reject_records_only(paths):
    r = execute(paths, generated_at=GENERATED_AT)
    pid = r.proposals[0].proposal_id
    out = record_decision(paths, pid, "reject", approver="Tom Moore", reason="not an IPO analogue")
    assert out["status"] == "rejected" and not paths.overrides.exists()
    assert yaml.safe_load(paths.policy.read_text())["custom_rules"] == []
    prec = yaml.safe_load(paths.precedent.read_text())
    assert prec["precedents"]["spac merger"] == {**prec["precedents"]["spac merger"], "repeat_count": 0, "reject_count": 1}
    r2 = execute(paths, generated_at=GENERATED_AT)
    assert any(f.rule_id == "M-999" for f in _company(r2).flags) and _company(r2).booked_mark == 6.0
    with pytest.raises(ValueError, match="named approver"):
        record_decision(paths, pid, "reject", approver="", reason="x")


def test_suggest_promotion_after_repeats(paths):
    cfg = load_config(paths.policy)
    sig = "spac merger"
    assert not suggest_promotion(paths, sig, cfg)
    for i in range(cfg.adjudication.promote_after_repeats):
        r = execute(paths, generated_at=GENERATED_AT)
        pid = r.proposals[0].proposal_id
        out = record_decision(paths, pid, "accept_once", approver="Tom Moore", reason=f"repeat {i}", booked=15.0)
        # reset so the same signature can be adjudicated again (a fresh quarter would do this naturally)
        proposal_path(paths.proposals_dir, pid).unlink()
        paths.overrides.unlink()
    assert out["precedent"]["repeat_count"] == cfg.adjudication.promote_after_repeats
    assert out["suggest_promotion"] is True and suggest_promotion(paths, sig, cfg)


def test_next_quarter_arithmetic():
    assert next_quarter("Q3 2026")[:2] == ("Q4 2026", "2026Q4")
    lbl, compact, w = next_quarter("Q4 2026")
    assert (lbl, compact) == ("Q1 2027", "2027Q1")
    assert w == {"measurement_date": date(2027, 3, 31), "prior_close": date(2026, 12, 31),
                 "window_start": date(2027, 1, 1), "window_end": date(2027, 3, 31)}
    with pytest.raises(ValueError):
        next_quarter("FY2026")


# ---------------------------------------------------------------- off switch

def test_disabled_adjudication_is_a_plain_block(paths):
    on = execute(paths, generated_at=GENERATED_AT)
    raw = yaml.safe_load(paths.policy.read_text())
    raw["adjudication"]["enabled"] = False
    paths.policy.write_text(yaml.safe_dump(raw, sort_keys=False))
    shutil.rmtree(paths.proposals_dir)
    off = execute(paths, generated_at=GENERATED_AT)
    assert off.proposals == [] and not paths.proposals_dir.exists()
    assert off.run.totals.dispositions == on.run.totals.dispositions
    assert [c.flags for c in off.run.companies] == [c.flags for c in on.run.companies]
    assert [c.steps for c in off.run.companies] == [c.steps for c in on.run.companies]
    assert not off.run.manifest.adjudication_enabled and on.run.manifest.adjudication_enabled


def test_real_workbook_has_no_novel_events_and_repo_data_stays_clean():
    before = sorted((ROOT / "data" / "proposals").glob("*"))
    r = execute()
    assert r.proposals == []
    assert sorted((ROOT / "data" / "proposals").glob("*")) == before
    assert not (ROOT / "data" / "precedent.yaml").exists() or yaml.safe_load((ROOT / "data" / "precedent.yaml").read_text())
