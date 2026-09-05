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
  is taken from that candidate, never from the reply. Every answer is cached under
  `data/recommendations/<sha>.json`, keyed by a hash of the case brief, the prompt and the
  model, so a rerun is deterministic and needs no network; a miss without an API key falls
  back to `policy` and the recommendation says so.

Either way the reviewer still confirms under a named approver, the other candidates stay
one click away, and accepting a recommendation records an ordinary E-01 override. This runs
in the pipeline after the engine, like adjudication: the engine never holds a client.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import RuleConfig
from .engine.models import CompanyResult, Flag, Recommendation, Severity, ValuationRun

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


def brief_hash(brief: dict[str, Any], prompt_sha: str, model: str) -> str:
    payload = json.dumps(brief, sort_keys=True, default=str) + "|" + prompt_sha + "|" + model
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


# ---------------------------------------------------------------- choosers

class Chooser(Protocol):
    name: str

    def choose(self, brief: dict[str, Any], f: Flag) -> Recommendation: ...


@dataclass
class PolicyChooser:
    """The rule's own default, worded as the rule wrote it."""
    name: str = "policy"

    def choose(self, brief: dict[str, Any], f: Flag, note: str | None = None) -> Recommendation:
        s = f.suggestions[0]
        return Recommendation(key=s.key, label=s.label, reasons=s.reasons, booked=s.booked, source="policy", note=note)


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
        self.policy = PolicyChooser()
        self.calls = 0
        self.cache_hits = 0
        self.fallbacks: list[str] = []

    @property
    def available(self) -> bool:
        return bool(self.api_key)

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
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        record = {"key": key, "model": self.model, "prompt_sha256": self.prompt_sha,
                  "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                  "company": brief["company"]["name"], "rule_id": brief["flag"]["rule_id"],
                  "candidates": [c["key"] for c in brief["candidates"]], "answer": answer}
        self._path(key).write_text(json.dumps(record, indent=2, sort_keys=True))

    # -- the call
    def _call(self, brief: dict[str, Any]) -> str:
        import anthropic  # optional dependency: the `adjudication` extra
        client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout_s)
        msg = client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "CASE BRIEF (JSON):\n" + json.dumps(brief, default=str)}],
        )
        self.calls += 1
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
        label = str(data["label"]).strip()
        reasons = [str(r).strip() for r in data["reasons"]]
        if not label or len(label) > 140 or len(reasons) != 2 or not all(0 < len(r) <= 140 for r in reasons):
            raise ValueError("label/reasons do not fit the card")
        if not label.endswith("."):
            label += "."
        conf = float(data["confidence"])
        if not 0.0 <= conf <= 1.0:
            raise ValueError("confidence outside [0, 1]")
        return {"choice": data["choice"], "label": label, "reasons": reasons,
                "rationale": str(data["rationale"]).strip()[:600], "confidence": round(conf, 3)}

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
                self.cache_hits += 1
                return self._to_recommendation(answer, f)
            except Exception as ex:  # noqa: BLE001
                log.warning("recommendation cache %s no longer fits the flag (%s); refetching", key, ex)
        if not self.available:
            why = "ANTHROPIC_API_KEY not set and no cached answer; showing the policy default"
            self.fallbacks.append(f"{brief['company']['name']} {f.rule_id}: {why}")
            return self.policy.choose(brief, f, note=why)
        try:
            answer = self.parse(self._call(brief), f)
        except Exception as ex:  # noqa: BLE001 — by contract this never raises into the run
            why = f"claude unavailable ({type(ex).__name__}: {str(ex)[:120]}); showing the policy default"
            log.warning("%s %s: %s", brief["company"]["name"], f.rule_id, why)
            self.fallbacks.append(f"{brief['company']['name']} {f.rule_id}: {why}")
            return self.policy.choose(brief, f, note=why)
        self._write(key, brief, answer)
        return self._to_recommendation(answer, f)


# ---------------------------------------------------------------- applying to a run

def make_chooser(cfg: RuleConfig, root: Path, provider: str | None = None, *, refresh: bool = False) -> Chooser:
    name = (provider or cfg.recommendation.provider).strip().lower()
    if name == "claude":
        return ClaudeChooser(Path(root) / CACHE_DIR, model=cfg.recommendation.model,
                             use_cache=cfg.recommendation.cache, refresh=refresh)
    if name != "policy":
        log.warning("unknown recommender %r; using policy", name)
    return PolicyChooser()


def recommender_label(chooser: Chooser) -> str:
    return f"claude:{chooser.model}" if isinstance(chooser, ClaudeChooser) else "policy"


def recommend_run(run: ValuationRun, chooser: Chooser, signals: dict[str, Any] | None = None) -> ValuationRun:
    """The run with one `recommendation` on every flag that carries suggestions. Marks, flags,
    dispositions and totals are untouched — only the recommendation field is filled in."""
    companies: list[CompanyResult] = []
    for c in run.companies:
        flags: list[Flag] = []
        changed = False
        for f in c.flags:
            if f.severity is Severity.MONITOR or not f.suggestions:
                flags.append(f)
                continue
            rec = chooser.choose(build_brief(c, f, run, signals), f)
            flags.append(f.model_copy(update={"recommendation": rec}))
            changed = True
        companies.append(c.model_copy(update={"flags": tuple(flags)}) if changed else c)
    manifest = run.manifest.model_copy(update={"recommender": recommender_label(chooser)})
    return run.model_copy(update={"companies": tuple(companies), "manifest": manifest})
