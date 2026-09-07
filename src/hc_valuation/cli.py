"""`hc-valuation` — the command line.

    run       serve the dashboard (and open a browser)
    build     write the whole deliverable set into a folder, no server needed
    validate  ingest + integrity checks only
    export    workbook + CSVs only
    rules     print the rule catalogue
    market    show the sector comps feed (live EDGAR + Yahoo/Stooq closes, or the fixture) and where it came from
    history   the quarter-over-quarter booked-mark archive per company (backfill + publish ledger + this run)
    recommend fill the one recommendation per flag (policy default, or Claude choosing among the engine's options)
    next-policy  write rules/<next quarter>.yaml inheriting from the current policy
    version   engine and policy versions

Plain output, no colour required: this is meant to be read in a terminal log as much as
on a screen.
"""
from __future__ import annotations

import os

import json
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from datetime import date

from .config import default_policy_path, load_config
from .engine.models import Severity, ValuationRun
from .engine.run import ENGINE_VERSION, build_registry


def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version as _v
    try:
        return _v("hc-valuation")
    except PackageNotFoundError:  # running from a checkout without an install
        return "unknown"

DEFAULT_HOST = os.environ.get("HC_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("HC_PORT", "8765"))
DASHBOARD_URL = os.environ.get("HC_DASHBOARD_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")

app = typer.Typer(
    add_completion=False, no_args_is_help=True, rich_markup_mode=None,
    help="HC valuation engine: roll the portfolio forward through the quarter's activity, propose marks, "
         "and flag what a human must review. Start with `hc-valuation run`.",
)

InputOpt = typer.Option(None, "--input", "-i", help="Portfolio workbook (.xlsx). Default: data/HC_Mock_Portfolio_Data.xlsx")
PolicyOpt = typer.Option(None, "--policy", "-p", help="Policy file. Default: the workbook quarter's rules/<YYYY>Q<n>.yaml when it exists, else the base policy")
ProviderOpt = typer.Option(None, "--provider", help="Market-data provider override (stub | live | pitchbook | synthetic), passed to the connectors")
RefreshMarketOpt = typer.Option(False, "--refresh-market", help="Refetch the live market feed over its cache (provider live)")
RecommenderOpt = typer.Option(None, "--recommender", help="Who picks the one resolution shown first per flag: policy | claude "
                                                        "(default: the policy file's recommendation.provider)")
# The decision ledgers. The real book keeps data/; a test chain (a synthetic quarter, a rehearsal)
# gets its own folder so its simulated decisions never land in the committee's overrides.yaml or in
# the publish archive the mark history reads.
OverridesOpt = typer.Option(None, "--overrides", help="Override ledger (E-01 decisions). Default: <ledger dir>/overrides.yaml")
LedgerDirOpt = typer.Option(None, "--ledger-dir", help="Folder for every decision record — overrides.yaml, proposals/, "
                                                      "precedent.yaml, published/. Default: data/")


def _load_rationale(root: Path):
    from .rationale import load_rationale
    return load_rationale(root)


def _paths(input_path: Optional[Path], policy: Optional[Path], overrides: Optional[Path] = None,
           ledger_dir: Optional[Path] = None):
    from .pipeline import RunPaths
    return RunPaths.default(workbook=input_path.resolve() if input_path else None,
                            policy=policy.resolve() if policy else None,
                            overrides=overrides.resolve() if overrides else None,
                            ledger_dir=ledger_dir.resolve() if ledger_dir else None)


def _slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")


def _default_provider(paths, provider: Optional[str]) -> Optional[str]:
    """`run`, `build` and `publish` pick the provider the way the dashboard's workbook switcher
    does (workbooks.provider_for): an explicit `--provider` or `HC_MARKET_PROVIDER` wins; else the
    declared-synthetic file for the measurement date, if one exists; else the committed live cache
    (`data/market_cache/<measurement date>/`, no network); else the fixture. The library default
    (`execute` with no provider, the tests, the golden run) stays `stub`."""
    from .workbooks import is_synthetic, provider_for, quarter_of

    synthetic = is_synthetic(paths.workbook, quarter_of(paths.workbook)[1]) if Path(paths.workbook).is_file() else False
    chosen = provider_for(paths.root, paths.policy, provider, synthetic=synthetic)
    if chosen == "synthetic" and provider is None:
        typer.echo("market: SYNTHETIC test data for this measurement date (data/synthetic_market/); not market data")
    elif chosen == "live" and provider is None:
        md = load_config(paths.policy).quarter.measurement_date
        typer.echo(f"market: reading the live comps cache in data/market_cache/{md.isoformat()} (no network; "
                   f"--provider stub for the fixture, --refresh-market to refetch)")
    return chosen


def _headline(run: ValuationRun) -> str:
    t, m = run.totals, run.manifest
    d = t.dispositions
    lines = [
        f"{m.quarter_label}  policy {m.policy_version}  engine {m.engine_version}  run {m.run_id}",
        f"positions {t.positions} ({t.active_after} active)   prior NAV {t.prior_nav:,.1f}   proposed {t.proposed_nav:,.1f}"
        f"   booked {t.booked_nav:,.1f}   net {t.net_movement:+,.1f}",
        f"realized in quarter {t.realized_quarter:,.1f}   cumulative {t.realized_cumulative:,.1f}   written off {t.written_off:,.1f}   exited {t.exited_at_prior_mark:,.1f}"
        f"   level-1 positions {t.level1_positions}",
        f"dispositions  BLOCK {d.get('BLOCK', 0)} / REVIEW {d.get('REVIEW', 0)} / MONITOR {d.get('MONITOR', 0)} / CLEAR {d.get('CLEAR', 0)}",
    ]
    blocked = [c.company for c in run.companies if c.disposition.value == "BLOCK"]
    if blocked:
        lines.append("blocked: " + ", ".join(blocked))
    if run.validation:
        nb = sum(1 for v in run.validation if v.blocking)
        lines.append(f"validation issues: {len(run.validation)} ({nb} blocking)")
    return "\n".join(lines)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    out = [fmt.format(*headers), fmt.format(*("-" * w for w in widths))]
    out += [fmt.format(*r) for r in rows]
    return "\n".join(out)


# ------------------------------------------------------------------------- commands

@app.command()
def version(policy: Optional[Path] = PolicyOpt) -> None:
    """Print engine, package and policy versions."""
    typer.echo(f"hc-valuation {_package_version()}  engine {ENGINE_VERSION}")
    p = policy or default_policy_path()
    try:
        cfg = load_config(p)
        typer.echo(f"policy {cfg.policy_version}  ({p})  quarter {cfg.quarter.label}")
    except Exception as exc:  # a broken policy must not stop `version` from answering
        typer.echo(f"policy: could not load {p}: {exc}")


@app.command("next-policy")
def next_policy(policy: Optional[Path] = PolicyOpt,
                note: str = typer.Option("", "--note", help="One-line reason recorded at the top of the file"),
                quarter: Optional[str] = typer.Option(None, "--for", help="Write the file for this quarter instead of the next one, e.g. \"Q2 2026\"")) -> None:
    """Write the next quarter's policy file (inherits everything, new window only). Step 4 of a refresh.
    `--for "Q2 2026"` writes the file for any quarter, for a workbook that arrives out of order."""
    from .config import write_next_policy

    src = (policy or default_policy_path()).resolve()
    try:
        out = write_next_policy(src, note=note, quarter=quarter)
    except FileExistsError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    cfg = load_config(out)
    typer.echo(f"wrote {out}  quarter {cfg.quarter.label}  window {cfg.quarter.window_start}..{cfg.quarter.window_end}  "
               f"inherits {cfg.inherits}")


@app.command()
def validate(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
             overrides: Optional[Path] = OverridesOpt, ledger_dir: Optional[Path] = LedgerDirOpt) -> None:
    """Ingest the workbook and run the X-9xx integrity checks. Exit 1 if anything blocks."""
    from .ingest.reader import IngestError, read_workbook
    from .ingest.validate import validate as _validate
    from .pipeline import load_mark_basis, sidecar_for

    paths = _paths(input_path, policy, overrides, ledger_dir)
    cfg = load_config(paths.policy)
    try:
        snapshot, feed = read_workbook(paths.workbook, cfg)
    except IngestError as exc:
        typer.echo(f"INGEST ERROR: {exc}")
        raise typer.Exit(code=1)
    # Same inputs as a run: the prior quarter's sidecar explains marks that deliberately depart
    # from ownership × post-money, so `validate` must not block what `run` would accept.
    sidecar = sidecar_for(paths, cfg)
    issues = _validate(snapshot, feed, cfg, explained_departures=load_mark_basis(sidecar))
    if sidecar.exists():
        typer.echo(f"open items carried from {sidecar}")
    typer.echo(f"{paths.workbook.name}: {len(snapshot.positions)} positions, {len(feed.events)} events "
               f"on '{feed.sheet_name}'; {len(issues)} issue(s)")
    for sev in (Severity.BLOCK, Severity.REVIEW, Severity.MONITOR):
        group = [i for i in issues if i.severity == sev]
        if not group:
            continue
        typer.echo(f"\n{sev.value} ({len(group)})")
        for i in group:
            where = f"{i.sheet} row {i.row_index}" if i.sheet else "-"
            typer.echo(f"  {i.rule_id}  {where:<26} {i.company or '':<20} {i.message}")
    blocking = sum(1 for i in issues if i.blocking)
    typer.echo(f"\n{'BLOCKED' if blocking else 'OK'}: {blocking} blocking issue(s)")
    raise typer.Exit(code=1 if blocking else 0)


@app.command()
def rules(policy: Optional[Path] = PolicyOpt) -> None:
    """Print the rule catalogue (built-in + declarative rules from the policy)."""
    cfg = load_config((policy or default_policy_path()).resolve())
    rows = []
    for m in build_registry(cfg).all():
        rows.append([m.rule_id, m.version, m.severity.value if m.severity else "-",
                     "base" if m.effective_from == date.min else m.effective_from.isoformat(),
                     m.source, ", ".join(m.applies_to) or "-", m.description])
    typer.echo(_table(["id", "version", "severity", "effective", "source", "applies to", "description"], rows))


@app.command()
def export(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
           overrides: Optional[Path] = OverridesOpt, ledger_dir: Optional[Path] = LedgerDirOpt,
           out: Path = typer.Option(Path("dist"), "--out", "-o", help="Output folder"),
           provider: Optional[str] = ProviderOpt) -> None:
    """Write the review workbook and CSVs only."""
    from .export import write_csvs, write_workbook
    from .pipeline import execute

    r = execute(_paths(input_path, policy, overrides, ledger_dir), provider=provider)
    out.mkdir(parents=True, exist_ok=True)
    try:
        from .api.sources import build_sources
        sources = build_sources(r)          # so the Audit Trail cites the cell behind every input
    except Exception as exc:  # noqa: BLE001
        sources = None
        typer.echo(f"warning: cell provenance unavailable ({type(exc).__name__}: {exc}); the Audit Trail will cite no cells", err=True)
    xlsx = write_workbook(r.run, out / f"valuation_{_slug(r.run.manifest.quarter_label)}.xlsx", sources)
    csvs = write_csvs(r.run, out, sources)
    typer.echo(_headline(r.run))
    for p in [xlsx, *csvs]:
        typer.echo(f"wrote {p}")


@app.command()
def build(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
          overrides: Optional[Path] = OverridesOpt, ledger_dir: Optional[Path] = LedgerDirOpt,
          out: Path = typer.Option(Path("dist"), "--out", "-o", help="Output folder"),
          provider: Optional[str] = ProviderOpt, refresh_market: bool = RefreshMarketOpt,
          recommender: Optional[str] = RecommenderOpt) -> None:
    """Produce every deliverable: report.html, workbook, CSVs, next-quarter input file, run.json, manifest.json."""
    from .api.app import STATIC_DIR
    from .api.history import build_history
    from .export import (next_quarter_label, write_csvs, write_history_csv, write_next_quarter_workbook,
                         write_static_report, write_workbook)
    from .pipeline import execute

    paths = _paths(input_path, policy, overrides, ledger_dir)
    r = execute(paths, provider=_default_provider(paths, provider), refresh_market=refresh_market, recommender=recommender)
    run = r.run
    out.mkdir(parents=True, exist_ok=True)
    q = _slug(run.manifest.quarter_label)
    try:
        from .api.sources import build_sources
        sources = build_sources(r)     # cell provenance, inlined as window.__HC_SOURCES__
    except Exception as exc:  # noqa: BLE001
        sources = None                 # the report still renders, but say so: an audit trail without cells is a downgrade
        typer.echo(f"warning: cell provenance unavailable ({type(exc).__name__}: {exc}); the report and Audit Trail will cite no cells", err=True)
    from .prior_screen import prior_screen_for
    history = build_history(run, paths.root, prior_screen=prior_screen_for(r), published=paths.published_dir)   # the per-company archive, inlined as window.__HC_HISTORY__
    try:
        from .api.signals import build_signals
        signals = build_signals(r)             # vendor context (Foresight / AlphaSense stubs), window.__HC_SIGNALS__
    except Exception:
        signals = None                         # optional: a missing fixture just means no vendor card
    blocking = [i for i in run.validation if i.blocking]
    written = [
        write_static_report(run, out / "report.html", STATIC_DIR, sources, r.market_report, history, signals,
                            _load_rationale(paths.root)),
        write_workbook(run, out / f"valuation_{q}.xlsx", sources),
        *write_csvs(run, out, sources),
        write_history_csv(history, out / "mark_history.csv"),
    ]
    if blocking:
        # A book the reader refused rows of is reviewable (the report shows every X-9xx issue) but not
        # rollable: the next-quarter input is not emitted from a position the engine could not read.
        typer.echo(f"refused: {len(blocking)} blocking ingest issue(s); the next-quarter workbook is not emitted "
                   "until the cells are fixed (see report.html › validation, or `hc-valuation validate`):", err=True)
        for i in blocking[:20]:
            typer.echo(f"  {i.rule_id} {i.company or ''}: {i.message}", err=True)
    else:
        written += [
            write_next_quarter_workbook(run, paths.workbook, out / f"portfolio_{_slug(next_quarter_label(r.config.quarter.label))}.xlsx", r.config),
            out / "open_items_carry.yaml",
        ]
    (out / "run.json").write_text(run.model_dump_json(indent=2))
    (out / "manifest.json").write_text(run.manifest.model_dump_json(indent=2))
    written += [out / "run.json", out / "manifest.json"]
    # the IC pack: the executive report for the quarter's published snapshot, when one exists
    try:
        from .api.publish import exec_payload
        from .export.exec_report import write_exec_report
        view = exec_payload(paths.root, published=paths.published_dir)
        if view is not None:
            written.append(write_exec_report(view, out / "exec_report.html"))
        else:
            typer.echo("note: no published snapshot yet, so no exec_report.html — `hc-valuation publish --approver …` releases one")
    except Exception as exc:  # noqa: BLE001 — the IC pack is a convenience over the review deliverables
        typer.echo(f"warning: exec_report.html not written ({type(exc).__name__}: {exc})", err=True)
    typer.echo(_headline(run))
    typer.echo("")
    for p in written:
        typer.echo(f"wrote {p}")
    if not (STATIC_DIR / "index.html").is_file():
        typer.echo("note: no dashboard bundle in api/static; report.html is the plain fallback page")
    if blocking:
        raise typer.Exit(code=2)


@app.command()
def publish(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
            overrides: Optional[Path] = OverridesOpt, ledger_dir: Optional[Path] = LedgerDirOpt,
            approver: str = typer.Option(..., "--approver", "-a", help="Who is releasing these marks to executives"),
            note: str = typer.Option("", "--note", "-n", help="Short note shown on the executive dashboard"),
            out: Optional[Path] = typer.Option(None, "--out", "-o", help="Also write a self-contained exec_report.html here"),
            proposed: bool = typer.Option(False, "--proposed", help="Release an undecided book as PROPOSED (bypasses the "
                                          "decision gate; the dashboard button never does this)")) -> None:
    """Freeze the current run as the executive snapshot for its quarter (the publish gate). Refuses while any
    position is still BLOCK or REVIEW: every one must be decided or confirmed from the queue first."""
    from .api.publish import PublishBlocked, SecondApproverRequired, exec_payload, publish_run
    from .export.exec_report import write_exec_report
    from .pipeline import execute

    paths = _paths(input_path, policy, overrides, ledger_dir)
    r = execute(paths, provider=_default_provider(paths, None))
    try:
        rec = publish_run(r.run, paths.root, approver=approver, note=note, require_decisions=not proposed,
                          require_second_approver=r.config.publish.require_second_approver, published=paths.published_dir)
    except SecondApproverRequired as exc:
        typer.echo(f"refused: {exc}", err=True)
        raise typer.Exit(2)
    except PublishBlocked as exc:
        typer.echo(f"refused: {exc}", err=True)
        for i in exc.items:
            typer.echo(f"  {i['disposition']:<7} {i['company']:<22} {', '.join(x['rule_id'] for x in i['rules'])}", err=True)
        raise typer.Exit(2)
    typer.echo(f"published {rec['quarter']} as {rec['status'].upper()} by {rec['published_by']} "
               f"(run {rec['run_id']}, booked NAV {rec['booked_nav']:,.1f}, "
               f"{len(rec.get('open_positions', rec['open_blocks']))} position(s) not ready, {len(rec['open_blocks'])} blocked)")
    if rec["status"] == "final":
        from .pipeline import emit_next_quarter
        nxt = emit_next_quarter(r)
        typer.echo(f"next quarter's input: {nxt}  (sidecar {nxt.parent / 'open_items_carry.yaml'})")
    typer.echo(f"executive dashboard: {DASHBOARD_URL}/exec/  (after `hc-valuation run`)")
    if out is not None:
        view = exec_payload(paths.root, published=paths.published_dir)
        p = write_exec_report(view, Path(out) / "exec_report.html")
        typer.echo(f"wrote {p}")


@app.command()
def market(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
           overrides: Optional[Path] = OverridesOpt, ledger_dir: Optional[Path] = LedgerDirOpt,
           provider: Optional[str] = typer.Option(None, "--provider", help="stub | live | pitchbook | synthetic (default: HC_MARKET_PROVIDER, else stub)"),
           refresh: bool = typer.Option(False, "--refresh", help="Refetch over the cache (provider live)"),
           price_source: Optional[str] = typer.Option(None, "--price-source", help="yahoo | stooq — the price half of the live feed (default: HC_PRICE_SOURCE, else rules/comps_baskets.yaml defaults.price_source)"),
           as_json: bool = typer.Option(False, "--json", help="Print the /api/market payload as JSON")) -> None:
    """Show the sector comps feed: one line per sector, then errors (a source-wide outage is one
    line, not one per ticker). Exits 0 even when the fixture answered."""
    from .connectors import assemble_market_data
    from .ingest.reader import read_workbook

    paths = _paths(input_path, policy, overrides, ledger_dir)
    cfg = load_config(paths.policy)
    snapshot, feed = read_workbook(paths.workbook, cfg)
    rep = assemble_market_data(cfg, paths.root, snapshot, feed, provider=provider, refresh=refresh,
                               price_source=price_source).report
    if as_json:
        typer.echo(json.dumps(rep, indent=2))
        return
    cache = rep.get("cache") or {}
    cache_txt = f"{cache['dir']} ({'hit' if cache.get('hit') else 'miss'})" if cache else "-"
    typer.echo(f"provider {rep['provider']}  source {rep['source']}  as_of {rep['as_of']}  "
               f"fetched {rep.get('fetched_at') or '-'}  cache {cache_txt}")
    typer.echo(f"used by: {rep['used_by']['note']}")
    rows = []
    for s in rep["sectors"]:
        cons = s["constituents"]
        ok = sum(1 for c in cons if c["status"] == "ok")
        mult = f"{s['ev_to_revenue']:.2f}x" if s["ev_to_revenue"] is not None else "-"
        qoq = f"{s['qoq_pct']:+.1%}" if s.get("qoq_pct") is not None else "-"
        rows.append([s["sector"], str(s["positions"]), mult, qoq, s["source"], s["as_of_month"] or "-",
                     f"{ok}/{len(cons)}" if cons else "-"])
    typer.echo(_table(["sector", "positions", "EV/revenue", "qoq", "source", "month", "constituents ok"], rows))
    if rep["errors"]:
        typer.echo(f"\nerrors ({len(rep['errors'])})")
        for e in rep["errors"]:
            typer.echo(f"  {e}")


@app.command()
def history(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
            overrides: Optional[Path] = OverridesOpt, ledger_dir: Optional[Path] = LedgerDirOpt,
            company: Optional[str] = typer.Option(None, "--company", "-c", help="One company only"),
            as_json: bool = typer.Option(False, "--json", help="Print the /api/history payload as JSON")) -> None:
    """The booked-mark archive the review tool charts: one row per company per quarter, with
    where each point came from (backfill file, publish ledger, workbook Prior Mark, live run)."""
    from .api.history import build_history, history_rows
    from .pipeline import execute

    paths = _paths(input_path, policy, overrides, ledger_dir)
    r = execute(paths)
    from .prior_screen import prior_screen_for
    hist = build_history(r.run, paths.root, prior_screen=prior_screen_for(r), published=paths.published_dir)
    if company is not None:
        if company not in hist["companies"]:
            raise typer.BadParameter(f"no company named {company!r}; known: {', '.join(hist['companies'])}")
        hist["companies"] = {company: hist["companies"][company]}
    if as_json:
        typer.echo(json.dumps(hist, indent=2))
        return
    counts = ", ".join(f"{k} {v}" for k, v in hist["counts"].items() if v)
    typer.echo(f"as of {hist['as_of_quarter']}  quarters {', '.join(hist['quarters'])}  points: {counts}")
    if hist["backfill_file"]:
        typer.echo(f"backfill: {hist['backfill_file']}")
    headers, rows = history_rows(hist)
    keep = [0, 1, 2, 3, 4, 5, 6, 8, 9]
    fmt = lambda v: "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))  # noqa: E731
    typer.echo(_table([headers[i].replace(" ($M)", "").replace(" (x)", "") for i in keep],
                      [[fmt(row[i]) for i in keep] for row in rows]))
    notes = [(row[0], row[1], row[12]) for row in rows if row[12]]
    if notes:
        typer.echo(f"\nnotes ({len(notes)})")
        for c, q, n in notes:
            typer.echo(f"  {c} {q}: {n}")
    if hist["errors"]:
        typer.echo(f"\nerrors ({len(hist['errors'])})")
        for e in hist["errors"]:
            typer.echo(f"  {e}")


@app.command()
def recommend(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
              overrides: Optional[Path] = OverridesOpt, ledger_dir: Optional[Path] = LedgerDirOpt,
              recommender: Optional[str] = typer.Option("claude", "--recommender", help="policy | claude"),
              refresh: bool = typer.Option(False, "--refresh", help="Ignore cached answers and ask the model again"),
              as_json: bool = typer.Option(False, "--json", help="Print every recommendation as JSON")) -> None:
    """Fill (or show) the one recommendation per BLOCK/REVIEW flag. With --recommender claude and
    ANTHROPIC_API_KEY set, every answer is cached under data/recommendations/ — commit that folder
    and later runs are deterministic and offline."""
    from .pipeline import execute

    paths = _paths(input_path, policy, overrides, ledger_dir)
    r = execute(paths, recommender=recommender, refresh_recommendations=refresh)
    rows, out = [], []
    for c in r.run.companies:
        for f in c.flags:
            rec = f.recommendation
            if rec is None:
                continue
            out.append({"company": c.company, "rule_id": f.rule_id, "severity": f.severity.value,
                        **rec.model_dump(mode="json")})
            rows.append([c.company, f.rule_id, f.severity.value, rec.source + (f" ({rec.model})" if rec.model else ""),
                         rec.key, f"{rec.booked:.2f}", rec.label[:70]])
    if as_json:
        typer.echo(json.dumps(out, indent=2))
        return
    ch = r.recommender
    typer.echo(f"recommender {r.run.manifest.recommender}  flags {len(rows)}"
               + (f"  model calls {ch.calls}  cache hits {ch.cache_hits}  fallbacks {len(ch.fallbacks)}"
                  if hasattr(ch, "calls") else ""))
    typer.echo(_table(["company", "rule", "severity", "source", "choice", "booked", "label"], rows))
    if getattr(ch, "fallbacks", None):
        typer.echo(f"\nfell back to the policy default ({len(ch.fallbacks)}):")
        for line in ch.fallbacks[:10]:
            typer.echo(f"  {line}")
        if len(ch.fallbacks) > 10:
            typer.echo(f"  … {len(ch.fallbacks) - 10} more")


def _open_when_up(url: str, health: str, timeout: float = 30.0) -> None:
    """Poll /api/health from a thread, then open the browser. Never raises into the server."""
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=1) as resp:  # noqa: S310 - localhost only
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.25)
    else:
        return
    try:
        webbrowser.open(url)
    except Exception:
        pass


