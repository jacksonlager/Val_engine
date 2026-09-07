"""The reader's one contact with the Anthropic SDK: `ClaudeReader._call`. A fake `anthropic`
module stands in for the real one so the test checks the request shape (model, system prompt,
one user message carrying the rows as JSON) and the reply handling (text blocks joined, a fenced
JSON block unwrapped, a non-object rejected) without a key, a network or the package."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from hc_valuation.notes.reader import SYSTEM_PROMPT, ClaudeReader


class _Block:
    def __init__(self, text: str) -> None:
        self.text = text


class _Msg:
    def __init__(self, blocks: list[_Block]) -> None:
        self.content = blocks


def _fake_anthropic(reply_text: str, seen: dict):
    mod = types.ModuleType("anthropic")

    class Anthropic:
        def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
            seen["api_key_given"] = bool(api_key)
            seen["timeout"] = timeout
            self.messages = self

        def create(self, **kw):
            seen["request"] = kw
            return _Msg([_Block(reply_text[: len(reply_text) // 2]), _Block(reply_text[len(reply_text) // 2:])])

    mod.Anthropic = Anthropic
    return mod


def test_call_sends_the_rows_and_unwraps_a_fenced_reply(tmp_path: Path, monkeypatch):
    seen: dict = {}
    answer = {"rows": [{"row_index": 2, "aspects": [], "conflicts": [], "supersedes_portfolio_tab": [], "instructions": [],
                        "novel": None, "confidence": 1.0}]}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic("```json\n" + json.dumps(answer) + "\n```", seen))
    reader = ClaudeReader(tmp_path / "cache", model="claude-test", api_key="k", timeout_s=12.0)
    payload = {"company": "Alpha", "rows": [{"row_index": 2, "event": "Priced Equity Round", "detail": "Series B", "notes": "escrow"}]}
    data = reader._call(payload)
    assert data == answer and reader.calls == 1
    req = seen["request"]
    assert req["model"] == "claude-test" and req["system"] == SYSTEM_PROMPT and req["max_tokens"] >= 1000
    assert len(req["messages"]) == 1 and req["messages"][0]["role"] == "user"
    assert json.loads(req["messages"][0]["content"].split("\n", 1)[1]) == payload
    assert seen["api_key_given"] is True and seen["timeout"] == 12.0


def test_call_rejects_a_reply_that_is_not_an_object(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic("[1, 2, 3]", {}))
    reader = ClaudeReader(tmp_path / "cache", model="m", api_key="k")
    with pytest.raises(ValueError):
        reader._call({"company": "Alpha", "rows": []})
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic("not json at all", {}))
    with pytest.raises(json.JSONDecodeError):
        reader._call({"company": "Alpha", "rows": []})
