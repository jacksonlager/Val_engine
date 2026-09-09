"""The one resolution put forward on each BLOCK/REVIEW flag — chosen, never priced.

Every actionable flag carries one to three *suggestions* the rule itself priced (ratify the
proposal, hold the prior mark, the full deal value, a comps calibration, cost as a floor).
This module picks **one** of them to show first and writes the sentence and the two reasons
the reviewer reads. Two choosers:

- `policy` — the rule's own default: its first suggestion, worded as the rule wrote it.
  Deterministic, offline, always available.
- `claude` — the Anthropic SDK is asked to choose among the candidates and explain the
  choice for this company's facts (the flag, the position, the vendor signals). Its reply
  is validated hard: the `choice` must be one of the candidate keys, and the booked number
  is taken from that candidate, never from the reply.

Two levels. Every actionable flag still gets its own `Recommendation`, because that is what
prices the options a reviewer can pick from. On top of it each *position* gets one
`PositionRecommendation`: the single next step, chosen across every finding on the position
rather than one per flag. That is the harder judgment and the one a model is actually useful
for — three findings on one company are not three independent questions, and a reviewer wants
to know which to act on first and what it settles. The same fences apply: the step must name a
finding on the position and one of that finding's priced suggestions, `covers` must be a subset
of the position's actionable findings, and the number comes from the suggestion. Every answer is cached under
  `data/recommendations/<sha>.json`, keyed by a hash of the case brief, the prompt and the
  model, so a rerun is deterministic and needs no network; a miss without an API key falls
  back to `policy` and the recommendation says so.

Either way the reviewer still confirms under a named approver, the other candidates stay
one click away, and accepting a recommendation records an ordinary E-01 override. This runs
in the pipeline after the engine: the engine never holds a client.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import RuleConfig
from .engine.models import CompanyResult, Flag, PositionRecommendation, Recommendation, Severity, Suggestion, ValuationRun
from .notes.schema import _figures, figures_carried
from .engine.readiness import MISSING_INPUT_RULES

log = logging.getLogger(__name__)

CACHE_DIR = Path("data") / "recommendations"
DEFAULT_MODEL = "claude-sonnet-4-5"

SYSTEM_PROMPT = """You are the assistant to the valuation reviewer at a venture capital fund. Each quarter the fund's
valuation engine proposes a mark for every portfolio company and flags the positions a human must decide on.
For one such flag you will receive a case brief: the company's position, what the engine proposed and why it
stopped, and a short list of CANDIDATE RESOLUTIONS the engine has already priced.

Choose exactly ONE candidate and explain it for this case. Rules you must follow:
- You may only choose among the candidates by their `key`. Never propose a different number or treatment.
- Reason from fair-value principles (ASC 820: the price an orderly market participant would pay at the
  measurement date; observable inputs over unobservable; a quoted price for a listed security is Level 1),
  from the fund's stated policy defaults, and from conservatism where the evidence is thin.
- Be specific to the brief: cite the figures and facts given. Do not invent facts.
- Keep the wording plain. No hedging filler.

Reply with ONE JSON object and nothing else:
{"choice": "<candidate key>",
 "label": "<one sentence, imperative, at most 110 characters, ending with a period>",
 "reasons": ["<short line, at most 110 characters>", "<short line, at most 110 characters>"],
 "rationale": "<at most 60 words on why this beats the other candidates>",
 "confidence": <number between 0 and 1>}"""

POSITION_PROMPT = """You are the assistant to the valuation reviewer at a venture capital fund. Each quarter the fund's
valuation engine proposes a mark for every portfolio company and raises findings a human must resolve before the
mark is booked. For ONE company you will receive its position, what the engine proposed, and EVERY open finding,
each with the CANDIDATE RESOLUTIONS the engine has already priced for it.

The reviewer wants one thing to do first. Choose the finding to lead with and one of that finding's candidates.

Rules you must follow:
- Choose one `rule_id` from the findings given, and a `choice` that is one of THAT finding's candidate keys.
  Never propose a different number, a different treatment, or a finding that is not listed.
