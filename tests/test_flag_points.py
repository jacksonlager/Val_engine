"""Flag summary points: the two or three scannable lines the review tool shows on a card.

The contract is in `engine/state.py::Working.flag` — a flag a reviewer must act on is
readable at a glance, MONITOR stays prose, and the full reasoning never leaves `message`.
"""
from __future__ import annotations

import re

import pytest

from hc_valuation.config import repo_root
from hc_valuation.engine.inputs import Position, Status
from hc_valuation.engine.models import Severity
from hc_valuation.engine.state import Working, summarise
from hc_valuation.export.tables import exceptions_table
from hc_valuation.pipeline import RunPaths, execute

MAX_POINT_CHARS = 180   # a line that does not wrap three times in the card


@pytest.fixture(scope="module")
def run():
    return execute(RunPaths.default(), provider="stub").run


def _working() -> Working:
    from datetime import date
    pos = Position(company="Acme", fund="Fund I", sector="AI/ML", stage="Series A", status=Status.ACTIVE,
                   first_investment=date(2024, 1, 1), latest_round=date(2025, 1, 1), latest_post_money=100.0,
                   invested=5.0, ownership=0.1, prior_mark=10.0, realized=0.0, row_index=2)
    return Working(pos=pos, quarter_label="Q3 2026", sheet_name="Q3 2026 Activity")


# ---------------------------------------------------------------- the contract

def test_action_flags_carry_points_and_monitor_flags_do_not(run):
    seen = 0
    for c in run.companies:
        for f in c.flags:
            if f.severity is Severity.MONITOR:
                assert f.points == (), f"{c.company} {f.rule_id}: MONITOR carries context, not points"
            else:
                seen += 1
                assert 1 <= len(f.points) <= 3, f"{c.company} {f.rule_id}: {len(f.points)} points"
                assert f.action, f"{c.company} {f.rule_id}: an actionable flag must say what to do"
    assert seen > 20, "the real book should exercise plenty of BLOCK/REVIEW flags"


def test_points_are_short_and_never_replace_the_full_message(run):
    for c in run.companies:
        for f in c.flags:
            for p in f.points:
                assert p.strip() == p and p, f"{f.rule_id}: {p!r}"
                assert len(p) <= MAX_POINT_CHARS, f"{f.rule_id}: point too long to scan ({len(p)}): {p}"
                assert p.count("**") % 2 == 0, f"{f.rule_id}: unbalanced emphasis in {p!r}"
            # the long form is always there, and is never merely the points glued together
            assert len(f.message) >= 40


def test_emphasis_marks_one_to_three_spans_per_point(run):
    """`**bold**` is for the words that carry the decision — a point that bolds everything
    (or nothing, on a hand-written point) has stopped guiding the eye."""
    unbolded: list[str] = []
    for c in run.companies:
        for f in c.flags:
            for p in f.points:
                spans = re.findall(r"\*\*(.+?)\*\*", p)
                assert len(spans) <= 3, f"{f.rule_id}: {len(spans)} bold spans in {p!r}"
                for sp in spans:
                    assert len(sp) <= 70, f"{f.rule_id}: bold span is a sentence, not a phrase: {sp!r}"
                if not spans:
                    unbolded.append(f"{f.rule_id}: {p}")
    # derived points (a YAML-promoted rule) carry no emphasis; authored ones should
    assert len(unbolded) <= 2, "authored points should mark the words that matter:\n" + "\n".join(unbolded[:5])


def test_flag_rejects_a_monitor_with_points_and_too_many_points():
    w = _working()
    with pytest.raises(ValueError, match="carries no summary points"):
        w.flag("X-999", "treatment", Severity.MONITOR, "Context only.", points=("a", "b"))
    with pytest.raises(ValueError, match="at most three summary points"):
        w.flag("X-999", "treatment", Severity.REVIEW, "Why.", action="Do it.", points=("a", "b", "c", "d"))


def test_a_flag_without_authored_points_falls_back_to_its_own_sentences():
    w = _working()
    w.flag("X-999", "treatment", Severity.REVIEW,
           "The first thing happened. The second thing follows. A third. And a fourth.",
           action="Check it.")
    assert w.flags[-1].points == ("The first thing happened.", "The second thing follows.", "A third.")


def test_summarise_never_rewrites_and_keeps_a_single_sentence_whole():
    assert summarise("One sentence, no split.") == ("One sentence, no split.",)
    assert summarise("A. B. C. D.", limit=2) == ("A.", "B.")
    assert summarise("  padded.  ") == ("padded.",)
    # a decimal or a $ figure must not be mistaken for a sentence end
    assert summarise("Priced at $14.2M against $23.9M last round.") == ("Priced at $14.2M against $23.9M last round.",)


# ---------------------------------------------------------------- exports

def test_exceptions_export_carries_action_summary_and_message(run):
    t = exceptions_table(run)
    assert t.headers[-4:] == ["Action", "Summary", "Suggestions", "Message"]
    rows = {r[2]: r for r in t.rows if r[4] != "MONITOR"}
    assert rows, "the real book has actionable flags"
    for rule_id, r in rows.items():
        assert r[5], f"{rule_id}: no action in the export"
        assert r[6].startswith("· "), f"{rule_id}: summary should be bulleted"
        assert "**" not in r[6], f"{rule_id}: emphasis markers must not leak into a spreadsheet cell"
        assert "→ $" in r[7], f"{rule_id}: every actionable flag offers at least one priced suggestion"


def test_frontend_type_declares_points():
    """The card cannot render what the type does not admit; a stale type is a silent blank."""
    ts = (repo_root() / "frontend" / "src" / "types.ts").read_text()
    assert re.search(r"points:\s*string\[\];", ts)
