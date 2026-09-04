"""Self-contained executive report: the exec bundle inlined with the published view-model.

`hc-valuation publish --out dist/` writes `exec_report.html`, a single file that renders
the executive dashboard for the published quarter with no server — the thing you attach
to the IC pack or drop on an intranet page.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .static_report import _LINK_TAG, _SCRIPT_TAG, _ATTR, _is_local, _resolve  # noqa: F401 - shared inliner

EXEC_STATIC_DIR = Path(__file__).resolve().parents[1] / "api" / "static_exec"


def exec_json_script(view: dict[str, Any]) -> str:
    return "<script>window.__HC_EXEC__ = " + json.dumps(view).replace("<", "\\u003c") + ";</script>"


def inline_exec_bundle(index_html: str, static_dir: Path, view: dict[str, Any]) -> str:
    import re

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
            return "<style>\n" + p.read_text(encoding="utf-8").replace("</style", "<\\/style") + "\n</style>"
        if rel == "modulepreload":
            return ""
        return tag

    out = _SCRIPT_TAG.sub(script_repl, index_html)
    out = _LINK_TAG.sub(link_repl, out)
    injection = exec_json_script(view)
    idx = out.lower().find("<script")
    if idx < 0:
        idx = out.lower().find("</head>")
    return (out[:idx] + injection + "\n" + out[idx:]) if idx >= 0 else injection + out


def fallback_exec_html(view: dict[str, Any]) -> str:
    """A plain page if the exec bundle has not been built: the headline and the decisions."""
    h, m = view["headline"], view["meta"]
    rows = "".join(
        f"<tr><td>{html.escape(d['company'])}</td><td class=n>{d['prior']:.2f}</td><td class=n>{d['booked']:.2f}</td>"
        f"<td class=n>{d['delta']:+.2f}</td><td>{html.escape('; '.join(a['action'] for a in d['actions']))}</td></tr>"
        for d in view["decisions"]
    )
    return f"""<!doctype html><meta charset=utf-8><title>{html.escape(m['firm'])} — {html.escape(m['quarter'])} valuation</title>
<style>body{{font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:32px;color:#1c1f26}}
td,th{{padding:6px 10px;border-bottom:1px solid #d9dde5;text-align:left}}td.n{{text-align:right;font-variant-numeric:tabular-nums}}</style>
<h1>{html.escape(m['firm'])} · {html.escape(m['quarter'])} marks ({html.escape(m['status'])})</h1>
<p>Prior NAV ${h['prior_nav']:,.1f}M → booked ${h['booked_nav']:,.1f}M ({h['net_movement']:+,.1f}M). Realized ${h['realized_quarter']:,.1f}M. Written off ${h['written_off']:,.1f}M; exited ${h['exited_at_prior_mark']:,.1f}M at prior mark.</p>
<p>Published {html.escape(str(m.get('published_at')))} by {html.escape(str(m.get('published_by')))} · run {html.escape(m['run_id'])} · policy {html.escape(m['policy_version'])}</p>
<h2>Awaiting committee decision ({len(view['decisions'])})</h2>
<table><tr><th>Company<th>Prior<th>Booked<th>Δ<th>Decision needed</tr>{rows}</table>
{exec_json_script(view)}"""


def render_exec_report(view: dict[str, Any], static_dir: Path | None = None) -> str:
    static_dir = Path(static_dir) if static_dir is not None else EXEC_STATIC_DIR
    index = static_dir / "index.html"
    if index.is_file():
        return inline_exec_bundle(index.read_text(encoding="utf-8"), static_dir, view)
    return fallback_exec_html(view)


def write_exec_report(view: dict[str, Any], out_path: str | Path, static_dir: Path | None = None) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_exec_report(view, static_dir), encoding="utf-8")
    return out
