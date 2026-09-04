"""`hc-valuation` — the command line.

    run       serve the dashboard (and open a browser)
    build     write the whole deliverable set into a folder, no server needed
    validate  ingest + integrity checks only
    export    workbook + CSVs only
    rules     print the rule catalogue
    next-policy  write rules/<next quarter>.yaml inheriting from the current policy
    version   engine and policy versions

Plain output, no colour required: this is meant to be read in a terminal log as much as
on a screen.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import typer

from .config import default_policy_path, load_config
from .engine.models import Severity, ValuationRun
from .engine.run import ENGINE_VERSION, build_registry


def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version as _v
    try:
        return _v("hc-valuation")
    except PackageNotFoundError:  # running from a checkout without an install
        return "unknown"

app = typer.Typer(
    add_completion=False, no_args_is_help=True, rich_markup_mode=None,
    help="HC valuation engine: roll the portfolio forward through the quarter's activity, propose marks, "
         "and flag what a human must review. Start with `hc-valuation run`.",
)

InputOpt = typer.Option(None, "--input", "-i", help="Portfolio workbook (.xlsx). Default: data/HC_Mock_Portfolio_Data.xlsx")
PolicyOpt = typer.Option(None, "--policy", "-p", help="Policy file. Default: rules/2026Q3.yaml (the base policy)")
ProviderOpt = typer.Option(None, "--provider", help="Market-data provider override (stub | live), passed to the connectors")


def _paths(input_path: Optional[Path], policy: Optional[Path]):
    from .pipeline import RunPaths
    return RunPaths.default(workbook=input_path.resolve() if input_path else None,
                            policy=policy.resolve() if policy else None)


def _slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")


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
                note: str = typer.Option("", "--note", help="One-line reason recorded at the top of the file")) -> None:
    """Write the next quarter's policy file (inherits everything, new window only). Step 4 of a refresh."""
    from .config import write_next_policy

    src = (policy or default_policy_path()).resolve()
    try:
        out = write_next_policy(src, note=note)
    except FileExistsError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    cfg = load_config(out)
    typer.echo(f"wrote {out}  quarter {cfg.quarter.label}  window {cfg.quarter.window_start}..{cfg.quarter.window_end}  "
               f"inherits {cfg.inherits}")


@app.command()
def validate(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt) -> None:
    """Ingest the workbook and run the X-9xx integrity checks. Exit 1 if anything blocks."""
    from .ingest.reader import IngestError, read_workbook
    from .ingest.validate import validate as _validate
    from .pipeline import load_mark_basis

    paths = _paths(input_path, policy)
    cfg = load_config(paths.policy)
    try:
        snapshot, feed = read_workbook(paths.workbook, cfg)
    except IngestError as exc:
        typer.echo(f"INGEST ERROR: {exc}")
        raise typer.Exit(code=1)
    # Same inputs as a run: the prior quarter's sidecar explains marks that deliberately depart
    # from ownership × post-money, so `validate` must not block what `run` would accept.
    issues = _validate(snapshot, feed, cfg, explained_departures=load_mark_basis(paths.open_items_carry))
    if paths.open_items_carry.exists():
        typer.echo(f"open items carried from {paths.open_items_carry}")
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
        rows.append([m.rule_id, m.version, m.severity.value if m.severity else "-", m.effective_from.isoformat(),
                     m.source, ", ".join(m.applies_to) or "-", m.description])
    typer.echo(_table(["id", "version", "severity", "effective", "source", "applies to", "description"], rows))


@app.command()
def export(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
           out: Path = typer.Option(Path("dist"), "--out", "-o", help="Output folder"),
           provider: Optional[str] = ProviderOpt) -> None:
    """Write the review workbook and CSVs only."""
    from .export import write_csvs, write_workbook
    from .pipeline import execute

    r = execute(_paths(input_path, policy), provider=provider)
    out.mkdir(parents=True, exist_ok=True)
    xlsx = write_workbook(r.run, out / f"valuation_{_slug(r.run.manifest.quarter_label)}.xlsx")
    csvs = write_csvs(r.run, out)
    typer.echo(_headline(r.run))
    for p in [xlsx, *csvs]:
        typer.echo(f"wrote {p}")


