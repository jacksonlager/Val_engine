"""Mutable per-company working state while rolling the quarter forward.

This is the only mutable object in the engine. It exists so marking rules can be written
as small, readable functions; it is frozen into a `CompanyResult` at the end of the roll.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .inputs import Event, Position, Status
from .models import EventRef, Flag, MarkStep, OpenItem, Severity, Suggestion


_SENTENCE = re.compile(r"(?<=[.?!])\s+(?=[A-Z\u201c\"$(])")


def summarise(message: str, limit: int = 3) -> tuple[str, ...]:
    """The first sentences of `message`, for a flag whose rule did not write its own points.

    Deliberately dumb: it splits, it never rewrites, so a derived point says exactly what the
    rule said. Authored points (see `Flag.points`) are better and every built-in rule has them."""
    parts = [s.strip() for s in _SENTENCE.split(message.strip()) if s.strip()]
    return tuple(parts[:limit]) if parts else (message.strip(),)


@dataclass(frozen=True)
class Suggest:
    """A suggestion as a rule writes it, before the final proposal is known.

    `basis` says where the booked number comes from once the roll is finished:
      proposed     — the engine's final proposed mark (ratify as proposed)
      prior        — the prior mark the position came in with (hold)
      value        — an explicit $M figure the rule computed (`value`)
      alternative  — `w.alternative_marks[value]`, dropped if that mark never materialises
      cost         — the lower of invested cost and the proposal (a floor, never a lift)
    Resolved by `Working.resolved_flags` into `Suggestion`s with a real `booked`."""
    key: str
    label: str
    reasons: tuple[str, str]
    basis: str
    value: float | str | None = None


_BASES = {"proposed", "prior", "value", "alternative", "cost"}


@dataclass
class Working:
    pos: Position
    quarter_label: str
    sheet_name: str

    equity_mark: float = 0.0
    note_at_cost: float = 0.0
    ownership: float = 0.0
    invested: float = 0.0
    realized_quarter: float = 0.0
    latest_post: float = 0.0
    latest_round: date = date.min
    staleness_anchor: date = date.min
    carried_anchor: date | None = None   # a staleness anchor restored from the prior quarter's sidecar
    status: Status = Status.ACTIVE
    listed: bool = False
    fv_level: int | None = 3
    stage: str = ""
    terminal: bool = False
    market_note: str = ""

    steps: list[MarkStep] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    _suggestions: dict[int, tuple[Suggest, ...]] = field(default_factory=dict)
    open_items: list[OpenItem] = field(default_factory=list)
    alternative_marks: dict[str, float] = field(default_factory=dict)
    applied_rules: list[str] = field(default_factory=list)

    @classmethod
    def from_position(cls, p: Position, quarter_label: str, sheet_name: str) -> "Working":
        return cls(
            pos=p, quarter_label=quarter_label, sheet_name=sheet_name,
            equity_mark=p.prior_mark, ownership=p.ownership, invested=p.invested,
            latest_post=p.latest_post_money, latest_round=p.latest_round,
            staleness_anchor=p.latest_round, status=p.status, stage=p.stage,
            fv_level=(3 if p.status == Status.ACTIVE else None),
            terminal=(p.status != Status.ACTIVE),
        )

    # ------------------------------------------------------------------ helpers
    @property
    def proposed_mark(self) -> float:
        return self.equity_mark + self.note_at_cost

    def ref(self, e: Event | None) -> EventRef | None:
        if e is None:
            return None
        return EventRef(sheet=self.sheet_name, row_index=e.row_index, event_type=e.event_type, date=e.date)

    def step(self, rule_id: str, version: str, inputs: dict[str, Any], prior: float, new: float,
             rationale: str, e: Event | None = None) -> None:
        self.steps.append(MarkStep(
            rule_id=rule_id, rule_version=version, sequence=len(self.steps) + 1,
            inputs={k: (v if not isinstance(v, date) else v.isoformat()) for k, v in inputs.items()},
            prior_value=round(prior, 6), new_value=round(new, 6), rationale=rationale, evidence=self.ref(e),
        ))
        if rule_id not in self.applied_rules:
            self.applied_rules.append(rule_id)

    def flag(self, rule_id: str, family: str, severity: Severity, message: str, action: str = "",
             points: tuple[str, ...] = (), suggestions: tuple[Suggest, ...] = (), **evidence: Any) -> None:
        if severity is Severity.MONITOR and action:
            raise ValueError(f"{rule_id}: a MONITOR flag must not carry an action — if a reviewer can act on it, "
                             "it is not MONITOR")
        if severity is not Severity.MONITOR and not action:
            raise ValueError(f"{rule_id}: a {severity.value} flag must say what the reviewer has to do")
        # A flag a reviewer must act on has to be readable at a glance: two or three lines, not a
        # paragraph. MONITOR is context and stays prose — it is never the thing being scanned.
        if severity is Severity.MONITOR:
            if points:
                raise ValueError(f"{rule_id}: a MONITOR flag carries no summary points — it is context, not a gate")
            if suggestions:
                raise ValueError(f"{rule_id}: a MONITOR flag has nothing to decide, so nothing to suggest")
        else:
            # A rule that did not author points (a policy rule promoted from YAML, say) still gets
            # scannable lines: its own sentences, unbolded. Never more than three.
            points = tuple(points) or summarise(message)
            if not 1 <= len(points) <= 3:
                raise ValueError(f"{rule_id}: a {severity.value} flag carries at most three summary points "
                                 f"(got {len(points)}); the full reasoning stays in `message`")
        if len(suggestions) > 3:
            raise ValueError(f"{rule_id}: at most three suggestions — a menu, not a list")
        for sg in suggestions:
            if sg.basis not in _BASES:
                raise ValueError(f"{rule_id}: suggestion {sg.key!r} has unknown basis {sg.basis!r}")
            if len(sg.reasons) != 2 or not all(sg.reasons):
                raise ValueError(f"{rule_id}: suggestion {sg.key!r} needs exactly two reasons")
            if sg.basis == "value" and not isinstance(sg.value, (int, float)):
                raise ValueError(f"{rule_id}: suggestion {sg.key!r} with basis 'value' needs a number")
            if sg.basis == "alternative" and not isinstance(sg.value, str):
                raise ValueError(f"{rule_id}: suggestion {sg.key!r} with basis 'alternative' names an alternative mark")
        if len({sg.key for sg in suggestions}) != len(suggestions):
            raise ValueError(f"{rule_id}: suggestion keys must be unique within a flag")
        self.flags.append(Flag(rule_id=rule_id, family=family, severity=severity, message=message, action=action,
                               points=tuple(points),
                               evidence={k: (v if not isinstance(v, date) else v.isoformat()) for k, v in evidence.items()}))
        self._suggestions[len(self.flags) - 1] = tuple(suggestions)

    def resolved_flags(self, proposed: float, prior: float, invested: float, tol: float = 1e-6) -> list[Flag]:
        """The flags with every suggestion's `booked` filled in from the finished roll.

        A suggestion that would book the same number as an earlier one on the same flag is
        dropped (ratifying the proposal and holding the prior are the same decision when the
        mark did not move); one naming an alternative mark that never materialised is dropped."""
        out: list[Flag] = []
        for i, f in enumerate(self.flags):
            resolved: list[Suggestion] = []
            for sg in self._suggestions.get(i, ()):
                if sg.basis == "proposed":
                    booked = proposed
                elif sg.basis == "prior":
                    booked = prior
                elif sg.basis == "cost":
                    booked = min(invested, proposed)
                elif sg.basis == "alternative":
                    if sg.value not in self.alternative_marks:
                        continue
                    # alternatives are equity-basis marks; the position's note leg rides on top, as in the proposal
                    booked = self.alternative_marks[str(sg.value)] + self.note_at_cost
                else:
                    booked = float(sg.value)  # type: ignore[arg-type]
                booked = round(max(0.0, float(booked)), 6)
                if any(abs(r.booked - booked) <= tol for r in resolved):
                    continue
                resolved.append(Suggestion(key=sg.key, label=sg.label, reasons=sg.reasons, booked=booked))
            out.append(f if not resolved else f.model_copy(update={"suggestions": tuple(resolved)}))
        return out
