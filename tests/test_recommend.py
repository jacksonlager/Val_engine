"""One recommendation per actionable flag (recommend.py): chosen among the engine's priced
suggestions by the policy default or by Claude, cached, validated, never priced by a model."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hc_valuation.config import load_config
from hc_valuation.engine.models import Severity
from hc_valuation.pipeline import RunPaths, execute
from hc_valuation.recommend import (CACHE_DIR, ClaudeChooser, PolicyChooser, brief_hash, build_brief, make_chooser,
                                    recommend_run)


@pytest.fixture(scope="module")
def base():
    return execute(RunPaths.default(), provider="stub", recommender="policy")


def _first_actionable(run):
    for c in run.companies:
        for f in c.flags:
            if f.severity is not Severity.MONITOR and len(f.suggestions) >= 2:
                return c, f
    raise AssertionError("no flag with two or more suggestions")


# ---------------------------------------------------------------- policy chooser

def test_every_actionable_flag_gets_exactly_one_recommendation_and_monitor_none(base):
    run = base.run
    assert run.manifest.recommender == "policy"
    for c in run.companies:
        for f in c.flags:
            if f.severity is Severity.MONITOR or not f.suggestions:
                assert f.recommendation is None
            else:
                r = f.recommendation
                assert r is not None and r.source == "policy" and r.model is None
                assert r.key == f.suggestions[0].key and r.booked == f.suggestions[0].booked
                assert r.label == f.suggestions[0].label and r.reasons == f.suggestions[0].reasons


def test_recommendation_changes_nothing_else(base):
    plain = execute(RunPaths.default(), provider="stub").run
    for a, b in zip(plain.companies, base.run.companies):
        assert (a.proposed_mark, a.booked_mark, a.disposition) == (b.proposed_mark, b.booked_mark, b.disposition)
        assert [f.rule_id for f in a.flags] == [f.rule_id for f in b.flags]
    assert plain.totals == base.run.totals


# ---------------------------------------------------------------- the brief

def test_brief_carries_the_case_and_only_priced_candidates(base):
    c, f = _first_actionable(base.run)
    brief = build_brief(c, f, base.run)
    assert brief["company"]["name"] == c.company and brief["flag"]["rule_id"] == f.rule_id
    assert [x["key"] for x in brief["candidates"]] == [s.key for s in f.suggestions]
    assert all("booked_musd" in x for x in brief["candidates"])
    assert brief["policy_default_key"] == f.suggestions[0].key
    assert "**" not in json.dumps(brief)          # emphasis markers stripped for the model
    h1 = brief_hash(brief, "p", "m")
    assert h1 == brief_hash(json.loads(json.dumps(brief)), "p", "m") and h1 != brief_hash(brief, "p2", "m")


# ---------------------------------------------------------------- claude chooser, mocked

class _Fake(ClaudeChooser):
    """Replaces the network call with a canned reply; counts calls like the real one."""
    def __init__(self, cache_dir: Path, reply: str, **kw):
        super().__init__(cache_dir, api_key="test-key", **kw)
        self.reply = reply

    def _call(self, brief):
        self.calls += 1
        return self.reply


def _reply(choice: str, label: str = "Book the full deal value now.", conf: float = 0.8) -> str:
    return json.dumps({"choice": choice, "label": label,
                       "reasons": ["The buyer has signed; only approval remains.", "Closing conditions look like formalities."],
                       "rationale": "A signed agreement with only regulatory approval outstanding is close to certain.",
                       "confidence": conf})


def test_claude_choice_is_validated_priced_by_the_engine_and_cached(base, tmp_path: Path):
    c, f = _first_actionable(base.run)
    other = f.suggestions[1]
    ch = _Fake(tmp_path / "rec", _reply(other.key))
    brief = build_brief(c, f, base.run)
    rec = ch.choose(brief, f)
    assert rec.source == "claude" and rec.model == ch.model and rec.key == other.key
    assert rec.booked == other.booked                      # the number is the engine's, never the reply's
    assert rec.label == "Book the full deal value now." and len(rec.reasons) == 2 and rec.confidence == 0.8
    assert ch.calls == 1
    files = list((tmp_path / "rec").glob("*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert record["company"] == c.company and record["rule_id"] == f.rule_id and record["answer"]["choice"] == other.key
    # second time: the cache answers, no call — and it works with no API key at all
    ch2 = _Fake(tmp_path / "rec", _reply(f.suggestions[0].key))
    ch2.api_key = None
    rec2 = ch2.choose(brief, f)
    assert rec2.key == other.key and rec2.source == "claude" and ch2.calls == 0 and ch2.cache_hits == 1


def test_claude_reply_that_is_not_a_candidate_falls_back_to_policy_and_says_so(base, tmp_path: Path):
    c, f = _first_actionable(base.run)
    ch = _Fake(tmp_path / "rec", _reply("invent_a_number"))
    rec = ch.choose(build_brief(c, f, base.run), f)
    assert rec.source == "policy" and rec.key == f.suggestions[0].key
    assert rec.note and "not a candidate" in rec.note and ch.fallbacks
    assert not list((tmp_path / "rec").glob("*.json"))    # a rejected answer is never cached


def test_claude_without_key_or_cache_is_the_policy_default_with_a_note(base, tmp_path: Path):
    ch = ClaudeChooser(tmp_path / "rec", api_key=None)
    c, f = _first_actionable(base.run)
    rec = ch.choose(build_brief(c, f, base.run), f)
    assert rec.source == "policy" and "not connected" in (rec.note or "")     # a reviewer's sentence, not the variable's name


def test_parse_rejects_bad_shapes(base):
    c, f = _first_actionable(base.run)
    good = json.loads(_reply(f.suggestions[0].key))
    for bad in (
        {**good, "extra": 1},
        {**good, "reasons": []},
        {**good, "confidence": 1.7},
        {**good, "label": ""},
        [good],
    ):
        with pytest.raises((ValueError, TypeError, AttributeError)):
            ClaudeChooser.parse(json.dumps(bad), f)
    fenced = "```json\n" + json.dumps(good) + "\n```"
    assert ClaudeChooser.parse(fenced, f)["choice"] == f.suggestions[0].key
    # wording that runs long is clipped to the card, not thrown away: the choice is the substance (the
    # live model wrote 150-character labels and every answer was being rejected — stress workbook 2)
    long = ClaudeChooser.parse(json.dumps({**good, "label": "word " * 40, "reasons": ["only one"]}), f)
    assert long["choice"] == good["choice"] and len(long["label"]) <= 140 and long["label"].endswith("…")
    assert len(long["reasons"]) == 2 and long["reasons"][0] == "only one"


def test_recommend_run_with_claude_labels_the_manifest(base, tmp_path: Path):
    c, f = _first_actionable(base.run)
    ch = _Fake(tmp_path / "rec", _reply(f.suggestions[1].key))
    run = recommend_run(base.run, ch)
    assert run.manifest.recommender == f"claude:{ch.model}"
    assert run.by_company()[c.company].flags[[g.rule_id for g in c.flags].index(f.rule_id)].recommendation.source == "claude"


def test_make_chooser_follows_policy_then_override():
    cfg = load_config(RunPaths.default().policy)
    # the shipped policy asks for claude; an explicit argument still wins in either direction
    assert cfg.recommendation.provider == "claude"
    assert isinstance(make_chooser(cfg, Path("/tmp")), ClaudeChooser)
    assert isinstance(make_chooser(cfg, Path("/tmp"), "policy"), PolicyChooser)
    ch = make_chooser(cfg, Path("/tmp"), "claude")
    assert isinstance(ch, ClaudeChooser) and ch.cache_dir == Path("/tmp") / CACHE_DIR and ch.model == cfg.recommendation.model
