"""E-09 decisions: reject, accept once, promote — and the precedent ledger behind them.

    record_decision(paths, proposal_id, decision, approver, reason, booked=None, effective_from=None)

* `reject`      — recorded only; the position falls back to a manual override.
* `accept_once` — an E-01 `OverrideRecord` is appended to `data/overrides.yaml` with the
                  proposal as its documented reason. No rule is created: accept-once is
                  deliberately cheaper than promote so the low-friction path cannot
                  silently create policy.
* `promote`     — the proposal becomes a `CustomRuleSpec` with a named approver and an
                  `effective_from`. It is written to the NEXT quarter's policy file
                  (`rules/<next>.yaml`, created with `inherits:` if absent) so the policy
                  diff between quarters is the audit trail, AND appended to the current
                  policy's `custom_rules` so the run that raised the block can clear it.
                  Rationale for the double write: the current file is the only policy the
                  current run reads, and `effective_from` (default: the current quarter's
                  window start) is what guarantees prior quarters stay unchanged. The
                  current policy's version string is left for a human to bump — a
                  promotion is a policy change and the commit that carries it should say so.

Every decision lands in `data/precedent.yaml` (`decisions:` list plus a per-signature
`precedents:` map with `repeat_count`), and `suggest_promotion` reads that count against
`adjudication.promote_after_repeats`. Nothing here touches `engine/`.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from ..config import CustomRuleSpec, RuleConfig, load_config
from ..engine.run import build_registry
from . import load_proposal, proposal_path, save_proposal
from .schema import Decision, TreatmentProposal, to_custom_rule_spec

PROMOTED_RULE_PREFIX = "M-1"          # M-1xx is reserved for promoted precedents
PROMOTED_RULE_FIRST = 100
_QUARTER_RX = re.compile(r"^\s*Q([1-4])\s+(\d{4})\s*$")


# ---------------------------------------------------------------- yaml helpers

class _PlainDumper(yaml.SafeDumper):
    """No `&id001` anchors: a policy file is read by people, and the same date appearing twice
    (window_end == measurement_date) is a fact, not a reference."""

    def ignore_aliases(self, data: Any) -> bool:  # noqa: D401
        return True


def _dump(data: dict[str, Any]) -> str:
    return yaml.dump(data, Dumper=_PlainDumper, sort_keys=False, allow_unicode=True, default_flow_style=False)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not Path(path).exists():
        return {}
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, data: dict[str, Any], header: str = "") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text((header + "\n" if header else "") + _dump(data), encoding="utf-8")


def _spec_dict(spec: CustomRuleSpec) -> dict[str, Any]:
    return spec.model_dump(mode="python")


def _replace_top_level_block(text: str, key: str, block: str) -> str:
    """Swap one top-level YAML mapping block by text so the file's comments survive."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(key)}\s*:", ln)), None)
    if start is None:
        sep = "" if (not lines or lines[-1].strip() == "") else "\n"
        return text.rstrip("\n") + "\n" + sep + block.rstrip("\n") + "\n"
    end = start + 1
    while end < len(lines) and not re.match(r"^[A-Za-z_][\w\-]*\s*:", lines[end]):
        end += 1
    new = lines[:start] + block.rstrip("\n").splitlines() + lines[end:]
    return "\n".join(new).rstrip("\n") + "\n"


def append_custom_rule(policy_path: Path, spec: CustomRuleSpec) -> None:
    """Append a spec to `custom_rules:` in an existing policy file, preserving its comments."""
    raw = _read_yaml(policy_path)
    existing = list(raw.get("custom_rules") or [])
    if any(r.get("rule_id") == spec.rule_id for r in existing):
        raise ValueError(f"{policy_path.name} already carries rule {spec.rule_id}")
    existing.append(_spec_dict(spec))
    block = _dump({"custom_rules": existing})
    policy_path.write_text(_replace_top_level_block(policy_path.read_text(encoding="utf-8"), "custom_rules", block), encoding="utf-8")


# ---------------------------------------------------------------- quarters

