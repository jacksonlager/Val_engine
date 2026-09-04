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
    w.step("E-01", "1", {"proposed": proposed, "booked": rec.booked, "approver": rec.approver,
                         "reason": rec.reason, "created_at": rec.created_at.isoformat(),
                         "rule_ids_addressed": list(rec.rule_ids_addressed)},
           proposed, proposed,   # the chain records the decision; proposed_mark itself is not altered
           f"Committee override by {rec.approver} ({rec.created_at.isoformat()}): booked ${rec.booked:.2f}M against proposed "
           f"${proposed:.2f}M. Reason: {rec.reason}")
    return rec.booked, rec
