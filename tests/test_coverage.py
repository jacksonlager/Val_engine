"""Structural guarantees: every event type has a handler, every documented rule is
registered, the engine stays pure, and thresholds live in the policy file.

Rule-id and event-type coverage is checked against the registry the engine actually
builds for the measurement date, so an effective-dated rule that is not yet in force
counts as missing.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import openpyxl
import pytest

from conftest import ROOT, WORKBOOK_PATH
from hc_valuation.engine import run as engine_run
from hc_valuation.engine.inputs import EventType

ENGINE_DIR = ROOT / "src" / "hc_valuation" / "engine"
POLICY_DOC = ROOT / "docs" / "valuation-policy.md"
FORBIDDEN_IMPORTS = ("api", "ingest", "connectors", "adjudication", "export", "pipeline")


@pytest.fixture(scope="module")
def registry(cfg):
    return engine_run.build_registry(cfg)


# ---------------------------------------------------------------- (a) event types → handlers

@pytest.mark.parametrize("event_type", [e.value for e in EventType])
def test_every_event_type_has_a_specific_handler(registry, cfg, event_type):
    found = registry.handler_for(event_type, cfg.quarter.measurement_date)
    assert found is not None, event_type
    meta, _ = found
    assert meta.rule_id != "M-999", f"{event_type!r} falls through to the unrecognised-event fallback"
    assert event_type in meta.applies_to


def test_event_types_listed_in_field_definitions_are_all_handled(registry, cfg):
    """The workbook's own Field Definitions tab enumerates the event vocabulary; it must
    not know an event the engine does not."""
    wb = openpyxl.load_workbook(WORKBOOK_PATH, read_only=True, data_only=True)
    rows = {str(r[0]).strip(): str(r[1]) for r in wb["Field Definitions"].iter_rows(values_only=True) if r and r[0] and r[1]}
    wb.close()
    text = rows["Event"].rstrip(".")
    listed = [re.sub(r"^or\s+", "", t.strip()) for t in re.split(r",\s*|\s+or\s+", text) if t.strip()]
    # The Q3 workbook enumerates the eight original types; the engine's vocabulary is a superset
    # (the eight new canonical types have no row in this file). The tab must never name a type
    # the engine does not know.
    unknown = [t for t in listed if t not in {e.value for e in EventType}]
    assert not unknown, f"Field Definitions names event types the engine does not know: {unknown}"
    assert len(listed) >= 8, listed
    covered = registry.covered_event_types(cfg.quarter.measurement_date)
    missing = [t for t in listed if t not in covered]
    assert not missing, f"event types in Field Definitions without a handler: {missing}"


def test_unknown_event_type_falls_to_m999(registry, cfg):
    meta, _ = registry.handler_for("SPAC Merger", cfg.quarter.measurement_date)
    assert meta.rule_id == "M-999"


def test_rule_not_yet_effective_is_not_dispatched(registry):
    from datetime import date
    assert registry.handler_for(EventType.IPO.value, date(2020, 1, 1)) is None


# ---------------------------------------------------------------- (b) documented rule ids

def _documented_rule_ids() -> list[str]:
    return sorted(set(re.findall(r"\bM-\d{3}\b", POLICY_DOC.read_text())))


@pytest.mark.parametrize("rule_id", _documented_rule_ids())
def test_documented_rule_ids_are_registered(registry, rule_id):
    ids = {m.rule_id for m in registry.all()}
    assert rule_id in ids, f"{rule_id} is documented in valuation-policy.md but not registered"


def test_policy_doc_mentions_rules():
    assert len(_documented_rule_ids()) >= 12


# ---------------------------------------------------------------- (c) engine purity

def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((a.name, node.lineno) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * node.level) + (node.module or "")
            out.append((mod, node.lineno))
            out.extend((f"{mod}.{a.name}", node.lineno) for a in node.names)
    return out


@pytest.mark.parametrize("module", sorted(p.name for p in ENGINE_DIR.glob("*.py")))
def test_engine_imports_nothing_impure(module):
    bad = []
    for name, line in _imports(ENGINE_DIR / module):
        parts = name.lstrip(".").split(".")
        if any(part in FORBIDDEN_IMPORTS for part in parts) and (name.startswith(".") or name.startswith("hc_valuation")):
            bad.append(f"{module}:{line} imports {name}")
        if name in ("requests", "httpx", "urllib", "socket", "openpyxl", "yaml"):
            bad.append(f"{module}:{line} imports I/O library {name}")
    assert not bad, "\n".join(bad)


def test_engine_reads_no_clock_or_files():
    """No `datetime.now`, `date.today`, `open(`, `Path(...).read_*` inside engine/."""
    offenders = []
    for path in ENGINE_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
                if name in ("now", "today", "utcnow", "open", "read_text", "read_bytes", "urlopen"):
                    offenders.append(f"{path.name}:{node.lineno} calls {name}()")
    assert not offenders, "\n".join(offenders)


# ---------------------------------------------------------------- (d) no threshold literals

ALLOWED_LITERALS = {0, 1, 1e-9, 1e-12}


def _literal_comparisons(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    hits: list[str] = []

    def is_numeric_literal(n: ast.AST) -> tuple[bool, float | None]:
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return True, n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            ok, v = is_numeric_literal(n.operand)
            return ok, (-v if ok and v is not None else None)
        return False, None

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in (node.left, *node.comparators):
                ok, v = is_numeric_literal(side)
                if ok and v not in ALLOWED_LITERALS:
                    hits.append(f"{path.name}:{node.lineno} compares against literal {v!r}")
    return hits


@pytest.mark.parametrize("module", ["exceptions.py", "marking.py"])
def test_no_numeric_threshold_literals_in_comparisons(module):
    hits = _literal_comparisons(ENGINE_DIR / module)
    assert not hits, "thresholds belong in rules/*.yaml:\n" + "\n".join(hits)


def test_literal_scanner_catches_a_planted_constant(tmp_path):
    src = tmp_path / "planted.py"
    src.write_text("def f(age):\n    if age > 24:\n        return True\n    return age < -0.15\n")
    hits = _literal_comparisons(src)
    assert len(hits) == 2 and "24" in hits[0] and "-0.15" in hits[1]
