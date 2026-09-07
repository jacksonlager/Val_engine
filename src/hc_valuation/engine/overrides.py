"""E-01 — committee override ledger.

`booked_mark = override.booked ?? proposed_mark`. Overrides never touch the proposal;
both figures survive into the report so a booked number always carries the proposal it
departed from and the person who departed from it.
"""
from __future__ import annotations

from .models import OverrideLedger, OverrideRecord, Severity
from .state import Suggest, Working


def apply_override(w: Working, ledger: OverrideLedger, quarter: str, tolerance: float) -> tuple[float, OverrideRecord | None]:
    rec = ledger.for_quarter(quarter).get(w.pos.company)
    proposed = w.proposed_mark
    if rec is None:
        return proposed, None
    if abs(rec.proposed - proposed) > tolerance:
        # The engine's proposal moved since the override was recorded (inputs or policy changed).
        # Keep the booked figure — a human decision stands — but make the drift visible.
        w.flag("E-01", "treatment", Severity.REVIEW,
               f"{rec.approver} booked ${rec.booked:.2f}M against a proposal of ${rec.proposed:.2f}M, but the engine now proposes "
               f"${proposed:.2f}M — the inputs or the policy have moved since. The booked figure stands, because a human decision "
               "is not overwritten by a re-run.",
               points=(f"{rec.approver} booked **${rec.booked:.2f}M** against a proposal of ${rec.proposed:.2f}M.",
                       f"The engine **now proposes ${proposed:.2f}M** — inputs or policy have moved since.",
                       "The **booked figure stands**: a human decision is not overwritten by a re-run."),
               suggestions=(
                   Suggest("reconfirm", f"Re-confirm the booked ${rec.booked:.2f}M.", ("The committee decision stands; only the proposal it was measured against moved.", "Re-confirming refreshes the record against the current proposal."), "value", value=rec.booked),
                   Suggest("adopt_proposed", f"Adopt the revised proposal of ${proposed:.2f}M.", ("Inputs or policy moved; the new proposal reflects them.", "Removes the drift and the override in one step."), "proposed"),
               ),
               action=f"Ask {rec.approver} to re-confirm ${rec.booked:.2f}M against the revised proposal.",
               override_proposed=rec.proposed, current_proposed=proposed, booked=rec.booked)
    route = decision_route(rec.source_suggestion)
    w.step("E-01", "1", {"proposed": proposed, "booked": rec.booked, "approver": rec.approver,
                         "reason": rec.reason, "created_at": rec.created_at.isoformat(),
                         "rule_ids_addressed": list(rec.rule_ids_addressed),
                         "chosen_by": route,
                         "source_suggestion": rec.source_suggestion,
                         "evidence": dict(rec.evidence) if rec.evidence else None},
           proposed, proposed,   # the chain records the decision; proposed_mark itself is not altered
           f"Committee override by {rec.approver} ({rec.created_at.isoformat()}): booked ${rec.booked:.2f}M against proposed "
           f"${proposed:.2f}M ({route}{evidence_clause(rec.evidence)}). Reason: {rec.reason}")
    return rec.booked, rec


def evidence_clause(evidence: dict | None) -> str:
    """The words for the input behind the booked figure, appended to the route in the E-01
    rationale. Only a closing price has a shape the chain can spell out; any other kind is
    named and left to the `evidence` input on the step."""
    if not evidence:
        return ""
    kind = evidence.get("kind")
    if kind != "closing_price":
        return f"; evidence of kind {kind!r} attached" if kind else ""
    cap = evidence.get("market_cap_musd")
    parts = [f"market cap ${float(cap):,.0f}M" if isinstance(cap, (int, float)) else "market cap not stated"]
    if evidence.get("as_of"):
        parts.append(f"at {evidence['as_of']}")
    if evidence.get("source"):
        parts.append(f"from {evidence['source']}")
    own = evidence.get("ownership")
    if isinstance(own, (int, float)):
        parts.append(f"× {float(own):.1%} held")
    return f": {' '.join(parts)}"


def decision_route(source_suggestion: str | None) -> str:
    """How the booked number was arrived at, for the audit chain. The review tool writes
    `<rule>/<key>` for an engine-priced option, `<rule>/proposed` when the approver took the
    proposal as it stood, `<rule>/manual` for a number they typed, `<rule>/price` when they
    supplied the quarter-end price the engine had no quote for (the evidence travels on the
    record); a record written by hand or by an older tool carries nothing and is read as a
    custom override."""
    if not source_suggestion:
        return "custom override"
    key = source_suggestion.rsplit("/", 1)[-1]
    if key == "manual":
        return "mark entered by the approver"
    if key == "proposed":
        return "proposed mark accepted"
    if key == "price":
        return "closing price supplied"
    return f"engine option {source_suggestion}"