@app.command()
def run(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
        overrides: Optional[Path] = OverridesOpt, ledger_dir: Optional[Path] = LedgerDirOpt,
        port: int = typer.Option(DEFAULT_PORT, "--port"), host: str = typer.Option(DEFAULT_HOST, "--host"),
        no_browser: bool = typer.Option(False, "--no-browser", help="Do not open a browser tab"),
        watch: bool = typer.Option(False, "--watch", help="Recompute when the workbook, policy or a ledger changes; "
                                                          "the open dashboard reloads itself"),
        provider: Optional[str] = ProviderOpt, refresh_market: bool = RefreshMarketOpt,
        recommender: Optional[str] = RecommenderOpt) -> None:
    """Compute the run, serve the dashboard and API, open a browser. With --watch, a new
    workbook dropped in place (or an edited policy / ledger) re-runs and refreshes the page."""
    import uvicorn

    from .api.app import STATIC_DIR, create_app, watch_inputs

    from .config import repo_root

    if input_path is None:
        # The dashboard is upload-driven: with no --input it opens on the most recently uploaded workbook,
        # or empty (the Upload button) when nothing has been uploaded yet. The CLI commands keep their
        # file defaults; `run` is the one that a person drives from the browser.
        uploads = sorted((p for p in (repo_root() / "data" / "uploads").rglob("*.xlsx")
                          if not p.name.startswith("~$") and p.parent.name != "incoming"), key=lambda p: p.stat().st_mtime)
        if uploads:
            input_path = uploads[-1]
            typer.echo(f"opening the most recent upload: {input_path.relative_to(repo_root())}")
    if input_path is None:
        application = create_app(None, provider=provider, provider_explicit=provider, refresh_market=refresh_market,
                                 recommender=recommender, start_empty=True)
        typer.echo("no workbook loaded: upload one from the dashboard (or pass --input)")
    else:
        paths = _paths(input_path, policy, overrides, ledger_dir)
        application = create_app(paths, provider=_default_provider(paths, provider), provider_explicit=provider,
                                 refresh_market=refresh_market, recommender=recommender)
        typer.echo(_headline(application.state.result.run))
    url = f"http://{host}:{port}/"
    typer.echo(f"\nserving {url}  (API at {url}api/run; docs at {url}api/docs)")
    if watch:
        watch_inputs(application, log=lambda m: typer.echo(f"watch: {m}"))
        typer.echo("watch: recomputing whenever the workbook, policy, overrides or proposals change")
    if not (STATIC_DIR / "index.html").is_file():
        typer.echo("note: no dashboard bundle in api/static; '/' serves the plain report page")
    if not no_browser:
        threading.Thread(target=_open_when_up, args=(url, f"{url}api/health"), daemon=True).start()
    uvicorn.run(application, host=host, port=port, log_level="warning")


def main() -> None:  # pragma: no cover - console entry
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
