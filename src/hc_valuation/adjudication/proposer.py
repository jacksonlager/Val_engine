"""Proposers: build a context packet for a novel event and draft a `TreatmentProposal`.

Two implementations share one contract, `Proposer.propose(packet)`:

* `StubProposer` — deterministic keyword heuristics mapping an unrecognised event type to
  the closest existing rule. It is the default, needs no network, and is what the
  `ClaudeProposer` falls back to.
* `ClaudeProposer` — asks a Claude model for JSON matching the schema, under a system
  prompt that carries the policy's six adjudicator constraints. It is used only when an
  API key is present, parses the reply strictly, and on *any* failure returns the stub's
  draft with `provenance.model = "stub-fallback"`. It never raises out of `propose`.

Neither produces a mark. Both produce a rule the engine may later compute with.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..config import RuleConfig
from ..engine.inputs import Event, Position
from ..engine.models import CompanyResult, Severity
from ..engine.registry import Registry
from .schema import Provenance, TreatmentProposal, catalogue_version_for, now_utc, validation_scope

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-5"

CONSTRAINTS = (
    "1. Never produce a mark. Propose a rule — a formula — and the deterministic engine computes the number.",
    "2. Formulas are a restricted expression language over a field whitelist: only the allowed fields, numeric "
    "literals, the allowed operators and min/max. Never code, never a function you invent.",
    "3. There is no auto-accept at any confidence. Confidence is displayed only; it gates nothing.",
    "4. You run at ingest, outside run_valuation. Your draft is cached by event signature so re-runs reproduce.",
    "5. Promotion goes through git with a named approver and must leave prior quarters unchanged.",
    "6. You are optional. If you cannot answer, the position stays blocked under M-999 exactly as before.",
)


# ---------------------------------------------------------------- packet

@dataclass(frozen=True)
class ContextPacket:
    """Everything a proposer may look at. Assembled once per novel event, serialisable."""
    event: dict[str, Any]
    position: dict[str, Any] | None
    prior_result: dict[str, Any]
    catalogue: list[dict[str, Any]]
    marking: dict[str, Any]
    principles: list[str]
    allowed_fields: list[str]
    allowed_operators: list[str]
    policy_version: str
    catalogue_version: str
    quarter_label: str
    news: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ROW_RX = re.compile(r"^\|\s*\*\*(M-\d{3})\*\*\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")
_PRINCIPLE_RX = re.compile(r"^\d+\.\s+\*\*(.+?)\*\*\s*(.*)$")


def policy_markdown_catalogue(policy_md: Path | None) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Pull the M-rule formula/notes table and the design principles out of the policy
    markdown. Best-effort: a missing or reshaped document yields empty extras, never an error."""
    if policy_md is None or not policy_md.exists():
        return {}, []
    rules: dict[str, dict[str, str]] = {}
    principles: list[str] = []
    in_principles = False
    for raw in policy_md.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_principles = "design principles" in line.lower()
            continue
        m = _ROW_RX.match(line)
        if m:
            rid, name, formula, notes = m.groups()
            rules[rid] = {"name": name, "formula": formula.replace("`", ""), "notes": notes}
        elif in_principles:
            pm = _PRINCIPLE_RX.match(line)
            if pm:
                principles.append(f"{pm.group(1)} {pm.group(2)}".strip())
    return rules, principles


def build_packet(event: Event, position: Position | None, prior: CompanyResult, cfg: RuleConfig,
                 registry: Registry, policy_md: Path | None, news: list[dict[str, Any]] | None = None) -> ContextPacket:
    md_rules, principles = policy_markdown_catalogue(policy_md)
    catalogue = []
    for m in registry.all():
        entry = {"rule_id": m.rule_id, "version": m.version, "applies_to": list(m.applies_to),
                 "severity": m.severity.value if m.severity else None, "terminal": m.terminal,
                 "tier": m.tier, "source": m.source, "description": m.description}
        entry.update(md_rules.get(m.rule_id, {}))
        catalogue.append(entry)
    return ContextPacket(
        event=event.model_dump(mode="json"),
        position=position.model_dump(mode="json") if position else None,
        prior_result={"prior_mark": prior.prior_mark, "proposed_mark": prior.proposed_mark, "ownership_before": prior.ownership_before,
                      "latest_post_money": prior.latest_post_money, "note_at_cost": prior.note_at_cost,
                      "flags": [f.rule_id for f in prior.flags], "disposition": prior.disposition.value},
        catalogue=catalogue,
        marking=cfg.marking.model_dump(mode="json"),
        principles=principles,
        allowed_fields=list(cfg.adjudication.allowed_fields),
        allowed_operators=list(cfg.adjudication.allowed_operators),
        policy_version=cfg.policy_version,
        catalogue_version=catalogue_version_for(cfg.policy_version, registry),
        quarter_label=cfg.quarter.label,
        news=list(news or []),
    )


