"""E-08: rule registry with effective dating.

Marking rules register themselves with metadata rather than being wired into a dispatch
block. Adding a rule next quarter is adding a function (or a declarative spec in the
policy file) — the orchestrator is never edited. `effective_from` guarantees that a rule
written for Q4 does not rewrite Q3 when Q3 is re-run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Protocol, TYPE_CHECKING

from .models import Severity

if TYPE_CHECKING:  # pragma: no cover
    from .inputs import Event
    from .state import Working
    from ..config import RuleConfig
    from .models import MarketData


class MarkingFn(Protocol):
    def __call__(self, w: "Working", e: "Event", cfg: "RuleConfig", market: "MarketData") -> None: ...


@dataclass(frozen=True)
class RuleMeta:
    rule_id: str
    version: str
    applies_to: tuple[str, ...]          # event type strings; ("*",) for the fallback
    severity: Severity | None            # severity of the treatment flag this rule raises, if any
    effective_from: date
    description: str
    terminal: bool = False               # suppresses everything else for the company
    tier: int = 99                       # precedence: lower applies first
    source: str = "builtin"              # builtin | declarative


@dataclass
class Registry:
    _rules: dict[str, tuple[RuleMeta, MarkingFn]] = field(default_factory=dict)

    def register(self, meta: RuleMeta, fn: MarkingFn) -> None:
        if meta.rule_id in self._rules and self._rules[meta.rule_id][0].source == "builtin" and meta.source == "builtin":
            raise ValueError(f"duplicate rule id {meta.rule_id}")
        self._rules[meta.rule_id] = (meta, fn)

    def all(self) -> list[RuleMeta]:
        return sorted((m for m, _ in self._rules.values()), key=lambda m: m.rule_id)

    def get(self, rule_id: str) -> tuple[RuleMeta, MarkingFn]:
        return self._rules[rule_id]

    def handler_for(self, event_type: str, as_of: date) -> tuple[RuleMeta, MarkingFn] | None:
        """Most specific, in-force rule for an event type. Declarative rules win over builtins
        for the same event type (they are the newer precedent); '*' is the fallback."""
        candidates = [
            (m, f) for m, f in self._rules.values()
            if event_type in m.applies_to and m.effective_from <= as_of
        ]
        if candidates:
            # Declarative precedent over builtin; then the *newest* in-force rule — a correction
            # promoted in Q4 must outrank the Q3 draft it supersedes, which an id sort (M-100 before
            # M-101) got exactly backwards; the id only breaks a genuine tie, for determinism.
            candidates.sort(key=lambda mf: (0 if mf[0].source == "declarative" else 1,
                                            -mf[0].effective_from.toordinal(), mf[0].rule_id))
            return candidates[0]
        fallback = [(m, f) for m, f in self._rules.values() if "*" in m.applies_to and m.effective_from <= as_of]
        return fallback[0] if fallback else None

    def covered_event_types(self, as_of: date) -> set[str]:
        out: set[str] = set()
        for m, _ in self._rules.values():
            if m.effective_from <= as_of:
                out.update(t for t in m.applies_to if t != "*")
        return out

    def copy(self) -> "Registry":
        r = Registry()
        r._rules = dict(self._rules)
        return r


BUILTIN = Registry()


def rule(*, rule_id: str, version: str, applies_to: tuple[str, ...], severity: Severity | None,
         effective_from: date, description: str, terminal: bool = False, tier: int = 99) -> Callable[[MarkingFn], MarkingFn]:
    def deco(fn: MarkingFn) -> MarkingFn:
        BUILTIN.register(RuleMeta(rule_id=rule_id, version=version, applies_to=applies_to, severity=severity,
                                  effective_from=effective_from, description=description,
                                  terminal=terminal, tier=tier), fn)
        return fn
    return deco
