"""HTTP surface over the pipeline. Thin on purpose: every number comes out of
`pipeline.execute`; the API only serialises, records decisions to the ledgers on disk,
and reruns.

The run is computed once when the app is created and held in `app.state.result`;
`POST /api/rerun` (and any endpoint that writes a ledger) recomputes it.
"""
from __future__ import annotations

import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..engine.run import build_registry
from ..export.exec_report import EXEC_STATIC_DIR, render_exec_report
from ..export.static_report import render_report
from ..pipeline import PipelineResult, RunPaths, execute
from .history import build_history
from .publish import exec_payload, list_published, publish_run
from .signals import build_signals
from .sources import build_sources

STATIC_DIR = Path(__file__).resolve().parent / "static"


class OverrideIn(BaseModel):
    company: str
    booked: float
    reason: str = Field(min_length=1)
    approver: str = Field(min_length=1)
    rule_ids_addressed: list[str] = Field(default_factory=list)
    source_suggestion: str | None = None   # "<rule_id>/<key>" when the reviewer accepted an engine suggestion


class PublishIn(BaseModel):
    approver: str = Field(min_length=1)
    note: str = ""


class DecisionIn(BaseModel):
    decision: str            # accept_once | promote | reject (the adjudication module validates)
    approver: str = Field(min_length=1)
    reason: str = ""
    booked: float | None = None
    effective_from: date | None = None


def _json(model: Any) -> Response:
    """Serialise via pydantic so dates, enums and tuples come out exactly as in run.json."""
    return Response(content=model.model_dump_json(), media_type="application/json")


def append_override(path: Path, record: dict[str, Any]) -> None:
    """Append one committee decision to the YAML ledger, creating the file if needed."""
    raw: dict[str, Any] = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text()) or {}
    records = list(raw.get("overrides") or [])
    records.append(record)
    raw["overrides"] = records
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))


def watched_inputs(paths: RunPaths) -> list[Path]:
    """The files whose change means "the answer may have changed": the workbook, the policy
    (and anything it inherits from, approximated by its folder), the decision ledgers, the
    prior quarter's sidecar. Not the market cache — a refetch is an explicit `--refresh-market`."""
    out = [paths.workbook, paths.policy, paths.overrides, paths.precedent, paths.open_items_carry]
    out += sorted(Path(paths.policy).parent.glob("*.yaml"))
    out += sorted(Path(paths.proposals_dir).glob("*.json")) if Path(paths.proposals_dir).exists() else []
    return out


def _stamp(files: list[Path]) -> tuple[tuple[str, float], ...]:
    return tuple((str(p), p.stat().st_mtime) for p in files if p.exists())


def watch_inputs(app: FastAPI, interval_s: float = 2.0, log: Any = None) -> threading.Thread:
    """Recompute the run whenever a watched input changes — the self-refreshing page.

    Polls mtimes (portable, no extra dependency) every `interval_s`; a change triggers one
    recompute under the app lock, and the served run id changes, which the dashboard notices
    and reloads on. A failed recompute (a half-written workbook, say) is logged and the last
    good run stays served; the next change retries."""
    paths: RunPaths = app.state.paths

    def loop() -> None:
        last = _stamp(watched_inputs(paths))
        while True:
            time.sleep(interval_s)
            now = _stamp(watched_inputs(paths))
            if now == last:
                continue
            last = now
            time.sleep(0.5)   # let a save finish
            try:
                r = app.state.recompute()
                if log:
                    log(f"inputs changed; recomputed run {r.run.manifest.run_id} "
                        f"(booked NAV {r.run.totals.booked_nav:,.1f})")
            except Exception as exc:  # noqa: BLE001 — keep serving the last good run
                if log:
                    log(f"inputs changed but the rerun failed: {exc}; still serving the previous run")

    t = threading.Thread(target=loop, name="hc-watch", daemon=True)
    t.start()
    return t


def rule_catalogue(result: PipelineResult) -> list[dict[str, Any]]:
    return [
        {
            "id": m.rule_id, "version": m.version, "applies_to": list(m.applies_to),
            "severity": m.severity.value if m.severity else None, "effective_from": m.effective_from.isoformat(),
            "description": m.description, "source": m.source, "terminal": m.terminal, "tier": m.tier,
        }
        for m in build_registry(result.config).all()
    ]