- Lead with what the others depend on. A missing input outranks a judgment: there is no supported mark until it
  is supplied, so a step that obtains it comes before any step that argues about the number. Among judgments,
  lead with the one that moves the mark most, or that the others are downstream of.
- `covers` lists the rule_ids this step actually settles — always including the one you chose. Include another
  finding only when acting on your step genuinely resolves it too (the same underlying fact, or a mark that
  supersedes it). When in doubt, list only your own. Do not sweep findings up to make the position look clean.
- Reason from fair-value principles (ASC 820: the price an orderly market participant would pay at the
  measurement date; observable inputs over unobservable; a quoted price for a listed security is Level 1),
  from the fund's stated policy defaults, and from conservatism where the evidence is thin.
- Be specific to the brief: cite the figures and facts given. Do not invent facts.
- Keep the wording plain. No hedging filler.

Reply with ONE JSON object and nothing else:
{"rule_id": "<the finding to lead with>",
 "choice": "<a candidate key on that finding>",
 "label": "<one sentence, imperative, at most 140 characters, ending with a period>",
 "reasons": ["<short line, at most 140 characters>", "<short line, at most 140 characters>"],
 "covers": ["<rule_id>", ...],
 "rationale": "<at most 70 words: why this finding first, and how it stands against the others>",
 "confidence": <number between 0 and 1>}"""

_CANDIDATE_LIMIT = 3


# ---------------------------------------------------------------- the case brief

def _round(x: Any, n: int = 4) -> Any:
    return round(float(x), n) if isinstance(x, (int, float)) and not isinstance(x, bool) else x


def build_brief(c: CompanyResult, f: Flag, run: ValuationRun, signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the chooser may reason from, and nothing it could mistake for an instruction."""
    sig = (signals or {}).get("companies", {}).get(c.company) or {}
    news = [{"date": (n.get("published_at") or "")[:10], "source": n.get("source"), "sentiment": n.get("sentiment"),
             "title": n.get("title")} for n in (sig.get("news") or [])][:6]
    metrics = sig.get("metrics") or {}
    gaps = [{"metric": r["label"], "vendor": r["vendor"], "workbook": r["workbook"], "delta_pct": r["delta_pct"]}
            for r in metrics.get("rows", []) if r.get("material")]
    return {
        "quarter": run.manifest.quarter_label,
        "measurement_date": run.manifest.measurement_date.isoformat(),
        "company": {
            "name": c.company, "fund": c.fund, "sector": c.sector, "stage": c.stage,
            "status": f"{c.status_before.value} -> {c.status_after.value}", "fv_level": c.fv_level, "listed": c.listed,
            "prior_mark_musd": _round(c.prior_mark), "proposed_mark_musd": _round(c.proposed_mark),
            "equity_mark_musd": _round(c.equity_mark), "note_at_cost_musd": _round(c.note_at_cost),
            "ownership_before": _round(c.ownership_before), "ownership_after": _round(c.ownership_after),
            "invested_musd": _round(c.invested_after), "realized_cumulative_musd": _round(c.realized_cumulative),
            "latest_post_money_musd": _round(c.latest_post_money), "staleness_anchor": c.staleness_anchor.isoformat(),
            "arr_musd": _round(c.arr), "arr_growth_yoy": _round(c.arr_growth), "runway_months_aged": _round(c.runway_months_aged),
            "implied_multiple": _round(c.implied_multiple), "moic_after": _round(c.moic_after),
            "alternative_marks_musd": {k: _round(v) for k, v in c.alternative_marks.items()},
        },
        "flag": {
            "rule_id": f.rule_id, "family": f.family, "severity": f.severity.value, "action": f.action,
            "points": [p.replace("**", "") for p in f.points], "message": f.message,
            "evidence": {k: _round(v) for k, v in f.evidence.items() if not isinstance(v, (dict, list))},
        },
        "other_flags": [{"rule_id": g.rule_id, "severity": g.severity.value, "action": g.action or None} for g in c.flags if g is not f],
        "steps": [{"rule": s.rule_id, "from": _round(s.prior_value), "to": _round(s.new_value), "rationale": s.rationale} for s in c.steps][-4:],
        "vendor_signals": {"news": news, "material_metric_gaps": gaps} if (news or gaps) else None,
        "candidates": [{"key": s.key, "label": s.label, "reasons": list(s.reasons), "booked_musd": _round(s.booked)}
                       for s in f.suggestions[:_CANDIDATE_LIMIT]],
        "policy_default_key": f.suggestions[0].key if f.suggestions else None,
    }