# ---------------------------------------------------------------- protocol

class Proposer(Protocol):
    name: str

    def propose(self, packet: ContextPacket) -> TreatmentProposal: ...


# ---------------------------------------------------------------- stub

@dataclass(frozen=True)
class _Heuristic:
    keywords: tuple[str, ...]
    analogue: str
    formula: str
    severity: Severity
    kind: str
    parameter_map: dict[str, str]
    rationale: str
    missing_facts: tuple[str, ...]
    confidence: float


HEURISTICS: tuple[_Heuristic, ...] = (
    _Heuristic(("spac", "listing", "direct listing", "de-spac", "reverse merger"), "M-040", "ownership_after * deal_value",
               Severity.BLOCK, "reuse", {"ownership_after": "HC Ownership After (FD %)", "deal_value": "Post-Money / Deal Value ($M)"},
               "A SPAC merger or direct listing produces a listed security, the same outcome as an IPO: mark at post-combination "
               "ownership × market capitalisation, move to Level 1, and hold the position for a reviewer's ratification as M-040 does. "
               "Until a measurement-date close exists the deal value stands in for market cap.",
               ("measurement-date closing market cap (not the announced pro-forma value)", "redemption rate and resulting post-combination share count",
                "lock-up terms and any earn-out/sponsor promote that dilutes HC", "whether the combination has actually closed"),
               0.62),
    _Heuristic(("bankrupt", "chapter", "liquidat", "insolven", "receivership", "assignment for the benefit"), "M-021", "0",
               Severity.REVIEW, "reuse", {},
               "A bankruptcy or liquidation is terminal for common and preferred equity in almost every case; treat as a shutdown: "
               "mark to zero, book any residual distribution to realized, status Shut Down.",
               ("expected recovery to HC's class after senior claims", "whether HC holds debt or notes ranking ahead of equity",
                "timing of any residual distribution"),
               0.7),
    _Heuristic(("earn-out", "earnout", "escrow", "holdback", "deferred consideration", "contingent consideration"), "M-020", "proceeds",
               Severity.REVIEW, "reuse", {"proceeds": "Proceeds to HC ($M)"},
               "Contingent or deferred consideration on an exit: cash received is realized under M-020; the contingent portion is a "
               "receivable whose value depends on facts the schema cannot see. Carry only the amount actually received until the "
               "a reviewer sets a probability-weighted receivable.",
               ("face value and conditions of the escrow / earn-out", "probability of release and expected date", "any indemnity claims against the escrow"),
               0.6),
    _Heuristic(("warrant", "option", "rights offering", "side letter"), "M-060", "prior_mark + hc_investment",
               Severity.REVIEW, "reuse", {"prior_mark": "prior equity mark", "hc_investment": "HC Investment ($M)"},
               "A warrant, option or similar instrument is not a price for the underlying equity. As with a convertible note (M-060), "
               "leave the equity mark unchanged and carry HC's new money, if any, at cost as a separate leg.",
               ("strike price and expiry", "whether the instrument was exercised or funded", "the fully diluted share count it converts into"),
               0.55),
    _Heuristic(("tender", "buyback", "repurchase", "structured secondary"), "M-030", "ownership_after * post_money",
               Severity.REVIEW, "reuse", {"ownership_after": "HC Ownership After (FD %)", "post_money": "last round post-money"},
               "A tender or company buyback is a secondary sale of part of the position: proceeds to realized, remainder marked on the "
               "configured basis (M-030), with the spread to the last round flagged.",
               ("price per share paid vs the last round", "share of the position sold", "whether the buyer was the company or a third party"),
               0.6),
    _Heuristic(("dividend", "distribution", "recapitalization dividend", "return of capital"), "M-000", "prior_mark",
               Severity.REVIEW, "reuse", {"prior_mark": "prior equity mark"},
               "A cash distribution does not reprice the equity; it is realized proceeds against an unchanged mark (carry forward, M-000, "
               "with the cash booked to realized). Confirm whether it reduces the cost basis or the carrying value.",
               ("amount received by HC", "whether it is a return of capital (reduces basis) or income", "any preference paid down"),
               0.55),
)