@app.command()
def build(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
          out: Path = typer.Option(Path("dist"), "--out", "-o", help="Output folder"),
          provider: Optional[str] = ProviderOpt) -> None:
    """Produce every deliverable: report.html, workbook, CSVs, next-quarter input file, run.json, manifest.json."""
    from .api.app import STATIC_DIR
    from .export import next_quarter_label, write_csvs, write_next_quarter_workbook, write_static_report, write_workbook
    from .pipeline import execute

    paths = _paths(input_path, policy)
    r = execute(paths, provider=provider)
    run = r.run
    out.mkdir(parents=True, exist_ok=True)
    q = _slug(run.manifest.quarter_label)
    try:
        from .api.sources import build_sources
        sources = build_sources(r)     # cell provenance, inlined as window.__HC_SOURCES__
    except Exception:
        sources = None                 # optional everywhere: the report just shows no cell refs
    written = [
        write_static_report(run, out / "report.html", STATIC_DIR, sources),
        write_workbook(run, out / f"valuation_{q}.xlsx"),
        *write_csvs(run, out),
        write_next_quarter_workbook(run, paths.workbook, out / f"portfolio_{_slug(next_quarter_label(r.config.quarter.label))}.xlsx", r.config),
        out / "open_items_carry.yaml",
    ]
    (out / "run.json").write_text(run.model_dump_json(indent=2))
    (out / "manifest.json").write_text(run.manifest.model_dump_json(indent=2))
    written += [out / "run.json", out / "manifest.json"]
    typer.echo(_headline(run))
    typer.echo("")
    for p in written:
        typer.echo(f"wrote {p}")
    if not (STATIC_DIR / "index.html").is_file():
        typer.echo("note: no dashboard bundle in api/static; report.html is the plain fallback page")


@app.command()
def publish(input_path: Optional[Path] = InputOpt, policy: Optional[Path] = PolicyOpt,
            approver: str = typer.Option(..., "--approver", "-a", help="Who is releasing these marks to executives"),
            note: str = typer.Option("", "--note", "-n", help="Short note shown on the executive dashboard"),
            out: Optional[Path] = typer.Option(None, "--out", "-o", help="Also write a self-contained exec_report.html here")) -> None:
    """Freeze the current run as the executive snapshot for its quarter (the publish gate)."""
    from .api.publish import exec_payload, publish_run
    from .export.exec_report import write_exec_report
    from .pipeline import execute

    paths = _paths(input_path, policy)
    r = execute(paths)
    rec = publish_run(r.run, paths.root, approver=approver, note=note)
    typer.echo(f"published {rec['quarter']} as {rec['status'].upper()} by {rec['published_by']} "
               f"(run {rec['run_id']}, booked NAV {rec['booked_nav']:,.1f}, {len(rec['open_blocks'])} open block(s))")
    typer.echo(f"executive dashboard: http://127.0.0.1:8765/exec/  (after `hc-valuation run`)")
    if out is not None:
        view = exec_payload(paths.root)
        p = write_exec_report(view, Path(out) / "exec_report.html")
        typer.echo(f"wrote {p}")


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
        port: int = typer.Option(8765, "--port"), host: str = typer.Option("127.0.0.1", "--host"),
        no_browser: bool = typer.Option(False, "--no-browser", help="Do not open a browser tab"),
        provider: Optional[str] = ProviderOpt) -> None:
    """Compute the run, serve the dashboard and API, open a browser."""
    import uvicorn

    from .api.app import STATIC_DIR, create_app

    application = create_app(_paths(input_path, policy), provider=provider)
    typer.echo(_headline(application.state.result.run))
    url = f"http://{host}:{port}/"
    typer.echo(f"\nserving {url}  (API at {url}api/run; docs at {url}api/docs)")
    if not (STATIC_DIR / "index.html").is_file():
        typer.echo("note: no dashboard bundle in api/static; '/' serves the plain report page")
    if not no_browser:
        threading.Thread(target=_open_when_up, args=(url, f"{url}api/health"), daemon=True).start()
    uvicorn.run(application, host=host, port=port, log_level="warning")


def main() -> None:  # pragma: no cover - console entry
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