def missing_input(c: CompanyResult, f: Flag) -> bool:
    """Does this finding say an input the mark needs is not on file? Either it is one of the
    rules that always means that, or the mark itself is a stand-in and this is the finding the
    engine hung that on. Until it is supplied there is no supported number to argue about."""
    if f.rule_id in MISSING_INPUT_RULES:
        return True
    return bool(c.provisional and f.family == "treatment")


def actionable(c: CompanyResult) -> list[Flag]:
    """The findings a person must resolve, in the order the card meets them: a missing input
    first (there is no supported mark until it is supplied), then BLOCK before REVIEW, then as
    the engine raised them. MONITOR findings and findings with no priced option are not steps."""
    rank = {}
    for i, f in enumerate(c.flags):
        if f.severity is Severity.MONITOR or not f.suggestions:
            continue
        rank[f.rule_id] = (0 if missing_input(c, f) else 1 if f.severity is Severity.BLOCK else 2, i)
    return sorted((f for f in c.flags if f.rule_id in rank), key=lambda f: rank[f.rule_id])


def build_position_brief(c: CompanyResult, run: ValuationRun, signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every open finding on one position, with its priced candidates — the whole question the
    reviewer faces, so the chooser can weigh the findings against each other rather than
    answering each in isolation."""
    acts = actionable(c)
    lead = acts[0] if acts else None
    brief = build_brief(c, lead, run, signals) if lead is not None else {}
    brief.pop("flag", None)
    brief.pop("other_flags", None)
    brief.pop("candidates", None)
    brief.pop("policy_default_key", None)
    brief["findings"] = [{
        "rule_id": f.rule_id, "family": f.family, "severity": f.severity.value, "action": f.action,
        "blocks_for_a_missing_input": missing_input(c, f),
        "points": [p.replace("**", "") for p in f.points], "message": f.message,
        "evidence": {k: _round(v) for k, v in f.evidence.items() if not isinstance(v, (dict, list))},
        "candidates": [{"key": s.key, "label": s.label, "reasons": list(s.reasons), "booked_musd": _round(s.booked)}
                       for s in f.suggestions[:_CANDIDATE_LIMIT]],
    } for f in acts]
    brief["mark_is_a_stand_in"] = ({"reason": c.provisional_reason} if c.provisional else None)
    brief["noted_only"] = [{"rule_id": g.rule_id, "message": g.message}
                           for g in c.flags if g.severity is Severity.MONITOR][:6]
    brief["policy_default"] = {"rule_id": lead.rule_id, "choice": lead.suggestions[0].key} if lead else None
    return brief


def brief_hash(brief: dict[str, Any], prompt_sha: str, model: str) -> str:
    payload = json.dumps(brief, sort_keys=True, default=str) + "|" + prompt_sha + "|" + model
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


# ---------------------------------------------------------------- choosers

class Chooser(Protocol):
    name: str

    def choose(self, brief: dict[str, Any], f: Flag) -> Recommendation: ...

    def choose_position(self, brief: dict[str, Any], c: CompanyResult) -> PositionRecommendation | None: ...


@dataclass
class PolicyChooser:
    """The rule's own default, worded as the rule wrote it."""
    name: str = "policy"

    def choose(self, brief: dict[str, Any], f: Flag, note: str | None = None) -> Recommendation:
        s = f.suggestions[0]
        return Recommendation(key=s.key, label=s.label, reasons=s.reasons, booked=s.booked, source="policy", note=note)

    def choose_position(self, brief: dict[str, Any], c: CompanyResult, note: str | None = None) -> PositionRecommendation | None:
        """Without a model there is no cross-finding judgment to make: lead with the first
        finding in the card's own order, and claim to settle only that one."""
        acts = actionable(c)
        if not acts:
            return None
        f = acts[0]
        s = f.suggestions[0]
        return PositionRecommendation(rule_id=f.rule_id, key=s.key, label=s.label, reasons=s.reasons,
                                      booked=s.booked, covers=(f.rule_id,), source="policy", note=note)


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


_WITHHELD = "A sentence naming a figure the engine did not compute was withheld; see the priced options."


def _allowed_figures(flags: list[Flag], c: CompanyResult | None = None) -> set[float]:
    """Every number the model was legitimately shown: the candidates' priced values, the figures in
    each finding's evidence, and the position's own marks. Anything else in its prose is invented."""
    out: set[float] = set()
    for f in flags:
        out |= {float(s_.booked) for s_ in f.suggestions}
        out |= _figures(json.dumps(f.evidence, default=str))
        out |= _figures(f.message)
    if c is not None:
        out |= {float(c.prior_mark), float(c.proposed_mark), float(c.booked_mark), float(c.equity_mark),
                float(c.note_at_cost), float(c.invested_after), float(c.realized_quarter)}
    return {round(x, 6) for x in out} | {round(x * 1e6, 6) for x in out} | {round(x / 1e6, 6) for x in out}


def _fit_card(data: dict[str, Any], allowed: set[float] | None = None, chosen: Suggestion | None = None) -> tuple[str, list[str]]:
    """The card shows one sentence and two short reasons. A model that writes long is clipped at a
    word, not rejected: the choice (validated separately against the candidates) is the substance,
    the wording is presentation. Empty is still a rejection. A sentence that brings its own figure —
    "book this at $88M" — is withheld, as the note reader withholds it: the number a reviewer books
    comes from the priced candidate, and the prose beside it must not quote one the engine never
    produced. This was the one AI layer without that fence. What a reviewer then reads is the
    candidate's own wording — the rule's sentence for the option chosen — never a placeholder."""
    label = _clip(data.get("label", ""), 140)
    raw = data.get("reasons") or []
    if isinstance(raw, str):
        raw = [raw]
    reasons = [_clip(r, 140) for r in raw if str(r).strip()][:2]
    if allowed is not None:
        if label and not figures_carried(label, allowed):
            label = _clip(chosen.label, 140) if chosen is not None else _WITHHELD
        kept = [r for r in reasons if figures_carried(r, allowed)]
        if reasons and not kept and chosen is not None:   # every reason was withheld: the rule's own stand in
            kept = [_clip(r, 140) for r in chosen.reasons[:2]]
        reasons = kept
    if not label or not reasons:
        raise ValueError("label/reasons are empty")
    if len(reasons) == 1:
        reasons.append(_clip(chosen.reasons[0], 140) if chosen is not None and chosen.reasons and chosen.reasons[0] != reasons[0]
                       else "See the finding's evidence.")
    if not label.endswith((".", "…")):
        label += "."
    return label, reasons


class ClaudeChooser:
    """Ask the model to choose among the engine's candidates; cache; validate; fall back."""
    name = "claude"

    def __init__(self, cache_dir: Path, model: str = DEFAULT_MODEL, *, api_key: str | None = None,
                 use_cache: bool = True, refresh: bool = False, timeout_s: float = 30.0, max_tokens: int = 600) -> None:
        self.cache_dir = Path(cache_dir)
        self.model = model
        self.api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        self.use_cache = use_cache
        self.refresh = refresh
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.prompt_sha = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
        self.position_prompt_sha = hashlib.sha256(POSITION_PROMPT.encode()).hexdigest()
        self.policy = PolicyChooser()
        self.calls = 0
        self.cache_hits = 0
        self.fallbacks: list[str] = []
        # `recommend_run` chooses for six companies at once; `+=` on an attribute is not atomic,
        # so the call and cache-hit counts are taken under a lock.
        self._lock = threading.Lock()

    def _tally(self, **deltas: int) -> None:
        with self._lock:
            for name, n in deltas.items():
                setattr(self, name, getattr(self, name) + n)

    @property
    def unavailable_reason(self) -> str | None:
        if not self.api_key:
            return "Claude is not connected on this machine"
        if importlib.util.find_spec("anthropic") is None:
            return "the anthropic package is not installed for this Python"
        return None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    # -- cache
    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read(self, key: str) -> dict[str, Any] | None:
        p = self._path(key)
        if not self.use_cache or self.refresh or not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001 — a corrupt cache entry is a miss, not a crash
            return None

    def _write(self, key: str, brief: dict[str, Any], answer: dict[str, Any]) -> None:
        if not self.use_cache:
            return
        record = {"key": key, "model": self.model, "prompt_sha256": self.prompt_sha,
                  "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                  "company": brief["company"]["name"],
                  "rule_id": (brief.get("flag") or {}).get("rule_id", "position"),
                  "candidates": [x["key"] for x in brief.get("candidates", [])]
                                or [f"{f['rule_id']}/{x['key']}" for f in brief.get("findings", []) for x in f["candidates"]],
                  "answer": answer}
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._path(key).write_text(json.dumps(record, indent=2, sort_keys=True))
        except OSError as ex:
            # A validated answer is already in hand; a cache that cannot be written costs one repeat
            # call next run, never the run (the write used to sit outside the never-raises contract).
            log.warning("could not cache the recommendation for %s (%s)", brief["company"]["name"], ex)

    # -- the call
    def _call(self, brief: dict[str, Any], system: str | None = None) -> str:
        import anthropic  # optional dependency: the `claude` extra
        client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout_s)
        msg = client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system or SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "CASE BRIEF (JSON):\n" + json.dumps(brief, default=str)}],
        )
        self._tally(calls=1)
        return "".join(getattr(block, "text", "") for block in msg.content)

    @staticmethod
    def parse(text: str, f: Flag) -> dict[str, Any]:
        """Strict: one JSON object, the choice must be a candidate key, the wording must fit."""
        body = text.strip()
        if body.startswith("```"):
            body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body, flags=re.S)
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("reply is not a JSON object")
        expected = {"choice", "label", "reasons", "rationale", "confidence"}
        if set(data) != expected:
            raise ValueError(f"reply keys {sorted(data)} != {sorted(expected)}")
        keys = {s.key for s in f.suggestions}
        if data["choice"] not in keys:
            raise ValueError(f"choice {data['choice']!r} is not a candidate ({sorted(keys)})")
        chosen = next(s for s in f.suggestions if s.key == data["choice"])
        label, reasons = _fit_card(data, _allowed_figures([f]), chosen)
        conf = float(data["confidence"])
        if not 0.0 <= conf <= 1.0:
            raise ValueError("confidence outside [0, 1]")
        return {"choice": data["choice"], "label": label, "reasons": reasons,
                "rationale": str(data["rationale"]).strip()[:600], "confidence": round(conf, 3)}

    @staticmethod
    def parse_position(text: str, c: CompanyResult) -> dict[str, Any]:
        """Strict: one JSON object; the finding must be one of this position's actionable
        findings; the choice must be one of THAT finding's candidate keys; `covers` must be a
        subset of the actionable findings and must include the one chosen."""
        body = text.strip()
        if body.startswith("```"):
            body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body, flags=re.S)
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("reply is not a JSON object")
        expected = {"rule_id", "choice", "label", "reasons", "covers", "rationale", "confidence"}
        if set(data) != expected:
            raise ValueError(f"reply keys {sorted(data)} != {sorted(expected)}")
        by_id = {f.rule_id: f for f in actionable(c)}
        rid = str(data["rule_id"])
        if rid not in by_id:
            raise ValueError(f"rule_id {rid!r} is not an actionable finding ({sorted(by_id)})")
        keys = {s.key for s in by_id[rid].suggestions}
        if data["choice"] not in keys:
            raise ValueError(f"choice {data['choice']!r} is not a candidate on {rid} ({sorted(keys)})")
        covers = [str(x) for x in data["covers"]]
        unknown = sorted(set(covers) - set(by_id))
        if unknown:
            raise ValueError(f"covers names {unknown}, which are not actionable findings on this position")
        if rid not in covers:
            covers = [rid] + covers
        chosen = next(s for s in by_id[rid].suggestions if s.key == data["choice"])
        label, reasons = _fit_card(data, _allowed_figures(list(by_id.values()), c), chosen)
        conf = float(data["confidence"])
        if not 0.0 <= conf <= 1.0:
            raise ValueError("confidence outside [0, 1]")
        return {"rule_id": rid, "choice": data["choice"], "label": label, "reasons": reasons,
                "covers": list(dict.fromkeys(covers)), "rationale": str(data["rationale"]).strip()[:700],
                "confidence": round(conf, 3)}

    def _to_position(self, answer: dict[str, Any], c: CompanyResult) -> PositionRecommendation:
        f = next(x for x in actionable(c) if x.rule_id == answer["rule_id"])
        chosen = next(s for s in f.suggestions if s.key == answer["choice"])
        return PositionRecommendation(rule_id=f.rule_id, key=chosen.key, label=answer["label"],
                                      reasons=tuple(answer["reasons"]), booked=chosen.booked,
                                      covers=tuple(answer["covers"]), source="claude", model=self.model,
                                      rationale=answer["rationale"], confidence=answer["confidence"])

    def choose_position(self, brief: dict[str, Any], c: CompanyResult) -> PositionRecommendation | None:
        if not actionable(c):
            return None
        key = brief_hash(brief, self.position_prompt_sha, self.model)
        cached = self._read(key)
        if cached is not None:
            try:
                answer = self.parse_position(json.dumps(cached["answer"]), c)
                self._tally(cache_hits=1)
                return self._to_position(answer, c)
            except Exception as ex:  # noqa: BLE001
                log.warning("position recommendation cache %s no longer fits %s (%s); refetching", key, c.company, ex)
        if not self.available:
            why = f"{(self.unavailable_reason or 'Claude is not connected on this machine')[0].upper()}{(self.unavailable_reason or 'Claude is not connected on this machine')[1:]}, so this is the rule's own default rather than a choice made for this company's facts."
            self.fallbacks.append(f"{c.company} (position): {why}")
            return self.policy.choose_position(brief, c, note=why)
        try:
            answer = self.parse_position(self._call(brief, POSITION_PROMPT), c)
        except Exception as ex:  # noqa: BLE001 — by contract this never raises into the run
            why = (f"Claude could not be used for this step ({type(ex).__name__}: {str(ex)[:120]}), so this is the rule's own "
                   "default rather than a choice made for this company's facts.")
            log.warning("%s (position): %s", c.company, why)
            self.fallbacks.append(f"{c.company} (position): {why}")
            return self.policy.choose_position(brief, c, note=why)
        self._write(key, brief, answer)
        return self._to_position(answer, c)

    def _to_recommendation(self, answer: dict[str, Any], f: Flag) -> Recommendation:
        chosen = next(s for s in f.suggestions if s.key == answer["choice"])
        return Recommendation(key=chosen.key, label=answer["label"], reasons=tuple(answer["reasons"]),
                              booked=chosen.booked, source="claude", model=self.model,
                              rationale=answer["rationale"], confidence=answer["confidence"])

    def choose(self, brief: dict[str, Any], f: Flag) -> Recommendation:
        key = brief_hash(brief, self.prompt_sha, self.model)
        cached = self._read(key)
        if cached is not None:
            try:
                answer = self.parse(json.dumps(cached["answer"]), f)   # re-validated against today's candidates
                self._tally(cache_hits=1)
                return self._to_recommendation(answer, f)
            except Exception as ex:  # noqa: BLE001
                log.warning("recommendation cache %s no longer fits the flag (%s); refetching", key, ex)
        if not self.available:
            why = f"{(self.unavailable_reason or 'Claude is not connected on this machine')[0].upper()}{(self.unavailable_reason or 'Claude is not connected on this machine')[1:]}, so this is the rule's own default rather than a choice made for this company's facts."
            self.fallbacks.append(f"{brief['company']['name']} {f.rule_id}: {why}")
            return self.policy.choose(brief, f, note=why)
        try:
            answer = self.parse(self._call(brief), f)
        except Exception as ex:  # noqa: BLE001 — by contract this never raises into the run
            why = (f"Claude could not be used for this step ({type(ex).__name__}: {str(ex)[:120]}), so this is the rule's own "
                   "default rather than a choice made for this company's facts.")
            log.warning("%s %s: %s", brief["company"]["name"], f.rule_id, why)
            self.fallbacks.append(f"{brief['company']['name']} {f.rule_id}: {why}")
            return self.policy.choose(brief, f, note=why)
        self._write(key, brief, answer)
        return self._to_recommendation(answer, f)