UNKNOWN = _Heuristic((), "M-999", "prior_mark", Severity.BLOCK, "new_rule", {"prior_mark": "prior equity mark"},
                     "No existing rule is a close analogue. Hold the mark unchanged and keep the position blocked until a reviewer "
                     "defines the treatment; do not absorb a genuinely new instrument into a rule it superficially resembles.",
                     ("what instrument or transaction this actually is", "whether it changes HC's ownership, liquidity or seniority",
                      "the facts a marking rule would need (price, ownership after, proceeds)"),
                     0.2)


class StubProposer:
    """Deterministic: the same packet always yields the same draft (modulo `created_at`)."""

    name = "stub"

    def __init__(self, label: str = "stub-heuristics") -> None:
        self.label = label

    def match(self, event_type: str, detail: str, notes: str) -> _Heuristic:
        text = f"{event_type} {detail} {notes}".lower()
        for h in HEURISTICS:
            if any(k in text for k in h.keywords):
                return h
        return UNKNOWN

    def propose(self, packet: ContextPacket) -> TreatmentProposal:
        ev = packet.event
        h = self.match(ev.get("event_type", ""), ev.get("detail", ""), ev.get("notes", ""))
        prompt_sha = hashlib.sha256(json.dumps([h.keywords, h.analogue, h.formula], sort_keys=True).encode()).hexdigest()
        return TreatmentProposal(
            event_signature=_signature_of(ev), event_type=ev["event_type"], company=ev["company"],
            event_row_index=int(ev["row_index"]), quarter_label=packet.quarter_label,
            proposed_mark_at_proposal=float(packet.prior_result["proposed_mark"]),
            analogue_rule_id=h.analogue, proposed_kind=h.kind, formula=h.formula, parameter_map=dict(h.parameter_map),
            suggested_severity=h.severity, rationale=h.rationale, missing_facts=list(h.missing_facts), confidence=h.confidence,
            briefing=_stub_briefing(ev, h),
            provenance=Provenance(model=self.label, prompt_sha256=prompt_sha, catalogue_version=packet.catalogue_version,
                                  created_at=now_utc()),
        )


def _stub_briefing(ev: dict[str, Any], h: _Heuristic) -> dict[str, str]:
    """The heuristic's draft in a reviewer's words. Generic by construction: the stub knows keywords,
    not the case, and says so."""
    what = f"The row records a '{ev.get('event_type', '')}' ({ev.get('detail', '') or 'no detail'}) on {ev.get('date', '')}."
    if h is UNKNOWN:
        return {
            "what_happened": what,
            "why_no_rule": "No marking rule is written for this event type and none of the built-in analogues matched the wording.",
            "what_it_means": "The engine has not changed the mark; whether this event changes what a market participant would pay for HC's position is undetermined until a person reads it.",
            "suggested_course": "Hold the mark and keep the position blocked; decide the treatment as a reviewer override, or define a rule if the case will recur.",
            "what_to_check": "; ".join(h.missing_facts) + ".",
        }
    return {
        "what_happened": what,
        "why_no_rule": f"No marking rule is written for this event type; the wording resembles cases handled by {h.analogue}.",
        "what_it_means": h.rationale,
        "suggested_course": f"Treat it as {h.analogue} would ({h.formula}), once the facts below are confirmed; the number comes from the engine, not from this draft.",
        "what_to_check": "; ".join(h.missing_facts) + ".",
    }


def _signature_of(ev: dict[str, Any]) -> str:
    return Event.model_validate(ev).signature


# ---------------------------------------------------------------- claude

SYSTEM_PROMPT = """You are the novel-case adjudicator (E-09) for a venture-portfolio valuation engine.
An event type has no registered marking rule and the position is blocked (M-999). Draft a treatment
proposal for a human reviewer. You are bound by these six constraints:
{constraints}

Reason by analogy from the rule catalogue in the packet. Cite the single closest existing rule as
`analogue_rule_id`. Write `formula` using ONLY the allowed fields and operators in the packet. Name
every fact the schema does not contain that a reviewer must supply in `missing_facts` (or exactly
["none"]). `suggested_severity` must be "REVIEW" or "BLOCK". Respond with ONE JSON object and nothing
else, with exactly these keys:
{{"analogue_rule_id": str, "proposed_kind": "reuse"|"new_rule", "formula": str, "parameter_map": {{str: str}},
 "suggested_severity": "REVIEW"|"BLOCK", "rationale": str, "missing_facts": [str], "confidence": float,
 "briefing": {{"what_happened": str, "why_no_rule": str, "what_it_means": str, "suggested_course": str, "what_to_check": str}}}}

`briefing` is for the CFO who reads the card, in plain words, one or two sentences each, no rule ids
and no number to book: what the row says happened; why none of the existing rules covers it; what it
means for the fair value of HC's position (ASC 820: what a market participant would pay today, and
how the event bears on that); the course you suggest and why (consistent with `formula`); what a
person must check before deciding.
"""


