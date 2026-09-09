"""The Q2 2026 test file (training/HC_Q2_2026_Test_Portfolio.xlsx): a quarter *earlier* than the base
policy, with event types the engine had never seen (two of them — Term Sheet Withdrawn and Operating
Update — are handled since the Q3 scenario rows; the rest still block), two initial investments filed as priced
rounds, a non-binding acquisition offer, and an answer key in its extra tabs.

What it found (all fixed here): every built-in rule was dated 2026-07-01, so a 30 Jun 2026 run raised
instead of reporting; an LOI was probability-weighted like a signed agreement; a first investment
filed as `Priced Equity Round` on a company not in the book was refused rather than created.

The engine must reproduce the key's closing marks, invested capital and realized proceeds to the
file's own tolerance, put every judgment it lists in front of a reviewer, and refuse — visibly — the
event types it does not know. The file is the reviewer's, not the repo's; the test skips if absent.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import openpyxl
import pytest

from hc_valuation.config import repo_root, write_next_policy
from hc_valuation.engine.inputs import EventType
from hc_valuation.pipeline import RunPaths, execute
from tests.conftest import event, make_workbook, position, run_workbook

ROOT = repo_root()
FIXTURE = next((p for p in (ROOT / "training" / "HC_Q2_2026_Test_Portfolio.xlsx",
                            ROOT / "data" / "quarters" / "2026Q2" / "HC_Q2_2026_Test_Portfolio.xlsx") if p.exists()), None)
pytestmark = pytest.mark.skipif(FIXTURE is None, reason="Q2 2026 test workbook not present")


@pytest.fixture(scope="module")
def q2(tmp_path_factory):
    root = tmp_path_factory.mktemp("q2")
    import shutil
    shutil.copytree(ROOT / "rules", root / "rules")
    shutil.copytree(ROOT / "data" / "mock_responses", root / "data" / "mock_responses")
    if not (root / "rules" / "2026Q2.yaml").exists():
        write_next_policy(root / "rules" / "2026Q3.yaml", quarter="Q2 2026")
    paths = RunPaths.default(root=root, workbook=FIXTURE, policy=root / "rules" / "2026Q2.yaml", ledger_dir=root / "ledger")
    run = execute(paths, provider="stub").run
    wb = openpyxl.load_workbook(FIXTURE, data_only=True)
    ws = wb["June 30 Target"]
    hdr = [c.value for c in ws[1]]
    target = {r[0]: dict(zip(hdr, r)) for r in ws.iter_rows(min_row=2, values_only=True) if r[0]}
    bridge = wb["Value Bridge"]
    bh = [c.value for c in bridge[1]]
    for r in bridge.iter_rows(min_row=2, values_only=True):
        if r[0] in target:
            target[r[0]]["raw_closing"] = dict(zip(bh, r))["Raw closing value"]   # before the file's $0.1M rounding
    return run, target


def test_a_quarter_before_the_base_policy_runs(q2):
    run, target = q2
    assert run.manifest.quarter_label == "Q2 2026" and run.manifest.measurement_date == date(2026, 6, 30)
    assert run.totals.positions == 100 == len(target)          # 98 opening + the two initial investments


def test_marks_invested_and_realized_tie_to_the_answer_key(q2):
    run, target = q2
    by = run.by_company()
    # The key's one explicit reviewer judgment: Gryphonel's LOI is held at 3.5; the engine proposes exactly that
    # now that a non-binding offer holds the mark. Everything else must tie to the file's 0.05 rounding.
    off = [(n, c.proposed_mark, t["Prior Mark ($M)"]) for n, t in target.items() for c in [by[n]]
           if abs(c.proposed_mark - (t["Prior Mark ($M)"] or 0)) > 0.05]
    assert off == [], off
    # ... and to the unrounded closing values on the Value Bridge tab, tightly
    raw_off = [(n, c.proposed_mark, t["raw_closing"]) for n, t in target.items() for c in [by[n]]
               if t.get("raw_closing") is not None and abs(c.proposed_mark - float(t["raw_closing"])) > 1e-3]
    assert raw_off == [], raw_off
    assert all(abs(by[n].invested_after - (t["Invested ($M)"] or 0)) <= 0.05 for n, t in target.items())
    assert all(abs(by[n].realized_cumulative - (t["Realized ($M)"] or 0)) <= 0.05 for n, t in target.items())
    assert round(sum(c.invested_after for c in run.companies), 1) == 613.4      # the file's Checks tab
    assert round(sum(c.realized_cumulative for c in run.companies), 1) == 17.1


def test_unknown_event_types_block_visibly_and_the_rest_reach_a_reviewer(q2):
    run, _ = q2
    by = run.by_company()
    # Stock Split (M-015) and Debt Facility (M-062) are handled now: a neutral split is nothing to decide, debt ahead
    # of the equity is a review. Neither is a blocked unknown any more.
    d, u = by["Drayvenn"], by["Umberly"]
    assert d.readiness.value == "Ready" and [s.rule_id for s in d.steps] == ["M-015"] and d.ownership_after == pytest.approx(0.034)
    assert u.readiness.value == "Needs Review" and [s.rule_id for s in u.steps] == ["M-062"] and "X-127" in {f.rule_id for f in u.flags}
    assert not any("M-999" in {f.rule_id for f in c.flags} for c in (d, u))
    # Operating Update (M-072) and Term Sheet Withdrawn (M-071) are handled now: the mark holds and a reviewer
    # gets the right question — the figures belong on the tab (X-126); the failed raise is weighed (X-125)
    b, h = by["Brumewell"], by["Halcyra"]
    assert b.readiness.value == "Needs Review" and [s.rule_id for s in b.steps] == ["M-072"] and "X-126" in {f.rule_id for f in b.flags}
    assert h.readiness.value == "Needs Review" and [s.rule_id for s in h.steps] == ["M-070", "M-071"]
    assert "X-125" in {f.rule_id for f in h.flags} and not any(i.kind.value == "term_sheet" for i in h.open_items)
    assert not {"M-999", "X-109"} & {f.rule_id for f in list(b.flags) + list(h.flags)}
    assert by["Drayvenn"].proposed_mark == pytest.approx(80.3)
    assert by["Kolvani Health"].realized_cumulative == pytest.approx(15.9) and by["Kolvani Health"].proposed_mark == 0.0
    assert by["Hearthwick"].status_after.value == "Acquired" and by["Hearthwick"].realized_cumulative == pytest.approx(1.2)
    assert by["Tidewell Health"].note_at_cost == 0.0 and by["Tidewell Health"].invested_after == pytest.approx(1.4)
    for name in ("Loamfield Robotics", "Harrowgate Bio"):
        c = by[name]
        assert c.fund == "Fund III" and "X-918" in {f.rule_id for f in c.flags} and c.readiness.value == "Blocked"
    g = by["Gryphonel"]
    assert g.proposed_mark == pytest.approx(3.5) and g.readiness.value == "Needs Review"
    assert next(f for f in g.flags if f.rule_id == "X-101").evidence["non_binding"] is True
    assert by["Saffronwell"].readiness.value == "Needs Review" and "X-102" in {f.rule_id for f in by["Saffronwell"].flags}
    assert by["Orchardline"].readiness.value == "Needs Review" and "X-304" in {f.rule_id for f in by["Orchardline"].flags}
    assert by["Zerocrest"].readiness.value == "Ready" and by["Zerocrest"].proposed_mark == 0.0


# ---- the two rule changes, on their own

def test_non_binding_offer_holds_the_mark(tmp_path: Path, cfg):
    pos = position(company="Alpha", latest_post_money=97.0, ownership=0.036, prior_mark=3.5)
    loi = event(EventType.ACQ_ANNOUNCED, detail="Non-binding acquisition letter of intent", value=120.0,
                notes="Non-binding LOI only; no signed definitive agreement.")
    run, _ = run_workbook(make_workbook(tmp_path, [pos], [loi]), cfg)
    c = run.by_company()["Alpha"]
    assert c.proposed_mark == pytest.approx(3.5) and c.readiness.value == "Needs Review"
    f = next(f for f in c.flags if f.rule_id == "X-101")
    assert f.evidence["non_binding"] is True and [s.key for s in f.suggestions] == ["as_proposed", "weighted", "full_value"]
    signed = event(EventType.ACQ_ANNOUNCED, detail="Definitive agreement signed, all cash", value=120.0,
                   notes="Expected to close in Q3, subject to regulatory approval.")
    run2, _ = run_workbook(make_workbook(tmp_path, [pos], [signed], name="b.xlsx"), cfg)
    assert run2.by_company()["Alpha"].proposed_mark == pytest.approx(0.9 * 0.036 * 120 + 0.1 * 3.5)


def test_first_investment_filed_as_a_priced_round_creates_the_position(tmp_path: Path, cfg):
    book = [position(company="Alpha")]
    first = event(company="Newco", detail="Seed", value=15.3, hc_investment=1.5, ownership_after=0.072,
                  notes="Initial HC investment; company absent from opening holdings. Fund III; sector SaaS.")
    run, issues = run_workbook(make_workbook(tmp_path, book, [first]), cfg)
    assert "X-901" not in {i.rule_id for i in issues}
    assert any(i.rule_id == "X-912" and "initial investment" in i.message for i in issues)
    c = run.by_company()["Newco"]
    assert c.proposed_mark == pytest.approx(0.072 * 15.3) and c.invested_after == pytest.approx(1.5) and c.fund == "Fund III"
    assert "X-918" in {f.rule_id for f in c.flags} and c.readiness.value == "Blocked"
    # without HC's cheque it is still a round on a company nobody holds: refused
    stray = event(company="Newco", detail="Seed", value=15.3, ownership_after=0.072, notes="Round led by others.")
    _, issues2 = run_workbook(make_workbook(tmp_path, book, [stray], name="b.xlsx"), cfg)
    assert "X-901" in {i.rule_id for i in issues2}
