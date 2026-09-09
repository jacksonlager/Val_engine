"""The `synthetic` comps provider: invented multiples that cannot be mistaken for observed ones.

Four properties (connectors/synthetic.py): the file declares itself, every value is labelled,
nothing is written to any cache, and the engine treats the source as not observed.
"""
from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from hc_valuation.config import load_config, repo_root
from hc_valuation.connectors import assemble_market_data, resolve_provider
from hc_valuation.connectors.cache import CACHE_DIR
from hc_valuation.connectors.synthetic import (SYNTHETIC_DIR, SYNTHETIC_NOTICE, SYNTHETIC_SOURCE, SyntheticCompsProvider,
                                               SyntheticDataError, synthetic_file)
from hc_valuation.ingest.reader import read_workbook
from hc_valuation.pipeline import RunPaths, execute

ROOT = repo_root()
AS_OF = date(2026, 9, 30)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A scratch root with the fixtures the stub needs and one synthetic file for the Q3 date."""
    (tmp_path / "rules").mkdir()
    shutil.copy(ROOT / "rules" / "2026Q3.yaml", tmp_path / "rules" / "2026Q3.yaml")
    shutil.copy(ROOT / "rules" / "comps_baskets.yaml", tmp_path / "rules" / "comps_baskets.yaml")
    shutil.copytree(ROOT / "data" / "mock_responses", tmp_path / "data" / "mock_responses")
    f = synthetic_file(tmp_path, AS_OF)
    f.parent.mkdir(parents=True)
    f.write_text(yaml.safe_dump({
        "synthetic": True, "warning": "TEST", "as_of": AS_OF.isoformat(),
        "sectors": {"AI/ML": {"history": {"2026-06": 20.0, "2026-09": 24.0}},
                    "Fintech": {"history": {"2026-06": 9.0, "2026-09": 8.0}}},
    }))
    return tmp_path


def _assemble(root: Path, provider: str):
    cfg = load_config(root / "rules" / "2026Q3.yaml")
    snapshot, feed = read_workbook(ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx", cfg)
    return assemble_market_data(cfg, root, snapshot, feed, provider=provider)


def test_synthetic_is_a_registered_provider():
    assert resolve_provider("synthetic") == "synthetic"


def test_every_value_is_labelled_synthetic(root: Path):
    asm = _assemble(root, "synthetic")
    market, label = asm
    assert label == SYNTHETIC_SOURCE and label.startswith("synthetic:")
    assert set(market.comps) == {"AI/ML", "Fintech"}
    assert all(c.source.startswith("synthetic:") for c in market.comps.values())
    assert market.comps["AI/ML"].ev_to_arr == 24.0 and market.comps["AI/ML"].source == f"{SYNTHETIC_SOURCE}@2026-09"
    rep = asm.report
    assert rep["provider"] == "synthetic" and rep["synthetic"] is True and rep["reached_live"] is False
    assert rep["notice"] == "TEST" and rep["cache"] is None and rep["fetched_at"] is None
    assert all(s["synthetic"] is True and s["live"] is False and s["constituents"] == [] for s in rep["sectors"])
    assert all(s["source"].startswith("synthetic:") for s in rep["sectors"])


def test_file_without_the_marker_is_refused_and_the_fixture_answers(root: Path):
    f = synthetic_file(root, AS_OF)
    raw = yaml.safe_load(f.read_text())
    raw.pop("synthetic")
    f.write_text(yaml.safe_dump(raw))
    with pytest.raises(SyntheticDataError):
        SyntheticCompsProvider(f)
    asm = _assemble(root, "synthetic")
    assert asm.label == "stub" and asm.report["provider"] == "synthetic" and asm.report["source"] == "stub"
    assert any("refused" in e for e in asm.report["errors"])
    assert all(c.source.startswith("fixture:") for c in asm.market.comps.values())


def test_missing_file_means_the_fixture_answers_and_says_so(tmp_path: Path):
    (tmp_path / "rules").mkdir()
    shutil.copy(ROOT / "rules" / "2026Q3.yaml", tmp_path / "rules" / "2026Q3.yaml")
    shutil.copytree(ROOT / "data" / "mock_responses", tmp_path / "data" / "mock_responses")
    asm = _assemble(tmp_path, "synthetic")
    assert asm.label == "stub"
    assert any("no data/synthetic_market/2026-09-30.yaml" in e for e in asm.report["errors"])


def test_nothing_is_written_to_any_cache(root: Path, monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    before = sorted(p.as_posix() for p in root.rglob("*"))
    _assemble(root, "synthetic")
    assert sorted(p.as_posix() for p in root.rglob("*")) == before
    assert not (root / CACHE_DIR).exists()
    assert not (home / ".cache").exists()


def test_the_engine_never_calibrates_to_or_screens_against_synthetic_multiples(root: Path):
    paths = RunPaths.default(root=root, workbook=ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx",
                             policy=root / "rules" / "2026Q3.yaml")
    r = execute(paths, provider="synthetic", generated_at=datetime(2026, 9, 30))
    assert r.run.manifest.market_data_source == SYNTHETIC_SOURCE
    # M-080 requires an observed (live:) history; the synthetic one must not produce a calibrated alternative
    assert not any("calibrated" in c.alternative_marks for c in r.run.companies)
    assert not any(s.rule_id == "M-080" for c in r.run.companies for s in c.steps)
    # X-401/X-402 in relative_to_comps mode with require_live_comps fall back to the absolute bounds
    screened = [f for c in r.run.companies for f in c.flags if f.rule_id in ("X-401", "X-402")]
    assert screened, "the Q3 book has multiple-screen findings; the synthetic run must too"
    assert all(f.evidence["basis"] == "absolute policy bound" for f in screened)
    # and the identity of the run says which source it was marked against
    stub = execute(paths, provider="stub", generated_at=datetime(2026, 9, 30))
    assert stub.run.manifest.run_id != r.run.manifest.run_id


def test_generator_writes_a_declared_file_the_provider_accepts(tmp_path: Path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_synthetic_market", ROOT / "scripts" / "make_synthetic_market.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    payload = mod.build(date(2027, 3, 31))
    assert payload["synthetic"] is True and payload["warning"] == SYNTHETIC_NOTICE
    assert "2027-03" in payload["sectors"]["AI/ML"]["history"]
    f = tmp_path / "x.yaml"
    f.write_text(yaml.safe_dump(payload))
    p = SyntheticCompsProvider(f)
    assert p.sector_multiples(date(2027, 3, 31))["AI/ML"].source.startswith("synthetic:")
    # the committed files for the three test quarters are exactly what the script writes
    for q in ("2026-12-31", "2027-03-31", "2027-06-30"):
        committed = yaml.safe_load((ROOT / SYNTHETIC_DIR / f"{q}.yaml").read_text())
        assert committed == mod.build(date.fromisoformat(q)), q
