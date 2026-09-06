"""The rule rationale: why each exception rule exists and why it carries its severity.

`rules/rationale.yaml` is policy documentation the review tool shows beside every flag (the
Rules tab, the flag detail panel, the static report). It is loaded once per run and served
as-is; the only logic here is the check that every flag id the engine can raise has an
entry, which the tests enforce so a new rule cannot ship without its two bullets.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SOURCES = ("brief", "policy")
SEVERITIES = ("BLOCK", "REVIEW", "MONITOR")
REQUIRED = ("id", "name", "family", "severity", "source", "reads", "why_flag", "why_severity")


def rationale_path(root: Path) -> Path:
    return Path(root) / "rules" / "rationale.yaml"


def load_rationale(root: Path) -> dict[str, Any]:
    """`{version, groups: [...], rules: [...]}` exactly as the file has it, validated."""
    p = rationale_path(root)
    if not p.exists():
        return {"version": None, "groups": [], "rules": []}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rules = list(raw.get("rules") or [])
    seen: set[str] = set()
    for r in rules:
        missing = [k for k in REQUIRED if not r.get(k)]
        if missing:
            raise ValueError(f"rules/rationale.yaml: {r.get('id', '?')} is missing {', '.join(missing)}")
        if r["source"] not in SOURCES:
            raise ValueError(f"rules/rationale.yaml: {r['id']} source must be one of {SOURCES}")
        sev = r["severity"] if isinstance(r["severity"], list) else [r["severity"]]
        bad = [s for s in sev if s not in SEVERITIES]
        if bad:
            raise ValueError(f"rules/rationale.yaml: {r['id']} has unknown severity {bad}")
        r["severity"] = sev
        if r["source"] == "brief" and not r.get("brief_text"):
            raise ValueError(f"rules/rationale.yaml: {r['id']} is from the brief but quotes no brief_text")
        if r["id"] in seen:
            raise ValueError(f"rules/rationale.yaml: {r['id']} appears twice")
        seen.add(r["id"])
        r["why_flag"] = " ".join(str(r["why_flag"]).split())
        r["why_severity"] = " ".join(str(r["why_severity"]).split())
    return {"version": raw.get("version"), "groups": list(raw.get("groups") or []), "rules": rules}


def rationale_by_id(root: Path) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in load_rationale(root)["rules"]}
