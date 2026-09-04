"""Mutable per-company working state while rolling the quarter forward.

This is the only mutable object in the engine. It exists so marking rules can be written
as small, readable functions; it is frozen into a `CompanyResult` at the end of the roll.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .inputs import Event, Position, Status
from .models import EventRef, Flag, MarkStep, OpenItem, Severity


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
    status: Status = Status.ACTIVE
    listed: bool = False
    fv_level: int | None = 3
    stage: str = ""
    terminal: bool = False
    market_note: str = ""

    steps: list[MarkStep] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
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

    def flag(self, rule_id: str, family: str, severity: Severity, message: str, action: str = "", **evidence: Any) -> None:
        if severity is Severity.MONITOR and action:
            raise ValueError(f"{rule_id}: a MONITOR flag must not carry an action — if a reviewer can act on it, "
                             "it is not MONITOR")
        if severity is not Severity.MONITOR and not action:
            raise ValueError(f"{rule_id}: a {severity.value} flag must say what the reviewer has to do")
        self.flags.append(Flag(rule_id=rule_id, family=family, severity=severity, message=message, action=action,
                               evidence={k: (v if not isinstance(v, date) else v.isoformat()) for k, v in evidence.items()}))