# ---------------------------------------------------------------- applying to a run

def make_chooser(cfg: RuleConfig, root: Path, provider: str | None = None, *, refresh: bool = False) -> Chooser:
    """Flag > HC_RECOMMENDER > policy. The environment variable lets the test suite and the golden
    fixture pin the policy default, so a cached model answer under data/recommendations/ can never
    leak into a run that must be a pure function of workbook, policy and engine."""
    name = (provider or os.environ.get("HC_RECOMMENDER") or cfg.recommendation.provider).strip().lower()
    if name == "claude":
        return ClaudeChooser(Path(root) / CACHE_DIR, model=cfg.recommendation.model,
                             use_cache=cfg.recommendation.cache, refresh=refresh)
    if name != "policy":
        log.warning("unknown recommender %r; using policy", name)
    return PolicyChooser()


def recommender_label(chooser: Chooser) -> str:
    """What actually chose, not what was asked for. A ClaudeChooser that could not connect falls
    back to the policy default on every card and says so there — so labelling the whole run
    `claude:<model>` told the dashboard footer to claim a model chose when none was reached."""
    if isinstance(chooser, ClaudeChooser):
        if getattr(chooser, "available", True):
            return f"claude:{chooser.model}"
        why = getattr(chooser, "unavailable_reason", None) or "not connected"
        return f"policy (Claude unavailable: {why})"
    return "policy"


