"""The publish gate between the back office and the executive dashboard.

The review dashboard works on the *live* run, which changes every time someone records
an override or a decision. Executives must never see that churn. `publish_run` freezes
the current run — booked marks, overrides, dispositions, manifest — into
`data/published/<quarter>.json` under a named approver, and the executive dashboard
reads only from there. Re-publishing the same quarter replaces the snapshot and keeps
the previous one under `history/` so the audit trail of what executives were shown is
itself preserved.

A run with open BLOCK positions can be published: its status is "proposed" and the
executive view says so. It becomes "final" only when every block has been resolved.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..engine.models import Disposition, ValuationRun
from .exec_view import build_exec_view


def _slug(label: str) -> str:
    m = re.match(r"^\s*Q([1-4])\s+(\d{4})\s*$", label)
    return f"{m.group(2)}Q{m.group(1)}" if m else re.sub(r"[^A-Za-z0-9]+", "_", label)


def published_dir(root: Path) -> Path:
    return Path(root) / "data" / "published"


def _escape(payload: str) -> str:
    return payload.replace("<", "\\u003c")


def publish_run(run: ValuationRun, root: Path, *, approver: str, note: str = "",
                published_at: datetime | None = None) -> dict[str, Any]:
    """Freeze `run` as the executive snapshot for its quarter. Returns the publish record."""
    if not approver or not approver.strip():
        raise ValueError("a publish must carry the name of the person releasing it")
    ts = (published_at or datetime.now(timezone.utc)).replace(microsecond=0)
    open_blocks = [c.company for c in run.companies if c.disposition == Disposition.BLOCK]
    record = {
        "quarter": run.manifest.quarter_label,
        "slug": _slug(run.manifest.quarter_label),
        "published_at": ts.isoformat(),
        "published_by": approver.strip(),
        "note": note.strip(),
        "status": "final" if not open_blocks else "proposed",
        "open_blocks": open_blocks,
        "run_id": run.manifest.run_id,
        "policy_version": run.manifest.policy_version,
        "engine_version": run.manifest.engine_version,
        "input_sha256": run.manifest.input_sha256,
        "booked_nav": run.totals.booked_nav,
    }
    d = published_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{record['slug']}.json"
    if target.exists():
        hist = d / "history"
        hist.mkdir(exist_ok=True)
        prev = json.loads(target.read_text())
        stamp = str(prev.get("publish", {}).get("published_at", "prev")).replace(":", "-")
        target.replace(hist / f"{record['slug']}_{stamp}.json")
    payload = {"publish": record, "run": json.loads(run.model_dump_json())}
    target.write_text(json.dumps(payload, indent=1))
    (d / "latest.json").write_text(json.dumps({"slug": record["slug"], "quarter": record["quarter"]}))
    return record


def list_published(root: Path) -> list[dict[str, Any]]:
    d = published_dir(root)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        if p.name == "latest.json":
            continue
        try:
            out.append(json.loads(p.read_text())["publish"])
        except Exception:  # noqa: BLE001 - a corrupt snapshot is skipped, not fatal
            continue
    return sorted(out, key=lambda r: r["published_at"], reverse=True)


def load_published(root: Path, slug: str | None = None) -> tuple[dict[str, Any], ValuationRun] | None:
    d = published_dir(root)
    if slug is None:
        latest = d / "latest.json"
        if not latest.exists():
            return None
        slug = json.loads(latest.read_text())["slug"]
    p = d / f"{slug}.json"
    if not p.exists():
        return None
    raw = json.loads(p.read_text())
    return raw["publish"], ValuationRun.model_validate(raw["run"])


def exec_payload(root: Path, slug: str | None = None) -> dict[str, Any] | None:
    loaded = load_published(root, slug)
    if loaded is None:
        return None
    record, run = loaded
    view = build_exec_view(run, record)
    view["history"] = [{k: r[k] for k in ("quarter", "slug", "published_at", "published_by", "status", "booked_nav")}
                       for r in list_published(root)]
    return view


def exec_json_script(view: dict[str, Any]) -> str:
    return "<script>window.__HC_EXEC__ = " + _escape(json.dumps(view)) + ";</script>"
