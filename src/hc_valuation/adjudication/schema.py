"""E-09 — the adjudicator's only output shape. Note what is absent: a mark.

A `TreatmentProposal` proposes a *rule* (a restricted-DSL formula plus an analogue it
reasons from). The deterministic engine computes the number, and only after a named
person accepts or promotes it. Validation is deliberately hostile to the model:

* the formula must parse with `engine.dsl.parse` against the policy's whitelist —
  a field outside it is rejected by the parser, not by the model's judgment;
* the analogue must be a rule that exists in the registry, so a weak analogy is visible;
* the suggested severity can never be below REVIEW — nothing a model drafts is CLEAR;
* `missing_facts` must be non-empty or say `["none"]` explicitly;
* `confidence` is displayed and gates nothing (`auto_accept: never` has no value).

Validation context (whitelist + registry) is supplied through `validation_scope(cfg,
registry)`; outside a scope the maximal whitelist — the fields `engine.declarative`
can actually supply — and the builtin registry apply, so a proposal can never validate
against *more* than the engine can evaluate.
"""
from __future__ import annotations

import contextvars
import hashlib
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import CustomRuleSpec, RuleConfig
from ..engine import dsl
from ..engine.dsl import DSLError
from ..engine.models import Severity
from ..engine.registry import BUILTIN, Registry

# The complete vocabulary `engine.declarative._values` provides. A policy whitelist may be
# narrower, never wider — anything else could parse and then fail at evaluation time.
ENGINE_FIELDS: tuple[str, ...] = (
    "ownership_before", "ownership_after", "post_money", "deal_value", "proceeds",
    "prior_mark", "hc_investment", "close_probability", "note_at_cost",
)
ENGINE_OPERATORS: tuple[str, ...] = ("*", "/", "+", "-", "min", "max")

ProposedKind = Literal["reuse", "new_rule"]
BRIEFING_KEYS: tuple[str, ...] = ("what_happened", "why_no_rule", "what_it_means", "suggested_course", "what_to_check")
ProposalStatus = Literal["pending", "accepted_once", "promoted", "rejected"]
Decision = Literal["accept_once", "promote", "reject"]

_scope: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("adjudication_validation_scope", default=None)


@contextmanager
def validation_scope(cfg: RuleConfig | None = None, registry: Registry | None = None) -> Iterator[None]:
    """Make the policy whitelist and the run's registry the validation authority."""
    ctx = {
        "allowed_fields": tuple(cfg.adjudication.allowed_fields) if cfg and cfg.adjudication.allowed_fields else ENGINE_FIELDS,
        "allowed_operators": tuple(cfg.adjudication.allowed_operators) if cfg and cfg.adjudication.allowed_operators else ENGINE_OPERATORS,
        "registry": registry or BUILTIN,
    }
    token = _scope.set(ctx)
    try:
        yield
    finally:
        _scope.reset(token)


def _ctx() -> dict[str, Any]:
    return _scope.get() or {"allowed_fields": ENGINE_FIELDS, "allowed_operators": ENGINE_OPERATORS, "registry": BUILTIN}


def check_formula(formula: str) -> str:
    """Parse against the active whitelist; raises `DSLError` before pydantic ever sees the value."""
    c = _ctx()
    allowed = tuple(f for f in c["allowed_fields"] if f in ENGINE_FIELDS)   # never wider than the engine
    dsl.parse(formula, allowed, c["allowed_operators"])
    return formula.strip()


def check_analogue(rule_id: str) -> str:
    known = {m.rule_id for m in _ctx()["registry"].all()}
    if rule_id not in known:
        raise ValueError(f"analogue_rule_id {rule_id!r} is not a registered rule; known: {sorted(known)}")
    return rule_id


def make_proposal_id(event_signature: str, catalogue_version: str) -> str:
    return hashlib.sha256(f"{event_signature}|{catalogue_version}".encode()).hexdigest()[:16]


def catalogue_version_for(policy_version: str, registry: Registry) -> str:
    """Policy version plus a digest of the rule catalogue: a proposal is only reusable while
    the rules it reasoned from are the rules in force."""
    digest = hashlib.sha256("|".join(f"{m.rule_id}@{m.version}" for m in registry.all()).encode()).hexdigest()[:8]
    return f"{policy_version}+{digest}"


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    model: str
    prompt_sha256: str
    catalogue_version: str
    created_at: datetime


class TreatmentProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: str
    event_signature: str
    event_type: str                       # raw type string; the promoted rule dispatches on it
    company: str
    event_row_index: int
    quarter_label: str                    # the quarter the event was adjudicated in
    proposed_mark_at_proposal: float      # the engine's (blocked, unchanged) proposal — an override needs it
    analogue_rule_id: str
    proposed_kind: ProposedKind
    formula: str
    parameter_map: dict[str, str] = Field(default_factory=dict)
    suggested_severity: Severity
    rationale: str
    missing_facts: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance
    # The draft in a reviewer's words: what happened, why no rule covers it, what it means for the
    # mark, the suggested course, what to check. Prose only — the formula above is the treatment.
    briefing: dict[str, str] = Field(default_factory=dict)
    status: ProposalStatus = "pending"
    decision: dict[str, Any] | None = None

    def __init__(self, /, **data: Any) -> None:
        # Pre-checks run *before* pydantic so the DSL parser's own error type surfaces to the
        # caller (a whitelist violation is a DSLError, not a ValidationError wrapping one).
        if "formula" in data:
            check_formula(str(data["formula"]))
        if "analogue_rule_id" in data:
            check_analogue(str(data["analogue_rule_id"]))
        prov = data.get("provenance")
        cat = prov.get("catalogue_version", "") if isinstance(prov, dict) else getattr(prov, "catalogue_version", "")
        expected = make_proposal_id(str(data.get("event_signature", "")), str(cat))
        if data.get("proposal_id") and data["proposal_id"] != expected:
            raise ValueError(f"proposal_id {data['proposal_id']} does not match sha(signature|catalogue_version) {expected}")
        data.setdefault("proposal_id", expected)
        super().__init__(**data)

    # Second line of defence for the `model_validate` path (cache files, API bodies).
    @field_validator("formula")
    @classmethod
    def _formula_parses(cls, v: str) -> str:
        return check_formula(v)

    @field_validator("analogue_rule_id")
    @classmethod
    def _analogue_exists(cls, v: str) -> str:
        return check_analogue(v)

    @field_validator("suggested_severity")
    @classmethod
    def _never_below_review(cls, v: Severity) -> Severity:
        if v not in (Severity.REVIEW, Severity.BLOCK):
            raise ValueError("suggested_severity can never be below REVIEW: a model-drafted treatment is never CLEAR or MONITOR")
        return v

    @field_validator("missing_facts")
    @classmethod
    def _facts_explicit(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("missing_facts must be non-empty, or exactly ['none']")
        if any(s.lower() == "none" for s in cleaned) and len(cleaned) != 1:
            raise ValueError("missing_facts may say 'none' only on its own")
        return cleaned

    @field_validator("briefing")
    @classmethod
    def _briefing_keys(cls, v: dict[str, str]) -> dict[str, str]:
        out = {}
        for k, text in (v or {}).items():
            if k not in BRIEFING_KEYS:
                continue                                    # a key the card does not show is dropped, not fatal
            text = " ".join(str(text or "").split())
            if text:
                out[k] = text[:600]
        return out

    @field_validator("rationale")
    @classmethod
    def _rationale_present(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale must not be empty")
        return v.strip()

    # ------------------------------------------------------------ helpers
    def with_decision(self, status: ProposalStatus, decision: dict[str, Any]) -> "TreatmentProposal":
        return self.model_copy(update={"status": status, "decision": decision})

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, text: str) -> "TreatmentProposal":
        return cls.model_validate_json(text)


def to_custom_rule_spec(proposal: TreatmentProposal, approver: str, effective_from: date, rule_id: str) -> CustomRuleSpec:
    """Promotion: proposal -> declarative rule. The formula is carried verbatim (it re-parses
    when the policy loads); analogue semantics decide `terminal` and `fv_level`."""
    terminal = proposal.analogue_rule_id in ("M-020", "M-021")
    fv_level = 1 if proposal.analogue_rule_id == "M-040" else 3
    return CustomRuleSpec(
        rule_id=rule_id, version="1", event_type=proposal.event_type, formula=proposal.formula,
        severity=proposal.suggested_severity.value,
        rationale=f"{proposal.rationale} (by analogy with {proposal.analogue_rule_id})",
        approver=approver, effective_from=effective_from, source_proposal=proposal.proposal_id,
        fv_level=fv_level, terminal=terminal,
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


__all__ = [
    "DSLError", "ENGINE_FIELDS", "ENGINE_OPERATORS", "Provenance", "TreatmentProposal", "catalogue_version_for",
    "check_formula", "make_proposal_id", "now_utc", "to_custom_rule_spec", "validation_scope",
]
