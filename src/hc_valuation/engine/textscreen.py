"""One way to ask whether a sentence *says* a term — shared by the note screen (X-105) and the
lead-investor test behind X-122.

Whole-word, hyphen-tolerant, and negation-aware: "no default" does not say default, and "no new
investor" does not name a new investor. Found by the synthetic Q1 2027 chain (HARDENING_REPORT.md,
D-6): a round whose notes read "No new investor" was treated as one led by an outside investor,
which downgraded X-122 from REVIEW to MONITOR.
"""
from __future__ import annotations

import re

NEGATIONS = ("no ", "not in ", "without ", "no longer in ", "not ")
# A negator up to three words before the term still negates it: "no new outside investor" names nobody,
# "not subject to any lock-up" has no lock-up. Found by a stress workbook whose internal round read
# "no new outside investor set the price" and was treated as one led by an outside investor.
_NEGATED_BEFORE = re.compile(r"\b(?:no|not|without|never|nor)\b(?:[\s-]+[\w']+){0,3}[\s-]+$")


def term_in(term: str, text: str) -> bool:
    text, term = text.lower(), term.lower()     # "No new investor" negates as surely as "no new investor"
    pattern = r"(?<![\w-])" + r"[\s-]?".join(re.escape(part) for part in re.split(r"[\s-]+", term)) + r"(?![\w-])"
    for m in re.finditer(pattern, text):
        before = text[max(0, m.start() - 40):m.start()]
        if any(before.endswith(n) for n in NEGATIONS) or _NEGATED_BEFORE.search(before):
            continue
        return True
    return False


def any_term_in(terms: tuple[str, ...], text: str) -> bool:
    return any(term_in(t, text) for t in terms)