def create_app(paths: RunPaths | None = None, provider: str | None = None, static_dir: Path | None = None,
               refresh_market: bool = False) -> FastAPI:
    paths = paths or RunPaths.default()
    static_dir = Path(static_dir) if static_dir is not None else STATIC_DIR
    app = FastAPI(title="HC valuation engine", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"], allow_headers=["*"],
    )
    lock = threading.Lock()

    def recompute(refresh: bool = False) -> PipelineResult:
        with lock:
            app.state.result = execute(paths, provider=provider, refresh_market=refresh)
        return app.state.result

    app.state.paths = paths
    app.state.provider = provider
    app.state.static_dir = static_dir
    app.state.recompute = recompute     # `hc-valuation run --watch` calls this when an input file changes
    recompute(refresh=refresh_market)   # a forced refetch applies to the first run only; reruns read the cache

    def result() -> PipelineResult:
        return app.state.result

    # ------------------------------------------------------------------ read

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        m = result().run.manifest
        return {"status": "ok", "run_id": m.run_id, "quarter": m.quarter_label, "policy_version": m.policy_version,
                "engine_version": m.engine_version, "generated_at": m.generated_at.isoformat(),
                "blocked": result().run.blocked}

    @app.get("/api/run")
    def get_run() -> Response:
        return _json(result().run)

    @app.get("/api/companies/{name}")
    def get_company(name: str) -> Response:
        c = result().run.by_company().get(name)
        if c is None:
            raise HTTPException(404, f"no company named {name!r} in this run")
        return _json(c)

    @app.get("/api/sources")
    def get_sources() -> JSONResponse:
        """Workbook, sheet and column letters, so the UI can cite the exact cell behind a number."""
        return JSONResponse(build_sources(result()))

    @app.get("/api/rules")
    def get_rules() -> list[dict[str, Any]]:
        return rule_catalogue(result())

    @app.get("/api/market")
    def get_market() -> JSONResponse:
        """The sector comps behind X-401/X-402 and M-080, with where they came from (docs/market-feed.md §3)."""
        return JSONResponse(result().market_report)

    @app.get("/api/history")
    def get_history() -> JSONResponse:
        """Quarter-over-quarter booked marks per company: backfill + publish ledger + this run (api/history.py)."""
        return JSONResponse(build_history(result().run, paths.root))

    @app.get("/api/signals")
    def get_signals() -> JSONResponse:
        """Vendor context beside each position — Foresight-shaped metrics cross-checked against the
        workbook and AlphaSense-shaped dated signals (api/signals.py). Never an input to a mark."""
        return JSONResponse(build_signals(result()))

    @app.get("/api/proposals")
    def get_proposals() -> JSONResponse:
        out = []
        for p in result().proposals:
            out.append(p.model_dump(mode="json") if hasattr(p, "model_dump") else p)
        return JSONResponse(out)

    @app.get("/api/published")
    def get_published_list() -> JSONResponse:
        """Every quarter that has been released to executives, newest first."""
        return JSONResponse(list_published(paths.root))

    @app.get("/api/exec")
    def get_exec_latest() -> JSONResponse:
        """The executive view-model for the most recently published quarter."""
        view = exec_payload(paths.root)
        if view is None:
            raise HTTPException(404, "nothing has been published yet — release a run from the review dashboard first")
        return JSONResponse(view)

    @app.get("/api/exec/{slug}")
    def get_exec_quarter(slug: str) -> JSONResponse:
        view = exec_payload(paths.root, slug)
        if view is None:
            raise HTTPException(404, f"no published snapshot named {slug!r}")
        return JSONResponse(view)

    # ------------------------------------------------------------------ write

    @app.post("/api/publish")
    def post_publish(body: PublishIn) -> JSONResponse:
        """Release the current run to the executive dashboard under a named approver."""
        try:
            rec = publish_run(result().run, paths.root, approver=body.approver, note=body.note)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(rec)

    @app.post("/api/rerun")
    def rerun() -> dict[str, Any]:
        r = recompute()
        return {"run_id": r.run.manifest.run_id, "generated_at": r.run.manifest.generated_at.isoformat(),
                "booked_nav": r.run.totals.booked_nav}

    @app.post("/api/overrides")
    def post_override(body: OverrideIn) -> Response:
        r = result()
        c = r.run.by_company().get(body.company)
        if c is None:
            raise HTTPException(404, f"no company named {body.company!r} in this run")
        append_override(paths.overrides, {
            "company": body.company, "quarter": r.config.quarter.label,
            "proposed": float(c.proposed_mark), "booked": float(body.booked),
            "reason": body.reason, "approver": body.approver,
            "created_at": date.today().isoformat(),
            "rule_ids_addressed": body.rule_ids_addressed or [f.rule_id for f in c.flags],
            **({"source_suggestion": body.source_suggestion} if body.source_suggestion else {}),
        })
        r2 = recompute()
        return _json(r2.run.by_company()[body.company])

    @app.post("/api/proposals/{proposal_id}/decision")
    def post_decision(proposal_id: str, body: DecisionIn) -> Response:
        try:
            from ..adjudication import promote  # lazy: the adjudication package is an optional work package
        except ImportError:
            raise HTTPException(501, "adjudication.promote is not available in this build; proposals can be read "
                                     "but decisions cannot be recorded") from None
        record = getattr(promote, "record_decision", None)
        if record is None:
            raise HTTPException(501, "adjudication.promote exists but has no record_decision(); decisions cannot be recorded")
        try:
            outcome = record(paths, proposal_id, body.decision, body.approver, body.reason,
                             booked=body.booked, effective_from=body.effective_from)
        except (FileNotFoundError, KeyError) as exc:
            raise HTTPException(404, f"proposal {proposal_id!r}: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        r2 = recompute()
        payload = {"proposal_id": proposal_id, "decision": body.decision, "run_id": r2.run.manifest.run_id,
                   "outcome": outcome.model_dump(mode="json") if hasattr(outcome, "model_dump") else outcome}
        return JSONResponse(payload)

    # ------------------------------------------------------------------ frontend

    # The executive site is a separate bundle at /exec/. It reads only published snapshots.
    exec_dir = getattr(app.state, "exec_static_dir", None) or EXEC_STATIC_DIR
    if (Path(exec_dir) / "index.html").is_file():
        app.mount("/exec", StaticFiles(directory=str(exec_dir), html=True), name="exec")
    else:
        @app.get("/exec", include_in_schema=False)
        @app.get("/exec/", include_in_schema=False)
        def exec_index() -> HTMLResponse:
            view = exec_payload(paths.root)
            if view is None:
                return HTMLResponse("<h1>Nothing published yet</h1><p>Release a run from the review dashboard first.</p>", 404)
            return HTMLResponse(render_exec_report(view, Path(exec_dir)))

    if (static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        @app.get("/", include_in_schema=False)
        def index() -> HTMLResponse:
            return HTMLResponse(render_report(result().run, None, market=result().market_report,
                                              history=build_history(result().run, paths.root),
                                              signals=build_signals(result())))

    return app