class ClaudeProposer:
    """Model-backed proposer. Optional: no key, no SDK, or any failure -> the stub answers."""

    name = "claude"

    # A reply carries a formula, a rationale, the missing facts and five briefing sentences of up
    # to 600 characters each — close to 1,200 tokens on its own, so that cap could cut the JSON
    # mid-briefing and the stub would answer instead, silently. The cap is a ceiling only; the
    # timeout has to let a full reply finish.
    def __init__(self, model: str = DEFAULT_MODEL, fallback: Proposer | None = None, api_key: str | None = None,
                 max_tokens: int = 2500, timeout_s: float = 60.0) -> None:
        self.model = model
        self.fallback = fallback or StubProposer()
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.system_prompt = SYSTEM_PROMPT.format(constraints="\n".join(CONSTRAINTS))
        self.prompt_sha256 = hashlib.sha256(self.system_prompt.encode()).hexdigest()

    @property
    def unavailable_reason(self) -> str | None:
        if not self.api_key:
            return "no model key is set in this environment"
        if importlib.util.find_spec("anthropic") is None:
            return "the anthropic package is not installed for this Python"
        return None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    def _fallback(self, packet: ContextPacket, why: str) -> TreatmentProposal:
        log.warning("claude proposer unavailable (%s); using stub draft", why)
        draft = self.fallback.propose(packet)
        return draft.model_copy(update={"provenance": draft.provenance.model_copy(update={"model": "stub-fallback"})})

    def _call(self, packet: ContextPacket) -> str:
        import anthropic  # optional dependency: the `adjudication` extra
        client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout_s)
        msg = client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=self.system_prompt,
            messages=[{"role": "user", "content": json.dumps(packet.to_dict(), default=str)}],
        )
        return "".join(getattr(block, "text", "") for block in msg.content)

    def propose(self, packet: ContextPacket) -> TreatmentProposal:
        if not self.available:
            return self._fallback(packet, self.unavailable_reason or "unavailable")
        try:
            text = self._call(packet)
            return self.parse(text, packet)
        except Exception as ex:  # noqa: BLE001 — by contract this never raises
            return self._fallback(packet, f"{type(ex).__name__}: {ex}")

    def parse(self, text: str, packet: ContextPacket) -> TreatmentProposal:
        """Strict: one JSON object with exactly the expected keys; the schema does the rest."""
        body = text.strip()
        if body.startswith("```"):
            body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body, flags=re.S)
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("model reply is not a JSON object")
        expected = {"analogue_rule_id", "proposed_kind", "formula", "parameter_map", "suggested_severity",
                    "rationale", "missing_facts", "confidence"}
        if set(data) - {"briefing"} != expected:
            raise ValueError(f"model reply keys {sorted(data)} != {sorted(expected | {'briefing'})}")
        briefing = data.get("briefing") if isinstance(data.get("briefing"), dict) else {}
        ev = packet.event
        return TreatmentProposal(
            event_signature=_signature_of(ev), event_type=ev["event_type"], company=ev["company"],
            event_row_index=int(ev["row_index"]), quarter_label=packet.quarter_label,
            proposed_mark_at_proposal=float(packet.prior_result["proposed_mark"]),
            analogue_rule_id=data["analogue_rule_id"], proposed_kind=data["proposed_kind"], formula=data["formula"],
            parameter_map={str(k): str(v) for k, v in dict(data["parameter_map"]).items()},
            suggested_severity=Severity(data["suggested_severity"]), rationale=str(data["rationale"]),
            missing_facts=[str(s) for s in data["missing_facts"]], confidence=float(data["confidence"]),
            briefing={str(k): str(v) for k, v in briefing.items()},
            provenance=Provenance(model=self.model, prompt_sha256=self.prompt_sha256,
                                  catalogue_version=packet.catalogue_version, created_at=now_utc()),
        )


def make_proposer(cfg: RuleConfig, model: str | None = None) -> Proposer:
    if cfg.adjudication.provider == "claude":
        return ClaudeProposer(model=model or DEFAULT_MODEL)
    return StubProposer()


__all__ = ["ClaudeProposer", "ContextPacket", "Proposer", "StubProposer", "build_packet", "make_proposer",
           "validation_scope", "CONSTRAINTS", "DEFAULT_MODEL"]
