"""What the engine does with a note reading: add review findings, and nothing else.

`apply_readings` runs after the marking rules and the keyword screen (X-105) on the rows that
were applied. For each row the reader read it raises

* X-130 — the text describes something (a catalogue kind) that no rule took account of on this
  row: not the row's own nature (a bridge on a Convertible Note row), not a term a rule marked
  as handled (`Working.handled`), not a term X-105 already raised. One finding per row, with
  the quotes.
* X-131 — the text states a different value or fact for one of the row's columns. The engine
  used the column; a person confirms which is right.
* X-126 — the text supersedes figures on the Portfolio tab (raised here only if the row's rule
  did not already raise it).
* X-132 — the reader was on but could not read a row that carries text.

Never a number, never a mark, never a lower severity, never a removed finding. A reading with
nothing in it changes nothing. Pure: readings are inputs, like market data.
"""
from __future__ import annotations

from collections.abc import Mapping

from ..config import RuleConfig
from ..notes.catalogue import BY_KIND, COLUMNS, AspectKind, kinds_for_terms
from ..notes.schema import Aspect, RowReading
from .inputs import Event
from .models import Severity
from .state import Suggest, Working


def _clip(text: str, limit: int = 140) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " …"


def _covered_kinds(w: Working, e: Event, cfg: RuleConfig) -> set[AspectKind]:
    """Kinds a rule already took account of on this row, or X-105 already raised."""
    terms = set(w.handled_terms.get(e.row_index, set()))
    exempt_map = cfg.note_screen.exempt or {}
    terms |= {t.lower() for t in exempt_map.get(e.event_type, ())}
    for f in w.flags:
        if f.rule_id == "X-105" and f.evidence.get("row_index") == e.row_index:
            terms |= {str(t).lower() for t in f.evidence.get("terms", ())}
    covered = kinds_for_terms(terms) if terms else set()
    covered |= {spec.kind for spec in BY_KIND.values() if e.event_type in spec.events}
    return covered


def _fmt(v: object) -> str:
    if v is None or v == "":
        return "blank"
    if isinstance(v, float):
        return f"{v:.1%}" if 0 < v < 1 else f"{v:,.2f}"
    return str(v)