def next_quarter(label: str) -> tuple[str, str, dict[str, date]]:
    """('Q4 2026', '2026Q4', {window dates}) for the quarter after `label`."""
    m = _QUARTER_RX.match(label)
    if not m:
        raise ValueError(f"cannot derive the next quarter from label {label!r}; expected 'Q<n> <year>'")
    q, y = int(m.group(1)), int(m.group(2))
    nq, ny = (q + 1, y) if q < 4 else (1, y + 1)
    start = date(ny, 3 * (nq - 1) + 1, 1)
    after = date(ny + 1, 1, 1) if nq == 4 else date(ny, 3 * nq + 1, 1)   # first day of the quarter after next
    end = after - timedelta(days=1)
    prior_close = start - timedelta(days=1)
    return f"Q{nq} {ny}", f"{ny}Q{nq}", {"measurement_date": end, "prior_close": prior_close, "window_start": start, "window_end": end}


def next_policy_file(cfg: RuleConfig, current: Path) -> tuple[Path, str, dict[str, date]]:
    label, compact, window = next_quarter(cfg.quarter.label)
    return current.parent / f"{compact}.yaml", label, window


def next_rule_id(cfg: RuleConfig, *policy_files: Path) -> str:
    taken = {m.rule_id for m in build_registry(cfg).all()}
    for p in policy_files:
        taken |= {r.get("rule_id") for r in (_read_yaml(p).get("custom_rules") or [])}
    n = PROMOTED_RULE_FIRST
    while f"M-{n}" in taken:
        n += 1
    return f"M-{n}"


# ---------------------------------------------------------------- precedent

def _precedent(paths) -> dict[str, Any]:
    raw = _read_yaml(paths.precedent)
    raw.setdefault("decisions", [])
    raw.setdefault("precedents", {})
    return raw


def _record_precedent(paths, proposal: TreatmentProposal, decision: Decision, approver: str, reason: str,
                      decided_at: datetime, **extra: Any) -> dict[str, Any]:
    raw = _precedent(paths)
    raw["decisions"].append({
        "proposal_id": proposal.proposal_id, "signature": proposal.event_signature, "event_type": proposal.event_type,
        "company": proposal.company, "quarter": proposal.quarter_label, "analogue_rule_id": proposal.analogue_rule_id,
        "formula": proposal.formula, "decision": decision, "approver": approver, "reason": reason,
        "decided_at": decided_at.isoformat(), **extra,
    })
    entry = raw["precedents"].setdefault(proposal.event_signature, {
        "repeat_count": 0, "reject_count": 0, "promoted": False, "rule_id": None,
        "analogue_rule_id": proposal.analogue_rule_id, "formula": proposal.formula, "last_decision": None,
    })
    if decision in ("accept_once", "promote"):
        entry["repeat_count"] = int(entry.get("repeat_count", 0)) + 1
    else:
        entry["reject_count"] = int(entry.get("reject_count", 0)) + 1
    if decision == "promote":
        entry["promoted"] = True
        entry["rule_id"] = extra.get("rule_id")
    entry["last_decision"] = decision
    entry["last_decided_at"] = decided_at.isoformat()
    _write_yaml(paths.precedent, raw, "# E-09 precedent ledger: every adjudication decision, and repeat counts per event signature.")
    return entry


def suggest_promotion(paths, signature: str, cfg: RuleConfig) -> bool:
    """True once the same treatment has been accepted `promote_after_repeats` times and no rule
    exists yet — by then it is a pattern, not a guess."""
    entry = _precedent(paths)["precedents"].get(signature)
    if not entry or entry.get("promoted"):
        return False
    return int(entry.get("repeat_count", 0)) >= cfg.adjudication.promote_after_repeats


# ---------------------------------------------------------------- decisions

