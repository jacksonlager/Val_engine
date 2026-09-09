"""rules/rationale.yaml — the two bullets behind every rule the engine can raise.

A rule without its rationale cannot ship: the review tool shows the bullets beside every flag,
so a missing entry is a blank panel in front of the committee. The set of raisable ids is
read from the engine source itself, not from a hand-kept list.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import ROOT

from hc_valuation.rationale import load_rationale, rationale_by_id

ENGINE = Path(ROOT) / "src" / "hc_valuation" / "engine"
FLAG_CALL = re.compile(r'\.flag\(\s*"([EMX]-\d{3})"')


def raisable_ids() -> set[str]:
    ids: set[str] = set()
    for p in ENGINE.glob("*.py"):
        ids |= set(FLAG_CALL.findall(p.read_text(encoding="utf-8")))
    return ids


def test_every_raisable_rule_has_its_two_bullets():
    by = rationale_by_id(Path(ROOT))
    missing = sorted(raisable_ids() - set(by))
    assert not missing, f"rules/rationale.yaml has no entry for {missing}"
    for r in by.values():
        assert len(r["why_flag"]) > 25 and len(r["why_severity"]) > 40, r["id"]
        # The dialog supplies the lead-in ("Why it blocks approval.") and the rule card supplies
        # "Why this severity.", so the body continues a sentence rather than restating the enum.
        # It used to be required to OPEN with the bare enum, which is what put "Why BLOCK. BLOCK
        # because …" on a reviewer's screen.
        assert r["why_severity"].split()[0] not in {"BLOCK", "REVIEW", "MONITOR", "CLEAR"}, \
            f"{r['id']}: the severity bullet should read as prose, not open with the raw severity"


def test_brief_rules_quote_the_brief_and_cover_its_five_exceptions():
    doc = load_rationale(Path(ROOT))
    named = {
        "activity where the right treatment is not mechanical": {"X-101"},
        "stale rounds": {"X-201", "X-202"},
        "shrinking ARR": {"X-301", "X-302"},
        "short runway": {"X-303", "X-304"},
        "a mark that no longer squares with performance": {"X-401", "X-402", "X-405"},
    }
    from_brief = {r["id"]: r["brief_text"] for r in doc["rules"] if r["source"] == "brief"}
    for phrase, ids in named.items():
        for i in ids:
            assert from_brief.get(i) == phrase, f"{i} should quote the brief: {phrase!r}"
    # everything else is our call, and says so
    ours = {r["id"] for r in doc["rules"] if r["source"] == "policy"}
    assert {"X-102", "X-105", "X-117", "X-119", "X-122", "X-900"} <= ours
    assert doc["groups"] and {g["key"] for g in doc["groups"]} >= {r["family"] for r in doc["rules"]}


def test_families_match_the_engine(run_real):
    """The family on the rationale is the family the engine counts for escalation."""
    run = run_real
    by = rationale_by_id(Path(ROOT))
    seen: dict[str, set[str]] = {}
    for c in run.companies:
        for f in c.flags:
            seen.setdefault(f.rule_id, set()).add(f.family)
    for rid, fams in seen.items():
        assert fams == {by[rid]["family"]}, f"{rid}: engine says {fams}, rationale says {by[rid]['family']}"


def test_rationale_is_served_and_inlined(tmp_path):
    from fastapi.testclient import TestClient
    from hc_valuation.api.app import create_app
    client = TestClient(create_app(static_dir=tmp_path / "no-static"))
    r = client.get("/api/rationale")
    assert r.status_code == 200 and r.json()["version"] and len(r.json()["rules"]) >= 35
    from hc_valuation.export.static_report import rationale_json_script
    assert "__HC_RATIONALE__" in rationale_json_script(r.json())
    assert rationale_json_script(None) == ""


def test_a_malformed_entry_is_refused(tmp_path):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "rationale.yaml").write_text(
        "rules:\n  - id: X-999\n    name: n\n    family: f\n    severity: [REVIEW]\n    source: brief\n"
        "    reads: r\n    trigger: t\n    why_flag: why\n    why_severity: REVIEW because\n", encoding="utf-8")
    with pytest.raises(ValueError, match="brief_text"):
        load_rationale(tmp_path)


# ---------------------------------------------------------------- the catalogue must match the code

def _raised_in_the_engine() -> dict[str, set[tuple[str, str]]]:
    """Every `w.flag("X-nnn", "family", Severity.X, ...)` the engine can raise, read out of the
    source. The alternative — running a book and looking at what came out — only ever sees the 19
    of 50 rules the shipped quarter happens to raise, which is how a rule raised in a family the
    catalogue does not declare, and one raised at a severity it does not declare, both survived."""
    import re
    out: dict[str, set[tuple[str, str]]] = {}
    rx = re.compile(r"""\.flag\(\s*["'](?P<id>[A-Z]-\d{3})["']\s*,\s*["'](?P<family>\w+)["']\s*,\s*Severity\.(?P<sev>\w+)""")
    for path in (Path(ROOT) / "src" / "hc_valuation" / "engine").glob("*.py"):
        for m in rx.finditer(path.read_text()):
            out.setdefault(m.group("id"), set()).add((m.group("family"), m.group("sev")))
    assert len(out) > 30, "the scan found too few flag sites to be trusted"
    return out


def test_every_severity_the_engine_raises_is_declared_in_the_catalogue():
    """A rule card that says "worth watching" beside a finding that gates the quarter is a lie to
    the reviewer, and nothing compared the two until this test."""
    by = rationale_by_id(Path(ROOT))
    wrong = []
    for rule_id, sites in sorted(_raised_in_the_engine().items()):
        entry = by.get(rule_id)
        if entry is None:
            continue                      # covered by test_every_raisable_rule_has_its_two_bullets
        declared = set(entry["severity"])
        raised = {sev for _, sev in sites}
        if not raised <= declared:
            wrong.append(f"{rule_id}: raised {sorted(raised)}, catalogue declares {sorted(declared)}")
    assert not wrong, "the catalogue disagrees with the code:\n  " + "\n  ".join(wrong)


def test_every_family_the_engine_raises_is_a_declared_group():
    """`family` is not cosmetic: `exceptions.disposition()` counts *distinct families* for the
    two-family escalation, so a rule raised in an undeclared family changes when a position blocks
    and renders as a group the review tool has no label for."""
    doc = load_rationale(Path(ROOT))
    groups = {g["key"] for g in doc["groups"]}
    by = rationale_by_id(Path(ROOT))
    wrong = []
    for rule_id, sites in sorted(_raised_in_the_engine().items()):
        for family, _ in sites:
            if family not in groups:
                wrong.append(f"{rule_id}: raised in family {family!r}, which is not one of {sorted(groups)}")
            elif rule_id in by and by[rule_id]["family"] != family:
                wrong.append(f"{rule_id}: raised in {family!r}, catalogue says {by[rule_id]['family']!r}")
    assert not wrong, "the catalogue disagrees with the code:\n  " + "\n  ".join(wrong)
