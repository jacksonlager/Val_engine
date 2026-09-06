"""Single-file HTML report.

Two modes, same entry point:

* the built dashboard exists in `static_dir` -> inline its JS/CSS into one file and inject
  the run as `window.__HC_RUN__` (plus `__HC_SOURCES__`, the mark history as `__HC_HISTORY__` and the market report as
  `__HC_MARKET__`), so the exported page is the served dashboard minus the server;
* it does not (fresh clone without a frontend build) -> render a plain, dependency-free
  page with the headline numbers, the queue and the full tables. `hc-valuation build`
  must always leave something a reviewer can open.

Every local asset is inlined, so the file can be emailed and opened from disk. The
fallback page makes no external requests at all; the bundle mode keeps whatever
third-party `<link>`s the frontend chose (web fonts), which degrade gracefully offline.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from ..engine.models import Disposition, ValuationRun
from .tables import INT, MULT, MUSD, NUM, PCT, TEXT, Table, exceptions_table, marks_table, summary_rows

_SCRIPT_TAG = re.compile(r"<script\b([^>]*)\bsrc=[\"']([^\"']+)[\"']([^>]*)>\s*</script>", re.I)
_LINK_TAG = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"(\w[\w-]*)\s*=\s*[\"']([^\"']*)[\"']")


def run_json_script(run: ValuationRun) -> str:
    """`<script>window.__HC_RUN__ = ...</script>` with `<` escaped so a rationale containing
    `</script>` cannot break out of the tag."""
    payload = run.model_dump_json()
    return "<script>window.__HC_RUN__ = " + payload.replace("<", "\\u003c") + ";</script>"


def sources_json_script(sources: dict | None) -> str:
    """`window.__HC_SOURCES__` — the cell provenance from `api.sources.build_sources`, escaped
    the same way. Empty string when there is none: the dashboard treats sources as optional
    and simply shows no cell references."""
    if not sources:
        return ""
    payload = json.dumps(sources, default=str)
    return "<script>window.__HC_SOURCES__ = " + payload.replace("<", "\\u003c") + ";</script>"


def market_json_script(market: dict | None) -> str:
    """`window.__HC_MARKET__` — the `/api/market` report (docs/market-feed.md §3), escaped the
    same way, so the Market panel works in the exported file. Empty when there is none."""
    if not market:
        return ""
    payload = json.dumps(market, default=str)
    return "<script>window.__HC_MARKET__ = " + payload.replace("<", "\\u003c") + ";</script>"


def history_json_script(history: dict | None) -> str:
    """`window.__HC_HISTORY__` — the `/api/history` archive (api/history.py), escaped the same
    way, so the per-company history chart works in the exported file. Empty when none."""
    if not history:
        return ""
    payload = json.dumps(history, default=str)
    return "<script>window.__HC_HISTORY__ = " + payload.replace("<", "\\u003c") + ";</script>"


def signals_json_script(signals: dict | None) -> str:
    """`window.__HC_SIGNALS__` — the `/api/signals` vendor context (api/signals.py). Empty when none."""
    if not signals:
        return ""
    payload = json.dumps(signals, default=str)
    return "<script>window.__HC_SIGNALS__ = " + payload.replace("<", "\\u003c") + ";</script>"


def rationale_json_script(rationale: dict | None) -> str:
    """`window.__HC_RATIONALE__` — `/api/rationale`, the two bullets behind every rule (rules/rationale.yaml)."""
    if not rationale:
        return ""
    payload = json.dumps(rationale, default=str)
    return "<script>window.__HC_RATIONALE__ = " + payload.replace("<", "\\u003c") + ";</script>"


# ---------------------------------------------------------------- bundle inlining

def _is_local(ref: str) -> bool:
    r = ref.strip().lower()
    return not (r.startswith(("http:", "https:", "//", "data:")))


def _resolve(static_dir: Path, ref: str) -> Path | None:
    rel = ref.split("?")[0].split("#")[0].lstrip("/")
    p = (static_dir / rel).resolve()
    try:
        p.relative_to(static_dir.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def inline_bundle(index_html: str, static_dir: Path, run: ValuationRun, sources: dict | None = None,
                  market: dict | None = None, history: dict | None = None, signals: dict | None = None,
                  rationale: dict | None = None) -> str:
    def script_repl(m: re.Match) -> str:
        pre, src, post = m.group(1), m.group(2), m.group(3)
        p = _resolve(static_dir, src) if _is_local(src) else None
        if p is None:
            return m.group(0)
        attrs = " ".join(a for a in (pre + " " + post).split() if not a.lower().startswith("crossorigin"))
        js = p.read_text(encoding="utf-8").replace("</script", "<\\/script")
        return f"<script {attrs}>\n{js}\n</script>" if attrs.strip() else f"<script>\n{js}\n</script>"

    def link_repl(m: re.Match) -> str:
        tag = m.group(0)
        attrs = {k.lower(): v for k, v in _ATTR.findall(tag)}
        rel, href = attrs.get("rel", "").lower(), attrs.get("href", "")
        if not href or not _is_local(href):
            return tag
        p = _resolve(static_dir, href)
        if rel == "stylesheet" and p is not None:
            css = p.read_text(encoding="utf-8").replace("</style", "<\\/style")
            return f"<style>\n{css}\n</style>"
        if rel == "modulepreload":
            return ""   # the module is inlined; a preload of a missing file is just noise
        return tag

    out = _SCRIPT_TAG.sub(script_repl, index_html)
    out = _LINK_TAG.sub(link_repl, out)
    injection = (run_json_script(run) + sources_json_script(sources) + market_json_script(market)
                 + history_json_script(history) + signals_json_script(signals) + rationale_json_script(rationale))
    idx = out.lower().find("<script")
    if idx < 0:
        idx = out.lower().find("</head>")
    if idx < 0:
        return injection + out
    return out[:idx] + injection + "\n" + out[idx:]


# ---------------------------------------------------------------- fallback page

_CSS = """
:root{--ink:#1c1f26;--muted:#5b6270;--line:#d9dde5;--bg:#ffffff;--panel:#f5f6f8;--block:#b3261e;--review:#b26a00;--monitor:#2f5e9e;--clear:#2b7a4b}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
main{max-width:1400px;margin:0 auto;padding:24px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}.sub{color:var(--muted);margin-bottom:16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.tile .k{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}.tile .v{font-size:20px;font-weight:600;margin-top:2px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:12.5px;white-space:nowrap}th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{position:sticky;top:0;background:var(--panel);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}td.wrap-text{white-space:normal;min-width:320px}
.pill{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:600;color:#fff}
.BLOCK{background:var(--block)}.REVIEW{background:var(--review)}.MONITOR{background:var(--monitor)}.CLEAR{background:var(--clear)}
ul.queue{margin:0;padding-left:18px}ul.queue li{margin:2px 0}.meta{font-size:12px;color:var(--muted)}
"""


def _fmt(v, kind: str) -> str:
    if v is None:
        return ""
    if kind == MUSD or kind == NUM:
        return f"{v:,.2f}"
    if kind == PCT:
        return f"{v:.1%}"
    if kind == MULT:
        return f"{v:.2f}x"
    if kind == INT:
        return f"{int(v)}"
    return html.escape(str(v))


def _table_html(t: Table, wrap_cols: tuple[str, ...] = ()) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in t.headers)
    body = []
    for row in t.rows:
        cells = []
        for h, v, k in zip(t.headers, row, t.kinds):
            if h == "Disposition" or h == "Severity":
                cells.append(f'<td><span class="pill {html.escape(str(v))}">{html.escape(str(v))}</span></td>')
            elif k == TEXT:
                cls = ' class="wrap-text"' if h in wrap_cols else ""
                cells.append(f"<td{cls}>{_fmt(v, k)}</td>")
            else:
                cells.append(f'<td class="n">{_fmt(v, k)}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def fallback_html(run: ValuationRun, sources: dict | None = None, market: dict | None = None,
                  history: dict | None = None, signals: dict | None = None) -> str:
    m, t = run.manifest, run.totals
    tiles = [
        ("Prior NAV ($M)", f"{t.prior_nav:,.1f}"), ("Proposed NAV ($M)", f"{t.proposed_nav:,.1f}"),
        ("Booked NAV ($M)", f"{t.booked_nav:,.1f}"), ("Net movement ($M)", f"{t.net_movement:+,.1f}"),
        ("Realized in quarter ($M)", f"{t.realized_quarter:,.1f}"), ("Written off ($M)", f"{t.written_off:,.1f}"), ("Exited at prior mark ($M)", f"{t.exited_at_prior_mark:,.1f}"),
        ("Positions", f"{t.positions} ({t.active_after} active)"), ("Level 1", f"{t.level1_positions}"),
    ] + [(f"{k}", f"{v}") for k, v in t.dispositions.items()]
    tiles_html = "".join(f'<div class="tile"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div></div>' for k, v in tiles)

    def queue(d: Disposition) -> str:
        items = [c for c in run.companies if c.disposition == d]
        if not items:
            return "<p class='meta'>none</p>"
        lis = []
        for c in items:
            rules = ", ".join(f"{f.rule_id} ({f.severity.value})" for f in c.flags)
            lis.append(f"<li><strong>{html.escape(c.company)}</strong> — {c.prior_mark:,.2f} → {c.proposed_mark:,.2f} $M"
                       f" · booked {c.booked_mark:,.2f} · <span class='meta'>{html.escape(rules)}</span></li>")
        return "<ul class='queue'>" + "".join(lis) + "</ul>"

    validation = ""
    if run.validation:
        validation = "<h2>Validation issues</h2><ul class='queue'>" + "".join(
            f"<li>{html.escape(v.rule_id)} [{v.severity.value}{', blocking' if v.blocking else ''}] "
            f"{html.escape(v.company or '')} — {html.escape(v.message)}</li>" for v in run.validation) + "</ul>"
    summary = "".join(f"<li>{html.escape(k)}: {html.escape(_fmt(v, kind))}</li>" for k, v, kind in summary_rows(run) if k)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HC valuation — {html.escape(m.quarter_label)}</title><style>{_CSS}</style>
{run_json_script(run)}{sources_json_script(sources)}{market_json_script(market)}{history_json_script(history)}{signals_json_script(signals)}
</head><body><main>
<h1>Quarterly valuation — {html.escape(m.quarter_label)}</h1>
<div class="sub">Measurement date {m.measurement_date.isoformat()} · policy {html.escape(m.policy_version)} · engine {html.escape(m.engine_version)}
 · run {html.escape(m.run_id)} · input {html.escape(m.input_file)} (sha256 {html.escape(m.input_sha256[:12])}…) · generated {m.generated_at.isoformat()}
 · market data: {html.escape(m.market_data_source)}</div>
<div class="tiles">{tiles_html}</div>
{validation}
<h2>Blocked — committee decision required</h2>{queue(Disposition.BLOCK)}
<h2>Review</h2>{queue(Disposition.REVIEW)}
<h2>Marks</h2>{_table_html(marks_table(run))}
<h2>Exceptions</h2>{_table_html(exceptions_table(run), wrap_cols=("Message",))}
<h2>Run summary</h2><ul class="queue meta">{summary}</ul>
<p class="meta">Static export. The full audit chain per company is in the workbook (Audit Trail tab) and in run.json; the served dashboard (hc-valuation run) shows it inline.</p>
</main></body></html>
"""


def render_report(run: ValuationRun, static_dir: str | Path | None, sources: dict | None = None,
                  market: dict | None = None, history: dict | None = None, signals: dict | None = None,
                  rationale: dict | None = None) -> str:
    """The report HTML: the inlined dashboard bundle when present, else the fallback page.

    `sources` is the optional cell provenance (`api.sources.build_sources`); when given it is
    injected as `window.__HC_SOURCES__` so the exported dashboard keeps its cell references.
    `market` is the optional market report (`/api/market`), injected as `window.__HC_MARKET__`;
    `history` the optional mark archive (`/api/history`), injected as `window.__HC_HISTORY__`."""
    if static_dir is not None:
        index = Path(static_dir) / "index.html"
        if index.is_file():
            return inline_bundle(index.read_text(encoding="utf-8"), Path(static_dir), run, sources, market, history, signals, rationale)
    return fallback_html(run, sources, market, history, signals)


def write_static_report(run: ValuationRun, path: str | Path, static_dir: str | Path | None = None,
                        sources: dict | None = None, market: dict | None = None,
                        history: dict | None = None, signals: dict | None = None,
                        rationale: dict | None = None) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(run, static_dir, sources, market, history, signals, rationale), encoding="utf-8")
    return out
