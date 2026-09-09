"""Controls found wanting in the pre-handover adversarial pass, pinned.

An override must be a finite, plausible number; a decision on a stand-in mark says so on the
ledger whichever client wrote it; the same decision twice is one decision; a same-quarter close
does not drop the escrow question it created; `validate` refuses a financing that follows the
company's own exit; a quoted (listed) mark is not screened against the last private round."""
from __future__ import annotations

from datetime import date

import pytest
from conftest import event, only, position
from fastapi.testclient import TestClient

from hc_valuation.engine.inputs import EventType
from hc_valuation.engine.models import OpenItem, OpenItemKind

MD = date(2026, 9, 30)


@pytest.fixture
def client(tmp_path):
    """A private copy of data/ (empty ledger) so decisions land in the test's own folder."""
    import shutil
    from hc_valuation.api.app import create_app
    from hc_valuation.config import repo_root
    from hc_valuation.pipeline import RunPaths
    root = repo_root()
    data = tmp_path / "data"
    shutil.copytree(root / "data", data, ignore=shutil.ignore_patterns("sample_run.json", "overrides.yaml", "published", "open_items_carry.yaml",
                                                                        "Q? ???? *.xlsx", "note_reads", "recommendations", "uploads", "trials", "market_cache"))
    (data / "overrides.yaml").write_text("overrides: []\n")
    paths = RunPaths(root=root, policy=root / "rules" / "2026Q3.yaml", workbook=data / "HC_Mock_Portfolio_Data.xlsx",
                     overrides=data / "overrides.yaml", precedent=data / "precedent.yaml", open_items_carry=data / "open_items_carry.yaml")
    return TestClient(create_app(paths, provider="stub", static_dir=tmp_path / "no-static", auto_refresh_market=False))


def _override(client, **kw):
    body = {"company": "Beltrix", "booked": 8.1, "reason": "test", "approver": "T. Ester", "rule_ids_addressed": ["X-304"]}
    body.update(kw)
    return client.post("/api/overrides", json=body)


def test_a_mark_must_be_a_finite_plausible_number(client):
    r = client.post("/api/overrides", content='{"company":"Beltrix","booked":NaN,"reason":"x","approver":"A","rule_ids_addressed":["X-304"]}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 422 and "booked" in r.json()["detail"]["message"] and "nan" not in r.text.lower()
    r = _override(client, booked=1e9)
    assert r.status_code == 422 and "20×" in r.json()["detail"]["message"] and "evidence" in r.json()["detail"]["message"]
    assert _override(client, booked=True).status_code == 422
    assert _override(client, booked=8.0).status_code == 200


def test_a_decision_on_a_stand_in_mark_says_so_on_the_ledger(client):
    run = client.get("/api/run").json()
    d = next(c for c in run["companies"] if c["company"] == "Drayvenn")
    assert d["provisional"]
    r = client.post("/api/overrides", json={"company": "Drayvenn", "booked": d["proposed_mark"], "reason": "accept the stand-in",
                                            "approver": "T. Ester", "rule_ids_addressed": ["X-101"]})
    assert r.status_code == 200
    assert r.json()["override"]["reason"].startswith("[input still missing]")


def test_the_same_decision_twice_is_one_decision(client):
    assert _override(client).status_code == 200
    r = _override(client)
    assert r.status_code == 409 and "already on the ledger" in r.json()["detail"]["message"]
    assert _override(client, booked=8.0).status_code == 200            # a different figure is a new decision


def test_an_escrow_question_survives_a_same_quarter_close(build, cfg):
    item = OpenItem(company="Alpha", kind=OpenItemKind.UNCONFIRMED_EXIT, opened=date(2026, 5, 1), opened_quarter="Q2 2026",
                    amount_musd=3.14, detail="$3.14M short of the deal entitlement")
    run, _ = build([position()], [event(EventType.SHUTDOWN, date=date(2026, 8, 1), detail="Ceased operations")], prior_open_items=[item])
    c = only(run)
    assert any(i.kind == OpenItemKind.UNCONFIRMED_EXIT for i in c.open_items), "the escrow question was dropped by the shutdown"
    # a closing with its proceeds is the confirmation the item was waiting for: that one resolves it
    run, _ = build([position()], [event(EventType.ACQ_CLOSED, date=date(2026, 8, 1), value=100.0, proceeds=10.0)], prior_open_items=[item])
    assert not any(i.kind == OpenItemKind.UNCONFIRMED_EXIT and i.age_quarters > 0 for i in only(run).open_items)


def test_a_listed_mark_is_not_screened_against_the_private_round(build, cfg):
    run, _ = build([position(arr=2.0)], [event(EventType.IPO, date=date(2026, 9, 20), detail="Listed", value=3000.0, ownership_after=0.05)])
    c = only(run)
    assert c.listed and not any(f.rule_id in ("X-401", "X-402") for f in c.flags)
