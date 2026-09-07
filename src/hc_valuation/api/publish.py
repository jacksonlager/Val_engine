"""The publish gate between the back office and the executive dashboard.

The review dashboard works on the *live* run, which changes every time someone records
an override or a decision. Executives must never see that churn. `publish_run` freezes
the current run — booked marks, overrides, dispositions, manifest — into
`data/published/<quarter>.json` under a named approver, and the executive dashboard
reads only from there. Re-publishing the same quarter replaces the snapshot and keeps
the previous one under `history/` so the audit trail of what executives were shown is
itself preserved.

Publishing is gated on decisions. A run still carrying a BLOCK ("decision required
before booking") or a REVIEW ("check required to confirm the mark") position is refused
with `PublishBlocked`, which lists every outstanding company and the flags a reviewer
must decide or confirm first. Confirming a REVIEW or deciding a BLOCK is an E-01
override addressed to the flag, after which the position rests at MONITOR and the gate
opens. The one way around it is `require_decisions=False`, which exists for tests and
for a deliberate "proposed" preview from code — the API never passes it, so the button
in the review dashboard cannot publish an undecided book.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..engine.models import Disposition, Readiness, Severity, ValuationRun
from ..fsutil import write_atomically
from .exec_view import build_exec_view

WAITING = {Disposition.BLOCK: "Decision required before booking",
           Disposition.REVIEW: "Check required to confirm the mark"}


def outstanding(run: ValuationRun) -> list[dict[str, Any]]:
    """Every position that is not Ready, with what is holding it and the flags behind that.
    Empty means the gate is open.

    Keyed on readiness rather than disposition: a Blocked position is missing an input and a
    Needs Review one is waiting on judgment, and the release note should say which."""
    out = []
    for c in run.companies:
        if c.readiness is Readiness.READY:
            continue
        addressed = set(c.override.rule_ids_addressed) if c.override else set()
        flags = [f for f in c.flags if f.severity in (Severity.BLOCK, Severity.REVIEW) and f.rule_id not in addressed]
        out.append({"company": c.company, "readiness": c.readiness.value,
                    "disposition": c.disposition.value,
                    "why": (c.provisional_reason if c.readiness is Readiness.BLOCKED and c.provisional_reason
                            else WAITING.get(c.disposition, "waiting on a reviewer")),
                    "proposed_mark": c.proposed_mark, "booked_mark": c.booked_mark,
                    "provisional": c.provisional,
                    "rules": [{"rule_id": f.rule_id, "severity": f.severity.value, "action": f.action} for f in flags]})
    return out


class SecondApproverRequired(ValueError):
    """The publisher is also the approver on this quarter's overrides; a second person must release."""


class PublishBlocked(ValueError):
    """Raised when a run with undecided BLOCK / REVIEW positions is sent to publish."""

    def __init__(self, items: list[dict[str, Any]]):
        self.items = items
        blocks = sum(1 for i in items if i["disposition"] == "BLOCK")
        reviews = len(items) - blocks
        parts = [f"{blocks} BLOCK" if blocks else "", f"{reviews} REVIEW" if reviews else ""]
        super().__init__(f"{len(items)} position(s) still need a decision before the book can be published "
                         f"({' and '.join(p for p in parts if p)}). Decide or confirm each one from the queue first.")


def _slug(label: str) -> str:
    m = re.match(r"^\s*Q([1-4])\s+(\d{4})\s*$", label)
    return f"{m.group(2)}Q{m.group(1)}" if m else re.sub(r"[^A-Za-z0-9]+", "_", label)


def published_dir(root: Path) -> Path:
    return Path(root) / "data" / "published"


def _escape(payload: str) -> str:
    return payload.replace("<", "\\u003c")


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def publish_run(run: ValuationRun, root: Path, *, approver: str, note: str = "",
                published_at: datetime | None = None, require_decisions: bool = True,
                require_second_approver: bool = True) -> dict[str, Any]:
    """Freeze `run` as the executive snapshot for its quarter. Returns the publish record.
    Refuses (PublishBlocked) while any position is BLOCK or REVIEW unless `require_decisions` is
    off, and (SecondApproverRequired) when the publisher approved any of this quarter's overrides
    and `require_second_approver` is on — four eyes at the one place a number leaves the back office."""
    if not approver or not approver.strip():
        raise ValueError("a publish must carry the name of the person releasing it")
    if require_decisions:
        waiting = outstanding(run)
        if waiting:
            raise PublishBlocked(waiting)
    if require_second_approver:
        own = sorted({c.company for c in run.companies if c.override and _norm(c.override.approver) == _norm(approver)})
        if own:
            raise SecondApproverRequired(
                f"{approver.strip()} approved the override on {len(own)} position(s) this quarter "
                f"({', '.join(own[:6])}{'…' if len(own) > 6 else ''}); the release needs a second person's name "
                "(policy publish.require_second_approver).")
    ts = (published_at or datetime.now(timezone.utc)).replace(microsecond=0)
    # "final" means every position was Ready when released. A --proposed release of a book with
    # anything still Needs Review is a proposal, whatever its dispositions say; the two words on
    # the executive dashboard are the only signal a reader has of which they are looking at.
    open_positions = [c.company for c in run.companies if c.readiness is not Readiness.READY]
    open_blocks = [c.company for c in run.companies if c.readiness is Readiness.BLOCKED]
    record = {
        "quarter": run.manifest.quarter_label,
        "slug": _slug(run.manifest.quarter_label),
        "published_at": ts.isoformat(),
        "published_by": approver.strip(),
        "note": note.strip(),
        "status": "final" if not open_positions else "proposed",
        "open_blocks": open_blocks,          # positions with a missing input
        "open_positions": open_positions,    # every position not Ready at release: the reason status is "proposed"
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
    write_atomically(target, json.dumps(payload, indent=1))
    write_atomically(d / "latest.json", json.dumps({"slug": record["slug"], "quarter": record["quarter"]}))
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