def apply_readings(w: Working, events: list[Event], readings: Mapping[int, RowReading], cfg: RuleConfig) -> None:
    for e in events:
        r = readings.get(e.row_index)
        if r is None:
            continue
        src = r.source or "reader"
        if r.failed:
            w.flag("X-132", "notes", Severity.REVIEW,
                   f"The note reader could not read row {e.row_index} ({r.failed}). Only the keyword screen ran on its text, so "
                   "anything the note says beyond the columns has to be read by a person.",
                   points=(f"**Row {e.row_index}'s note was not read** by the reader ({_clip(r.failed, 80)}).",
                           "Only the **keyword screen** ran on it.",
                           "Read the note; anything beyond the columns is unaccounted for."),
                   suggestions=(Suggest("as_proposed", "Book as proposed once the note has been read by hand.", ("The columns were applied; the note may add nothing.", "Rerun with the reader available to have it read."), "proposed"),),
                   action=f"Read the note on row {e.row_index} by hand (the reader failed) and decide whether it changes anything.",
                   row_index=e.row_index, reason=r.failed)
            continue
        covered = _covered_kinds(w, e, cfg)
        open_aspects = [a for a in r.aspects if a.kind not in covered]
        if r.novel:
            open_aspects.append(Aspect(kind=AspectKind.OTHER, quote="", note=r.novel, verified=True))
        if open_aspects:
            labels = list(dict.fromkeys(BY_KIND[a.kind].label for a in open_aspects))
            quotes = [a.quote for a in open_aspects if a.quote and a.verified][:2]
            unverified = [a for a in open_aspects if a.quote and not a.verified]
            notes = [a.note for a in open_aspects if a.note][:3]
            if quotes:
                second = f"The note says: “{_clip(quotes[0])}”" + (f" … “{_clip(quotes[1], 80)}”" if len(quotes) > 1 else "")
            elif notes:
                second = "The reader's reading: " + "; ".join(_clip(n, 100) for n in notes[:2])
            else:
                second = "See the row's note."
            if unverified:
                second += " (a quoted passage could not be matched to the row text — read the note itself)"
            third = ("The note also instructs: " + "; ".join(_clip(i, 80) for i in r.instructions[:2]) + "."
                     if r.instructions else "**No rule took account of this**; the mark ignores it until a person decides.")
            w.flag("X-130", "notes", Severity.REVIEW,
                   f"The text on row {e.row_index} ({e.event_type}) describes {', '.join(labels).lower()} — which no rule took account "
                   f"of on this row. The engine applied the columns and ignored the rest. "
                   + " ".join(f"{BY_KIND[a.kind].label}: “{_clip(a.quote, 200)}”" + (f" — {a.note}" if a.note else "") for a in open_aspects if a.quote)
                   + (" " + " ".join(f"{BY_KIND[a.kind].label}: {a.note}" for a in open_aspects if not a.quote and a.note) if any(not a.quote for a in open_aspects) else "")
                   + (" Instructions in the note: " + " | ".join(r.instructions) if r.instructions else ""),
                   points=(f"The note describes **{', '.join(labels).lower()}** that **no rule applied** on row {e.row_index}.", second, third),
                   suggestions=(
                       Suggest("as_proposed", "Book as proposed; reflect the note's terms by override once read.", ("The engine applied every term the columns can hold.", "Unrepresented terms need a human number, not a guess."), "proposed"),
                   ),
                   action=f"Read the note on row {e.row_index}: {', '.join(labels).lower()}. Decide whether the mark should reflect it (override) or the row needs correcting.",
                   row_index=e.row_index, kinds=[a.kind.value for a in open_aspects], quotes=[a.quote for a in open_aspects],
                   notes=[a.note for a in open_aspects], instructions=list(r.instructions), confidence=r.confidence, source=src,
                   unverified_quotes=len(unverified))
        for c in r.conflicts:
            col = COLUMNS.get(c.column, c.column)
            w.flag("X-131", "data", Severity.REVIEW,
                   f"On row {e.row_index} the note says “{_clip(c.note_says, 200)}” but the column {col} carries {_fmt(c.column_value)}"
                   + (f" ({c.why})" if c.why else "") + ". The engine used the column. One of them is wrong, and the mark depends on which."
                   + ("" if c.verified else " (The quoted passage could not be matched to the row text; read the note itself.)"),
                   points=(f"The note says **“{_clip(c.note_says, 90)}”**; the column **{col}** carries **{_fmt(c.column_value)}**.",
                           "The engine **used the column**.",
                           "Confirm which is right: correct the row and rerun, or decide by override."),
                   suggestions=(
                       Suggest("as_proposed", "Keep the mark computed from the column; the note is context.", ("The column is the input the engine can audit.", "Right when the note is stale or imprecise."), "proposed"),
                       Suggest("hold_prior", "Hold the prior mark until the row is corrected and rerun.", ("Nothing is booked from a row whose figure is in doubt.", "Rerunning after the fix clears this without an override."), "prior"),
                   ),
                   action=f"Confirm {col} on row {e.row_index} against the note ({_clip(c.note_says, 60)}); correct the row and rerun, or decide by override.",
                   row_index=e.row_index, column=c.column, column_value=c.column_value, note_says=c.note_says, why=c.why,
                   verified=c.verified, source=src, confidence=r.confidence)
        if r.supersedes and not any(f.rule_id == "X-126" and f.evidence.get("row_index") == e.row_index for f in w.flags):
            fields = list(dict.fromkeys(s.field for s in r.supersedes))
            quote = next((s.quote for s in r.supersedes if s.quote), "")
            w.flag("X-126", "liquidity", Severity.REVIEW,
                   f"The note on row {e.row_index} supersedes figures the Portfolio tab carries ({', '.join(fields)}): “{_clip(quote, 200)}”. "
                   "The engine does not read numbers out of a sentence, so the screens ran on the tab's columns.",
                   points=(f"The note **supersedes the Portfolio tab** ({', '.join(fields)}); the screens read the **tab**, not the note.",
                           f"The note says: “{_clip(quote, 110)}”" if quote else "See the row's note.",
                           "Update the Portfolio tab from the note and rerun, or confirm the tab is current."),
                   suggestions=(
                       Suggest("as_proposed", "Keep the mark as proposed; update the Portfolio tab from the note and rerun.", ("A figure in prose is not an input until it is in the tab.", "Rerunning on the corrected tab re-screens runway and growth."), "proposed"),
                   ),
                   action="Update the Portfolio tab from the note (or confirm the tab is current), then rerun.",
                   row_index=e.row_index, fields=fields, quote=quote, source=src, confidence=r.confidence)

