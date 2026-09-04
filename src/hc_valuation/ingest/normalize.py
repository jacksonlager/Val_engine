"""Pure normalizers for a dirty workbook (training/SPEC.md §1.1, §1.2, §2).

Every function here answers "what did this cell mean?" and returns `(value, correction)`.
The correction is `None` only when the cell already said exactly what we read; otherwise
it is a `Correction` record the reader locates and `validate.py` turns into an X-91x /
X-920 issue. Nothing is guessed silently: an ambiguous match returns a `kind="ambiguous"`
correction (X-914, blocking) that names the candidates, and a typo match on a short token
is refused for the same reason — a two-letter edit on a five-letter word is a different
word, not a typo.

No threshold lives in this file; every tolerance comes from `config.normalization`.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping, Sequence

from ..config import NormalizationCfg
from ..engine.inputs import Correction, EventType

# ---------------------------------------------------------------- folding

_DASHES = {"–": "-", "—": "-", "‒": "-", "−": "-"}
_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"'}
_EDGE_PUNCT = " \t\r\n.,;:!?'\"`"
_TRAILING_PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")


def unify_typography(text: str) -> str:
    """Curly quotes and typographic dashes become their ASCII forms; whitespace collapses."""
    for k, v in {**_DASHES, **_QUOTES}.items():
        text = text.replace(k, v)
    return " ".join(text.split())


def fold(text: str) -> str:
    """Lowercase, collapse whitespace, unify dashes/quotes, strip edge punctuation, and
    normalise the spacing around parentheses so `Acquisition(Closed)` and
    `Acquisition (Closed)` fold to the same string. Internal punctuation is kept because
    the synonym table distinguishes `m&a closed` and `acquisition - closed`."""
    s = unify_typography(str(text)).lower()
    s = re.sub(r"\s*\(\s*", " (", s)
    s = re.sub(r"\s*\)", ")", s)
    s = " ".join(s.split()).strip(_EDGE_PUNCT)
    return s


def strip_trailing_qualifier(folded: str) -> str:
    """`ipo (nasdaq)` -> `ipo`. The caller decides whether the qualifier mattered by
    trying the full text first."""
    return _TRAILING_PAREN.sub("", folded).strip(_EDGE_PUNCT)


# ---------------------------------------------------------------- distance

def damerau_levenshtein(a: str, b: str) -> int:
    """Optimal-string-alignment distance: insert, delete, substitute, and transpose two
    adjacent characters, each costing 1. Transposition is what makes `Equtiy` one edit
    from `Equity` rather than two."""
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev2: list[int] = []
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[lb]


def _rank(text: str, candidates: Mapping[str, str]) -> list[tuple[int, str, str]]:
    """(distance, candidate, canonical) for every candidate, best first."""
    ranked = [(damerau_levenshtein(text, c), c, canon) for c, canon in candidates.items()]
    ranked.sort(key=lambda t: (t[0], t[1]))
    return ranked


def _fuzzy(text: str, candidates: Mapping[str, str], max_distance: int, min_length: int,
           ) -> tuple[str | None, int | None, list[str]]:
    """Resolve `text` against `candidates` (folded spelling -> canonical) by edit distance.

    Returns `(canonical, distance, [])` on a unique best match, `(None, d, [names])` when
    the match is ambiguous (a tie at the best distance across different canonicals, or a
    token too short to trust), and `(None, None, [])` when nothing is within tolerance.
    """
    if not text or not candidates:
        return None, None, []
    ranked = _rank(text, candidates)
    within = [r for r in ranked if r[0] <= max_distance]
    if not within:
        return None, None, []
    best_d = within[0][0]
    at_best = sorted({canon for d, _, canon in within if d == best_d})
    if len(text) < min_length:
        # A short token with a near neighbour is exactly the case a human cannot resolve
        # either: `Sale`, `loi`, `IPOO`. Refuse and name what it might have been.
        return None, best_d, sorted({canon for _, _, canon in within})
    if len(at_best) > 1:
        return None, best_d, at_best
    return at_best[0], best_d, []


# ---------------------------------------------------------------- event types (SPEC §1.1, §1.2)

_SYNONYMS: dict[str, tuple[str, ...]] = {
    EventType.PRICED_ROUND.value: (
        "priced round", "equity round", "priced equity", "financing round", "equity financing",
        "series seed", "series a", "series a extension", "series b", "series c", "series d", "series e", "series f",
        "seed round", "seed", "series a (recap)", "pro rata", "follow-on", "insider round", "up round", "down round",
        "recap", "round",
    ),
    EventType.CONVERTIBLE_NOTE.value: (
        "note", "convertible", "bridge", "bridge note", "bridge loan", "convertible bridge", "safe",
        "post-money safe", "pre-money safe", "convertible security",
    ),
    EventType.IPO.value: ("initial public offering", "ipo", "listing", "public listing", "listed", "went public"),
    EventType.DIRECT_LISTING.value: ("direct listing", "direct list"),
    EventType.ACQ_CLOSED.value: (
        "acquisition closed", "acquired", "exit", "exit closed", "m&a closed", "sale of company", "sold",
        "acquisition - closed", "acquisition: closed", "acqui-hire", "acquihire", "trade sale", "merger closed",
    ),
    EventType.ACQ_ANNOUNCED.value: (
        "acquisition announced", "announced acquisition", "definitive agreement", "signed definitive agreement",
        "pending acquisition", "acquisition pending", "acquisition - announced", "merger announced",
        "loi signed (acquisition)",
    ),
    EventType.ACQ_TERMINATED.value: (
        "acquisition terminated", "deal terminated", "deal cancelled", "deal canceled", "acquisition withdrawn",
        "deal fell through", "merger terminated",
    ),
    EventType.SHUTDOWN.value: (
        "shut down", "shutdown", "wind down", "wound down", "wind-down", "ceased operations", "dissolved",
        "dissolution", "liquidation", "liquidated", "chapter 7", "bankruptcy (chapter 7)", "abc",
        "assignment for the benefit of creditors", "closed down", "company closed",
    ),
    EventType.BANKRUPTCY_CH11.value: (
        "chapter 11", "bankruptcy (chapter 11)", "reorganization", "reorganisation", "restructuring (chapter 11)",
    ),
    EventType.SECONDARY.value: (
        "secondary", "secondary sale", "sold shares", "partial sale", "tender offer (sold)", "tender (sold)",
        "sale of shares",
    ),
    EventType.SECONDARY_PURCHASE.value: (
        "secondary purchase", "purchased shares", "bought shares", "tender offer (bought)", "acquired shares from",
        "secondary buy",
    ),
    EventType.TERM_SHEET.value: (
        "term sheet", "term sheet signed", "signed term sheet", "ts signed", "loi (financing)", "loi signed (financing)",
    ),
    EventType.DISTRIBUTION.value: (
        "distribution", "dividend", "cash distribution", "escrow release", "escrow released", "holdback release",
        "earn-out", "earnout", "earn out", "milestone payment", "contingent consideration", "deferred consideration",
    ),
    EventType.OWNERSHIP_ADJUSTMENT.value: (
        "ownership adjustment", "warrant exercise", "warrants exercised", "option pool expansion", "pool expansion",
        "option pool top-up", "cap table restatement", "cap table correction", "ownership correction", "true-up",
    ),
    EventType.NEW_INVESTMENT.value: (
        "new investment", "initial investment", "first investment", "first check", "new position",
        "new portfolio company",
    ),
    EventType.NOTE_REPAID.value: ("note repaid", "note repayment", "note redeemed", "bridge repaid", "loan repaid"),
}


def _build_event_index() -> dict[str, str]:
    """folded spelling -> canonical, for the canonical names and every synonym. A spelling
    that maps to two canonicals is a table error, caught at import."""
    index: dict[str, str] = {}
    for canon, syns in _SYNONYMS.items():
        for spelling in (canon, *syns):
            f = fold(spelling)
            if f in index and index[f] != canon:
                raise ValueError(f"synonym {spelling!r} maps to both {index[f]!r} and {canon!r}")
            index[f] = canon
    return index


EVENT_INDEX: dict[str, str] = _build_event_index()


def _prefix_candidates(folded: str) -> list[str]:
    """Canonicals whose synonyms begin with `folded` as a whole word: `acquisition` starts
    `acquisition closed` and `acquisition announced`; `sale` starts `sale of company` and
    `sale of shares`. Two or more distinct canonicals means the bare word is ambiguous."""
    if not folded:
        return []
    hits = {canon for spelling, canon in EVENT_INDEX.items()
            if spelling != folded and (spelling.startswith(folded + " ") or spelling.startswith(folded + " ("))}
    return sorted(hits)


def normalize_event_type(raw: object, cfg: NormalizationCfg) -> tuple[str, Correction | None]:
    """Map a cell's event text onto a canonical `EventType` value.

    Order: exact canonical -> exact synonym after folding -> the same with a trailing
    `(qualifier)` dropped -> ambiguity by whole-word prefix -> typo tolerance. Anything
    unresolved is returned as-is (stripped) so validation can raise X-909 and the engine
    M-999; an ambiguous text is returned as-is with a blocking `ambiguous` correction.
    """
    text = "" if raw is None else str(raw)
    stripped = unify_typography(text)
    if not stripped:
        return "", None
    if stripped in EVENT_INDEX.values():
        if stripped == text:
            return stripped, None
        return stripped, Correction(kind="event_type", original=text, resolved=stripped, method="whitespace")

    folded = fold(text)
    canon = EVENT_INDEX.get(folded)
    if canon is not None:
        method = "fold" if folded == fold(canon) else "synonym"
        return canon, Correction(kind="event_type", original=text, resolved=canon, method=method)

    bare = strip_trailing_qualifier(folded)
    if bare != folded:
        canon = EVENT_INDEX.get(bare)
        if canon is not None:
            return canon, Correction(kind="event_type", original=text, resolved=canon, method="synonym",
                                     detail=f"qualifier {folded[len(bare):].strip()!r} dropped")

    for probe in dict.fromkeys((folded, bare)):
        cands = _prefix_candidates(probe)
        if len(cands) >= 2:
            return stripped, Correction(kind="ambiguous", original=text, resolved="", method="prefix",
                                        detail="; ".join(cands))

    best_canon, dist, ambiguous = None, None, []
    for probe in dict.fromkeys((folded, bare)):
        c, d, amb = _fuzzy(probe, EVENT_INDEX, cfg.event_type_max_distance, cfg.min_length_for_fuzzy)
        if c is not None and (dist is None or d < dist):
            best_canon, dist, ambiguous = c, d, []
        elif c is None and amb and best_canon is None:
            dist, ambiguous = d, amb
    if best_canon is not None:
        return best_canon, Correction(kind="event_type", original=text, resolved=best_canon, method=f"distance={dist}")
    if ambiguous:
        why = "too short for typo tolerance" if len(folded) < cfg.min_length_for_fuzzy else f"tie at distance {dist}"
        return stripped, Correction(kind="ambiguous", original=text, resolved="", method="distance",
                                    detail=f"{why}; could be: " + "; ".join(ambiguous))
    return stripped, None


# ---------------------------------------------------------------- headers (SPEC §2.2)

def normalize_header(raw: object, known: Sequence[str], aliases: Mapping[str, str], cfg: NormalizationCfg,
                     ) -> tuple[str | None, Correction | None]:
    """Map a header cell onto one of `known`. Exact -> folded -> alias -> typo (<= header
    distance, unique, not short). Returns `(None, None)` for a column we do not know
    (recorded upstream as X-910) and `(None, ambiguous)` for one we cannot decide."""
    if raw is None:
        return None, None
    text = str(raw)
    stripped = unify_typography(text)
    if stripped in known:
        return stripped, None
    folded = fold(text)
    if not folded:
        return None, None
    by_fold = {fold(k): k for k in known}
    if folded in by_fold:
        return by_fold[folded], Correction(kind="header", original=text, resolved=by_fold[folded], method="fold")
    if folded in aliases:
        return aliases[folded], Correction(kind="header", original=text, resolved=aliases[folded], method="alias")
    candidates = {**by_fold, **{fold(a): k for a, k in aliases.items()}}
    canon, d, ambiguous = _fuzzy(folded, candidates, cfg.header_max_distance, cfg.min_length_for_fuzzy)
    if canon is not None:
        return canon, Correction(kind="header", original=text, resolved=canon, method=f"distance={d}")
    if ambiguous:
        why = "too short for typo tolerance" if len(folded) < cfg.min_length_for_fuzzy else f"tie at distance {d}"
        return None, Correction(kind="ambiguous", original=text, resolved="", method="distance",
                                detail=f"{why}; could be: " + "; ".join(ambiguous))
    return None, None


def closest_header(target: str, seen: Iterable[str]) -> str | None:
    """The raw header nearest to a required column, for an error message that names the fix."""
    seen = [s for s in seen if s]
    if not seen:
        return None
    return min(seen, key=lambda s: (damerau_levenshtein(fold(s), fold(target)), s))


def find_header_row(rows: Sequence[Sequence[object]], known: Sequence[str], aliases: Mapping[str, str],
                    cfg: NormalizationCfg) -> tuple[int, dict[str, int], list[str], list[Correction]] | None:
    """Scan the first `header_scan_rows` rows for the first one in which at least
    `header_min_known_columns` cells resolve to known columns.

    Returns `(row_number, {canonical: index}, [raw headers], corrections)` or `None`.
    A raw header that resolves ambiguously, or two raw headers that resolve to the same
    column, are both `ambiguous` corrections: the first wins the index, the run blocks.
    """
    for offset, row in enumerate(rows[: cfg.header_scan_rows]):
        idx: dict[str, int] = {}
        raw_headers: list[str] = []
        corrections: list[Correction] = []
        for i, cell in enumerate(row):
            if cell is None or str(cell).strip() == "":
                continue
            raw_headers.append(unify_typography(str(cell)))
            canon, corr = normalize_header(cell, known, aliases, cfg)
            if corr is not None:
                corrections.append(corr.located(row_index=offset + 1))
            if canon is None:
                continue
            if canon in idx:
                corrections.append(Correction(
                    kind="ambiguous", original=str(cell), resolved=canon, method="duplicate",
                    detail=f"column {canon!r} appears twice (columns {idx[canon] + 1} and {i + 1}); first kept",
                    row_index=offset + 1))
                continue
            idx[canon] = i
        if len(idx) >= cfg.header_min_known_columns:
            return offset + 1, idx, raw_headers, corrections
    return None


# ---------------------------------------------------------------- sheets (SPEC §2.1)

_PORTFOLIO_FALLBACKS = ("portfolio", "book", "positions", "holdings", "portfolio tab")
_QUARTER_FORMS = (
    re.compile(r"\bq([1-4])\s*[-'’ ]?\s*(\d{4}|\d{2})\b"),   # Q4 2026 | Q4-2026 | Q4'26
    re.compile(r"\b([1-4])q\s*(\d{4}|\d{2})\b"),             # 4Q26
    re.compile(r"\b(\d{4})\s*[- ]?\s*q([1-4])\b"),           # 2026 Q4 (groups reversed)
)


def find_sheet(sheetnames: Sequence[str], exact: str, fallbacks: Sequence[str] = _PORTFOLIO_FALLBACKS,
               ) -> tuple[str | None, Correction | None, list[str]]:
    """The portfolio tab: exact name -> folded name -> any of the fallback words. Returns
    `(name, correction, candidates)`; `name` is None when nothing matched, and the
    candidate list carries every fallback hit so the caller can refuse a plural."""
    if exact in sheetnames:
        return exact, None, [exact]
    folded = {fold(s): s for s in sheetnames}
    if fold(exact) in folded:
        name = folded[fold(exact)]
        return name, Correction(kind="sheet", original=exact, resolved=name, method="fold"), [name]
    hits = [folded[f] for f in folded if f in fallbacks]
    if len(hits) == 1:
        return hits[0], Correction(kind="sheet", original=exact, resolved=hits[0], method="fallback"), hits
    return None, None, hits


def relaxed_activity_candidates(sheetnames: Sequence[str]) -> list[str]:
    """Any sheet whose folded name contains `activity` or `events`."""
    return [s for s in sheetnames if "activity" in fold(s) or "events" in fold(s)]


def parse_quarter_label(sheet_name: str) -> str | None:
    """`Q4-2026 Activity` / `4Q26 Activity` / `2026 Q4 Activity` -> `Q4 2026`; None when the
    name carries no quarter+year (the policy label is used instead)."""
    f = fold(sheet_name)
    for i, rx in enumerate(_QUARTER_FORMS):
        m = rx.search(f)
        if not m:
            continue
        q, y = (m.group(2), m.group(1)) if i == 2 else (m.group(1), m.group(2))
        year = int(y) if len(y) == 4 else 2000 + int(y)
        return f"Q{q} {year}"
    return None


# ---------------------------------------------------------------- companies (SPEC §2.3)

_SUFFIX_RX = re.compile(r"[\s,]+(inc|llc|ltd|corp|co|plc)\.?$")
_FORMERLY_RXS = (
    re.compile(r"^(?P<x>.+?)\s*\((?:formerly|fka|f/k/a|previously)\s+(?P<y>[^()]+)\)$", re.I),
    re.compile(r"^(?P<x>.+?),\s*(?:formerly|fka|f/k/a|previously)\s+(?P<y>.+)$", re.I),
    re.compile(r"^(?P<y>.+?)\s*(?:->|→)\s*(?P<x>.+)$"),
)


def clean_company(raw: object) -> tuple[str, Correction | None]:
    """Strip, collapse whitespace, unify curly quotes and dashes. Used on the Portfolio
    tab, where there is no book yet to match against."""
    text = "" if raw is None else str(raw)
    cleaned = unify_typography(text)
    if cleaned == text:
        return cleaned, None
    return cleaned, Correction(kind="company", original=text, resolved=cleaned, method="whitespace")


def _strip_suffix(folded: str) -> str:
    return _SUFFIX_RX.sub("", folded).strip(_EDGE_PUNCT)


def _match_plain(text: str, book: Sequence[str]) -> tuple[str | None, str | None]:
    """exact -> folded exact -> folded after stripping a corporate suffix on either side.
    Returns (book name, method)."""
    cleaned = unify_typography(text)
    if cleaned in book:
        return cleaned, None if cleaned == text else "whitespace"
    f = fold(cleaned)
    by_fold = {fold(b): b for b in book}
    if f in by_fold:
        return by_fold[f], "fold"
    by_suffix = {_strip_suffix(fold(b)): b for b in book}
    if _strip_suffix(f) in by_suffix:
        return by_suffix[_strip_suffix(f)], "suffix"
    return None, None


def _extends(folded_other: str, folded_name: str) -> bool:
    """True when `folded_other` is `folded_name` plus at least one more word (`aravine labs`
    extends `aravine`; `aravinex` does not)."""
    return folded_other.startswith(folded_name + " ") or folded_other.endswith(" " + folded_name)


def match_company(raw: object, book: Sequence[str], cfg: NormalizationCfg) -> tuple[str, Correction | None]:
    """Resolve an activity-row company against the Portfolio names.

    exact -> folded -> corporate suffix -> "X (formerly Y)" / "X, formerly Y" / "Y -> X"
    where either side matches -> Damerau-Levenshtein <= company_max_distance on names of
    at least company_min_length_for_fuzzy characters, unique. Unresolved names come back
    cleaned with no correction (X-901 / X-918 downstream); a near-miss that is short or
    tied comes back with a blocking `ambiguous` correction.
    """
    text = "" if raw is None else str(raw)
    cleaned = unify_typography(text)
    if not cleaned:
        return "", None

    name, method = _match_plain(text, book)
    if name is not None:
        if method is None:
            return name, None
        return name, Correction(kind="company", original=text, resolved=name, method=method)

    for rx in _FORMERLY_RXS:
        m = rx.match(cleaned)
        if not m:
            continue
        hits = []
        for side in ("x", "y"):
            n, _ = _match_plain(m.group(side), book)
            if n is not None and n not in hits:
                hits.append(n)
        if len(hits) == 1:
            return hits[0], Correction(kind="company", original=text, resolved=hits[0], method="formerly")
        if len(hits) > 1:
            return cleaned, Correction(kind="ambiguous", original=text, resolved="", method="formerly",
                                       detail="both names are in the book: " + "; ".join(hits))

    f = fold(cleaned)
    canon, d, ambiguous = _fuzzy(f, {fold(b): b for b in book}, cfg.company_max_distance, cfg.company_min_length_for_fuzzy)
    if canon is not None:
        # A typo-match is only trusted when no *other* book name extends the match: `Aravin`
        # sits at distance 1 from `Aravine`, but if the book also holds `Aravine Labs` the deal
        # team may have meant either, and the engine must not re-mark one of them on a guess.
        # (An exact or folded match above is never second-guessed this way.)
        extended = sorted(b for b in book if b != canon and _extends(fold(b), fold(canon)))
        if extended:
            return cleaned, Correction(kind="ambiguous", original=text, resolved="", method="distance",
                                       detail=f"typo-match {canon!r} is a prefix of another book name; could be: "
                                              + "; ".join([canon, *extended]))
        return canon, Correction(kind="company", original=text, resolved=canon, method=f"distance={d}")
    if ambiguous:
        why = "too short for typo tolerance" if len(f) < cfg.company_min_length_for_fuzzy else f"tie at distance {d}"
        # Name every book entry that extends a near-miss too, so the reviewer sees the whole choice.
        for cand in list(ambiguous):
            ambiguous += [b for b in book if b not in ambiguous and _extends(fold(b), fold(cand))]
        return cleaned, Correction(kind="ambiguous", original=text, resolved="", method="distance",
                                   detail=f"{why}; could be: " + "; ".join(ambiguous))
    return cleaned, None


def infer_fund(*texts: str) -> str:
    """`Fund I/II/III` mentioned in Notes/Detail, else `Unassigned` (SPEC X-918)."""
    for t in texts:
        m = re.search(r"\bfund\s+(iii|ii|i|iv|v|\d+)\b", t or "", re.I)
        if m:
            return f"Fund {m.group(1).upper()}"
    return "Unassigned"


# ---------------------------------------------------------------- numbers (SPEC §2.3)

BLANK_TOKENS: frozenset[str] = frozenset({"", "-", "—", "–", "n/a", "na", "tbd", "?", "none", "null", "nan"})
_CURRENCY_SYMBOLS = ("€", "£", "¥")
_CURRENCY_CODES = re.compile(r"\b(EUR|GBP|CHF|JPY|CAD|AUD)\b")
_NUMBER_RX = re.compile(
    r"^(?P<open>\()?\s*(?P<sign>[-+])?\s*\$?\s*(?P<sign2>[-+])?\s*"
    r"(?P<num>(?:(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?|\.\d+)(?:e[-+]?\d+)?)\s*"
    r"(?P<suffix>k|m|mm|mn|b|bn)?\s*(?P<close>\))?\s*(?P<pct>%)?$",
    re.I,
)
_SUFFIX_SCALE = {"k": 1e-3, "m": 1.0, "mm": 1.0, "mn": 1.0, "b": 1e3, "bn": 1e3}  # relative to $M


def currency_hit(text: str) -> str | None:
    """The non-USD currency marker found in `text`, if any. `$` and `USD` are fine."""
    for sym in _CURRENCY_SYMBOLS:
        if sym in text:
            return sym
    m = _CURRENCY_CODES.search(text)
    return m.group(1) if m else None


def is_blank_token(text: str) -> bool:
    return fold(text) in BLANK_TOKENS


def coerce_number(raw: object) -> tuple[float | None, Correction | None]:
    """A cell -> float. Numbers pass through; blank tokens -> None silently (they *are*
    the blank representation); text is parsed (`$28.2M`, `(1.2)`, `28,200,000`, `5.5 %`)
    and recorded as X-915 because a text cell where a number should be is worth knowing
    about. Non-USD currency -> `currency` (X-920). Anything else -> `unparseable` (X-902).
    A percentage sign is applied here (`5.5%` -> 0.055) and reported in the method so the
    percent-points heuristic does not double-convert it."""
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return None, Correction(kind="unparseable", original=str(raw), resolved="", method="boolean")
    if isinstance(raw, (int, float)):
        return float(raw), None
    if isinstance(raw, (datetime, date)):
        return None, Correction(kind="unparseable", original=raw.isoformat(), resolved="", method="date-in-number-cell")
    text = str(raw)
    if is_blank_token(text):
        return None, None
    hit = currency_hit(text)
    if hit is not None:
        return None, Correction(kind="currency", original=text, resolved="", method="value", detail=hit)
    m = _NUMBER_RX.match(unify_typography(text))
    if not m or not m.group("num") or m.group("num") == ".":
        return None, Correction(kind="unparseable", original=text, resolved="", method="text")
    if bool(m.group("open")) != bool(m.group("close")):
        return None, Correction(kind="unparseable", original=text, resolved="", method="unbalanced-parenthesis")
    value = float(m.group("num").replace(",", ""))
    negative = bool(m.group("open")) or "-" in (m.group("sign") or "", m.group("sign2") or "")
    if negative:
        value = -value
    suffix = (m.group("suffix") or "").lower()
    if suffix:
        value *= _SUFFIX_SCALE[suffix]
    method = "text"
    if m.group("pct"):
        value /= 100.0
        method = "percent-sign"
    elif suffix:
        method = f"suffix={suffix}"
    elif m.group("open"):
        method = "parenthesised-negative"
    elif "," in m.group("num"):
        method = "thousands-separator"
    return value, Correction(kind="value", original=text, resolved=repr(value), method=method)


def coerce_musd(raw: object, cfg: NormalizationCfg) -> tuple[float | None, list[Correction]]:
    """A $M cell. A magnitude above `unit_suspect_musd_above` was typed in dollars: divide
    by 1e6 and record the assumption (X-916)."""
    value, corr = coerce_number(raw)
    corrections = [corr] if corr is not None else []
    if value is not None and abs(value) > cfg.unit_suspect_musd_above:
        scaled = value / 1e6
        corrections.append(Correction(kind="unit", original=str(raw), resolved=repr(scaled), method="usd->musd",
                                      detail=f"{value:,.0f} exceeds {cfg.unit_suspect_musd_above:,.0f}; read as dollars"))
        value = scaled
    return value, corrections


def coerce_percent(raw: object, cfg: NormalizationCfg, *, points_heuristic: bool = True,
                   ) -> tuple[float | None, list[Correction]]:
    """A fraction cell (`0.055`). `5.5%` is converted by the sign. A bare value above
    `percent_points_above` and up to `percent_block_above` was typed in points -> /100
    with X-916 (only when `points_heuristic`; growth legitimately exceeds 100%). Above
    `percent_block_above` it is neither -> `percent_block` (X-903)."""
    value, corr = coerce_number(raw)
    corrections = [corr] if corr is not None else []
    if value is None or (corr is not None and corr.method == "percent-sign"):
        return value, corrections
    if value > cfg.percent_block_above:
        corrections.append(Correction(kind="percent_block", original=str(raw), resolved="", method="out-of-range",
                                      detail=f"{value} is above {cfg.percent_block_above:g}: not a fraction, not percentage points"))
        return value, corrections
    if points_heuristic and value > cfg.percent_points_above:
        scaled = value / 100.0
        corrections.append(Correction(kind="unit", original=str(raw), resolved=repr(scaled), method="points->fraction",
                                      detail=f"{value:g} exceeds {cfg.percent_points_above:g}; read as percentage points"))
        value = scaled
    return value, corrections


# ---------------------------------------------------------------- dates (SPEC §2.3)

# Excel's 1900 date system: serial 1 = 1900-01-01, with the (deliberate) Lotus leap-year bug,
# which is why the epoch is 1899-12-30. The serial bounds are calendar facts, not policy:
# 20000 = 1954-10-03 and 80000 = 2119-01-03 bracket any date this book can hold.
_EXCEL_EPOCH = date(1899, 12, 30)
EXCEL_SERIAL_MIN = 20000
EXCEL_SERIAL_MAX = 80000
_DATE_FORMATS: tuple[tuple[str, str], ...] = (
    ("%Y-%m-%d", "iso"), ("%Y-%m-%d %H:%M:%S", "iso-datetime"), ("%Y-%m-%dT%H:%M:%S", "iso-datetime"),
    ("%m/%d/%Y", "m/d/yyyy"), ("%m/%d/%y", "m/d/yy"),
    ("%d-%b-%Y", "dd-Mon-yyyy"), ("%d-%b-%y", "dd-Mon-yy"),
    ("%b %d, %Y", "Mon d, yyyy"), ("%B %d, %Y", "Month d, yyyy"), ("%b %d %Y", "Mon d yyyy"),
    ("%Y/%m/%d", "yyyy/mm/dd"), ("%d %b %Y", "d Mon yyyy"), ("%d %B %Y", "d Month yyyy"),
)
_SLASH_RX = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")


class DateParseError(ValueError):
    """The cell is not a date in any accepted form; the reader turns this into IngestError."""


def coerce_date(raw: object) -> tuple[date | None, Correction | None]:
    """A cell -> date. `datetime`/`date` pass through untouched; an Excel serial in
    [EXCEL_SERIAL_MIN, EXCEL_SERIAL_MAX] is converted (X-915); strings are tried against
    the accepted formats (X-915). A slash date whose parts are both <= 12 is read
    month-first with the ambiguity recorded; one whose first part is > 12 can only be
    day-first and is read so, recorded. Blank -> None. Anything else raises."""
    if raw is None:
        return None, None
    if isinstance(raw, datetime):
        return raw.date(), None
    if isinstance(raw, date):
        return raw, None
    if isinstance(raw, bool):
        raise DateParseError(f"{raw!r} is not a date")
    if isinstance(raw, (int, float)):
        if EXCEL_SERIAL_MIN <= raw <= EXCEL_SERIAL_MAX:
            d = _EXCEL_EPOCH + timedelta(days=int(raw))
            return d, Correction(kind="value", original=repr(raw), resolved=d.isoformat(), method="excel-serial")
        raise DateParseError(f"{raw!r} is outside the Excel serial range {EXCEL_SERIAL_MIN}..{EXCEL_SERIAL_MAX}")
    text = unify_typography(str(raw))
    if is_blank_token(text):
        return None, None
    m = _SLASH_RX.match(text)
    if m:
        first, second = int(m.group(1)), int(m.group(2))
        if first > 12 and second <= 12:
            try:
                d = datetime.strptime(text, "%d/%m/%Y" if len(m.group(3)) == 4 else "%d/%m/%y").date()
            except ValueError:
                raise DateParseError(f"{text!r} is not a valid day-first date") from None
            return d, Correction(kind="value", original=text, resolved=d.isoformat(), method="day-first",
                                 detail="first part exceeds 12, so the date can only be day-first")
    for fmt, label in _DATE_FORMATS:
        try:
            d = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        detail = ""
        if m and int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and int(m.group(1)) != int(m.group(2)):
            detail = f"ambiguous day/month order; read month-first ({d.isoformat()}), day-first would be {date(d.year, d.day, d.month).isoformat()}"
        return d, Correction(kind="value", original=text, resolved=d.isoformat(), method=label, detail=detail)
    raise DateParseError(f"{text!r} is not a date in any accepted form "
                         "(YYYY-MM-DD, MM/DD/YYYY, M/D/YY, DD-Mon-YYYY, Mon D, YYYY, YYYY/MM/DD, or an Excel date)")


# ---------------------------------------------------------------- structure (SPEC §2.4)

_TOTAL_WORDS: frozenset[str] = frozenset({"total", "totals", "sum", "grand total", "subtotal", "sub-total", "sub total"})


def row_is_blank(row: Sequence[object]) -> bool:
    return all(v is None or (isinstance(v, str) and v.strip() == "") for v in row)


def row_is_total(row: Sequence[object]) -> bool:
    """The first non-empty cell folds to a totals word."""
    for v in row:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            continue
        return isinstance(v, str) and fold(v) in _TOTAL_WORDS
    return False


def row_is_note(row: Sequence[object]) -> bool:
    """Text in the first cell and nothing else anywhere: a trailing remark, not data."""
    if not row or not isinstance(row[0], str) or row[0].strip() == "":
        return False
    return all(v is None or (isinstance(v, str) and v.strip() == "") for v in row[1:])
