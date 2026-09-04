"""Event precedence for companies with more than one event in a quarter.

Events are applied **chronologically**, so the audit chain reads as the quarter actually
happened (a July round's cash is counted before a September exit returns it). Three rules
sit on top of chronology:

* once a terminal event (shutdown, closed exit) has applied, anything later is recorded
  as suppressed rather than applied — except cash that arrives *after* the position is
  closed (a distribution such as an escrow release, or a note repaid), which is applied
  because it changes realized proceeds and nothing else;
* an announced acquisition is superseded by a closed one in the same quarter;
* an announced acquisition is superseded by a termination dated on or after it in the
  same quarter (the deal was announced and fell through inside one period).

Same-date ties apply the non-terminal event first so money flows are captured before
the position is closed. Unrecognised events are never reordered away from their date —
M-999 blocks wherever they fall.

`superseded` is given only the rows the orchestrator will actually dispatch: a row the
ingest layer refused (see `run.py`) is not evidence of anything and never supersedes an
announcement — an announced deal whose closing row was refused stays announced.

No company has two events in the Q3 2026 feed, but the engine must be deterministic
when one does.
"""
from __future__ import annotations

from .inputs import Event, EventType

TIER: dict[str, int] = {
    EventType.SHUTDOWN.value: 1,
    EventType.ACQ_CLOSED.value: 1,
    EventType.IPO.value: 2,
    EventType.DIRECT_LISTING.value: 2,
    EventType.BANKRUPTCY_CH11.value: 2,        # not terminal: a reorganisation, not a liquidation
    EventType.PRICED_ROUND.value: 3,
    EventType.NEW_INVESTMENT.value: 3,
    EventType.SECONDARY.value: 4,
    EventType.SECONDARY_PURCHASE.value: 4,
    EventType.DISTRIBUTION.value: 4,
    EventType.OWNERSHIP_ADJUSTMENT.value: 4,
    EventType.NOTE_REPAID.value: 4,
    EventType.ACQ_TERMINATED.value: 5,         # listed before Announced: a termination wins over an announcement
    EventType.ACQ_ANNOUNCED.value: 5,
    EventType.CONVERTIBLE_NOTE.value: 6,
    EventType.TERM_SHEET.value: 7,
}
TERMINAL: frozenset[str] = frozenset({EventType.SHUTDOWN.value, EventType.ACQ_CLOSED.value})

# Events that may still be applied to a position that is already Acquired / Shut Down — at
# the prior close or earlier in the quarter. They move cash, never the mark.
ALLOWED_AFTER_TERMINAL: frozenset[str] = frozenset({EventType.DISTRIBUTION.value, EventType.NOTE_REPAID.value})


def ordered(events: list[Event]) -> list[Event]:
    return sorted(events, key=lambda e: (e.date, -TIER.get(e.event_type, 8), e.row_index))


def superseded(e: Event, all_events: list[Event]) -> str | None:
    """Reason this event should be skipped in favour of another in the same quarter, or None."""
    if e.event_type == EventType.ACQ_ANNOUNCED.value:
        if any(x.event_type == EventType.ACQ_CLOSED.value for x in all_events if x is not e):
            return "announced acquisition superseded by a closed acquisition in the same quarter"
        if any(x.event_type == EventType.ACQ_TERMINATED.value and x.date >= e.date for x in all_events if x is not e):
            return "announced acquisition superseded by its termination in the same quarter"
    return None