def record_decision(paths, proposal_id: str, decision: Decision, approver: str, reason: str,
                    booked: float | None = None, effective_from: date | None = None,
                    rule_id: str | None = None, decided_at: datetime | None = None) -> dict[str, Any]:
    if decision not in ("accept_once", "promote", "reject"):
        raise ValueError(f"unknown decision {decision!r}")
    if not approver or not approver.strip():
        raise ValueError("a decision needs a named approver")
    cfg = load_config(paths.policy)
    path = proposal_path(paths.proposals_dir, proposal_id)
    if not path.exists():
        raise FileNotFoundError(f"no proposal {proposal_id} under {paths.proposals_dir}")
    proposal = load_proposal(path, cfg)
    # A pending proposal takes any decision. An accepted-once proposal may still be PROMOTED
    # later — "accept now, promote once it is a pattern" is the intended path. Nothing else
    # is re-decidable: promoted and rejected are final (edit the policy file / re-propose instead).
    if proposal.status == "pending":
        pass
    elif proposal.status == "accepted_once" and decision == "promote":
        pass
    else:
        raise ValueError(f"proposal {proposal_id} is already {proposal.status}; only accept_once → promote is allowed")
    when = decided_at or datetime.now(timezone.utc).replace(microsecond=0)
    out: dict[str, Any] = {"proposal_id": proposal_id, "company": proposal.company, "decision": decision,
                           "approver": approver, "files_written": []}
    extra: dict[str, Any] = {}

    if decision == "accept_once":
        if booked is None:
            raise ValueError("accept_once needs the booked mark the committee agreed (the engine will not compute one from a draft)")
        raw = _read_yaml(paths.overrides)
        records = list(raw.get("overrides") or [])
        records.append({
            "company": proposal.company, "quarter": proposal.quarter_label,
            "proposed": float(proposal.proposed_mark_at_proposal), "booked": float(booked),
            "reason": (f"E-09 accept-once of proposal {proposal_id} (analogue {proposal.analogue_rule_id}, formula "
                       f"'{proposal.formula}'): {proposal.rationale} Committee: {reason}"),
            "approver": approver, "created_at": when.date().isoformat(),
            "rule_ids_addressed": ["M-999"], "source_proposal": proposal_id,
        })
        raw["overrides"] = records
        _write_yaml(paths.overrides, raw, "# E-01 committee override ledger. booked = override.booked ?? proposed. Never edits a proposal.")
        out["files_written"].append(str(paths.overrides))
        out["override"] = records[-1]
        extra["booked"] = float(booked)
        status = "accepted_once"

    elif decision == "promote":
        eff = effective_from or cfg.quarter.window_start
        nxt_path, nxt_label, window = next_policy_file(cfg, Path(paths.policy))
        rid = rule_id or next_rule_id(cfg, Path(paths.policy), nxt_path)
        spec = to_custom_rule_spec(proposal, approver=approver, effective_from=eff, rule_id=rid)
        if nxt_path.exists():
            append_custom_rule(nxt_path, spec)
        else:
            current_rules = list(_read_yaml(paths.policy).get("custom_rules") or [])
            _write_yaml(nxt_path, {
                "policy_version": f"{nxt_path.stem}-0.1",
                "inherits": Path(paths.policy).name,
                "quarter": {"label": nxt_label, **window},
                "custom_rules": current_rules + [_spec_dict(spec)],
            }, header=(f"# HC Valuation Engine — policy {nxt_path.stem}. Inherits {Path(paths.policy).name}; "
                       "carries only what changed.\n# custom_rules must be the FULL list: a child list replaces the parent's."))
        append_custom_rule(Path(paths.policy), spec)
        load_config(paths.policy)   # prove the edited policy still validates before we claim success
        load_config(nxt_path)
        out["files_written"] += [str(nxt_path), str(paths.policy)]
        out["rule"] = _spec_dict(spec)
        extra["rule_id"] = rid
        extra["effective_from"] = eff.isoformat()
        status = "promoted"

    else:
        status = "rejected"

    entry = _record_precedent(paths, proposal, decision, approver, reason, when, **extra)
    out["files_written"].append(str(paths.precedent))
    out["precedent"] = entry
    out["suggest_promotion"] = suggest_promotion(paths, proposal.event_signature, cfg)

    updated = proposal.with_decision(status, {"decision": decision, "approver": approver, "reason": reason,
                                              "decided_at": when.isoformat(), **extra})
    save_proposal(path, updated)
    out["status"] = status
    out["files_written"].append(str(path))
    return out


__all__ = ["append_custom_rule", "next_quarter", "next_rule_id", "record_decision", "suggest_promotion"]
