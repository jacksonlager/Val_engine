"""Declarative rules promoted from adjudication (E-09 → E-08).

A `CustomRuleSpec` in the policy file becomes a registered handler whose formula is
evaluated by the restricted DSL. The model that drafted it never executes; the spec is
data, reviewed in version control, with a named approver and an effective date.
"""
from __future__ import annotations

from ..config import CustomRuleSpec, RuleConfig
from . import dsl
from .inputs import Event
from .models import MarketData, Severity
from .registry import Registry, RuleMeta
from .state import Working


def _values(w: Working, e: Event, cfg: RuleConfig) -> dict[str, float | None]:
    return {
        "ownership_before": w.ownership,
        "ownership_after": e.ownership_after if e.ownership_after is not None else w.ownership,
        "post_money": e.value,
        "deal_value": e.value,
        "proceeds": e.proceeds or 0.0,
        "prior_mark": w.equity_mark,
        "hc_investment": e.hc_investment or 0.0,
        "close_probability": cfg.marking.announced.close_probability,
        "note_at_cost": w.note_at_cost,
    }


def register_custom_rules(registry: Registry, cfg: RuleConfig) -> None:
    adj = cfg.adjudication
    for spec in cfg.custom_rules:
        tree = dsl.parse(spec.formula, adj.allowed_fields, adj.allowed_operators)  # raises before anything runs

        def handler(w: Working, e: Event, cfg_: RuleConfig, market: MarketData, _spec: CustomRuleSpec = spec, _tree=tree) -> None:
            vals = _values(w, e, cfg_)
            try:
                new_equity = dsl.evaluate(_tree, vals)
            except dsl.DSLError as ex:
                # The formula cannot be evaluated for this row (a field the validator could not see is
                # missing, or a division by zero). Nothing is booked; the position blocks on the rule.
                w.step(_spec.rule_id, _spec.version,
                       {"formula": _spec.formula, **{k: vals[k] for k in dsl.fields_used(_tree)}, "error": str(ex)},
                       w.proposed_mark, w.proposed_mark,
                       f"Declarative rule {_spec.rule_id} could not be evaluated for this row ({ex}); mark unchanged and the "
                       "position blocked — a formula that cannot produce a number must not look like a quiet quarter.", e)
                w.flag(_spec.rule_id, "treatment", Severity.BLOCK,
                       f"Rule {_spec.rule_id} ({_spec.formula}) could not be evaluated on row {e.row_index}: {ex}. The mark is "
                       "unchanged; nothing from this row — proceeds, ownership, cost — has been booked.",
                       action=f"Correct row {e.row_index} so that {_spec.rule_id}'s formula has every input it needs, and rerun.",
                       formula=_spec.formula, error=str(ex), row_index=e.row_index)
                return
            w.step(_spec.rule_id, _spec.version,
                   {"formula": _spec.formula, **{k: vals[k] for k in dsl.fields_used(_tree)}, "approver": _spec.approver,
                    "effective_from": _spec.effective_from.isoformat(), "source_proposal": _spec.source_proposal},
                   w.equity_mark, new_equity,
                   f"Declarative rule {_spec.rule_id} (promoted precedent, approved by {_spec.approver}): {_spec.rationale}", e)
            sev = Severity(_spec.severity)
            w.flag(_spec.rule_id, "treatment", sev,
                   f"Marked by {_spec.rule_id}, a rule promoted from an earlier adjudication and approved by {_spec.approver} "
                   f"with effect from {_spec.effective_from.isoformat()}: {_spec.rationale}",
                   action=("" if sev is Severity.MONITOR else
                           f"Confirm {_spec.rule_id} is still the right treatment for a {_spec.event_type}."),
                   formula=_spec.formula, approver=_spec.approver)
            w.equity_mark = new_equity
            if e.ownership_after is not None:
                w.ownership = e.ownership_after
            if e.hc_investment:
                w.invested += e.hc_investment
            if e.proceeds:
                w.realized_quarter += e.proceeds
            w.fv_level = _spec.fv_level
            if _spec.terminal:
                w.terminal = True
                w.fv_level = None

        registry.register(RuleMeta(rule_id=spec.rule_id, version=spec.version, applies_to=(spec.event_type,),
                                   severity=Severity(spec.severity), effective_from=spec.effective_from,
                                   description=spec.rationale, terminal=spec.terminal, tier=5, source="declarative"),
                          handler)