def recommend_run(run: ValuationRun, chooser: Chooser, signals: dict[str, Any] | None = None) -> ValuationRun:
    """The run with one `recommendation` on every flag that carries suggestions, and one
    `recommendation` on every position with something actionable — the single next step,
    chosen across its findings. Marks, flags, dispositions, readiness and totals are
    untouched: only the two recommendation fields are filled in."""
    policy = PolicyChooser()

    def one(c: CompanyResult) -> CompanyResult:
        # A position with a decision on record is not waiting for a suggestion: the rule's own
        # default fills the fields and no model is asked. Recording a decision re-runs the book,
        # and the seconds a fresh model call costs were the whole of that wait.
        ch = policy if c.override is not None else chooser
        flags: list[Flag] = []
        changed = False
        for f in c.flags:
            if f.severity is Severity.MONITOR or not f.suggestions:
                flags.append(f)
                continue
            rec = ch.choose(build_brief(c, f, run, signals), f)
            flags.append(f.model_copy(update={"recommendation": rec}))
            changed = True
        c2 = c.model_copy(update={"flags": tuple(flags)}) if changed else c
        step = ch.choose_position(build_position_brief(c2, run, signals), c2)
        return c2.model_copy(update={"recommendation": step}) if step is not None else c2

    # Positions are independent, and a model call takes seconds: run them side by side. The policy
    # chooser is instant and stays sequential; the result order is the run's order either way.
    workers = 6 if isinstance(chooser, ClaudeChooser) and chooser.available else 1
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            companies = list(pool.map(one, run.companies))
    else:
        companies = [one(c) for c in run.companies]
    manifest = run.manifest.model_copy(update={"recommender": recommender_label(chooser)})
    return run.model_copy(update={"companies": tuple(companies), "manifest": manifest})
