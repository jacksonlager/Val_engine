"""Screenshot the executive dashboard in light and dark from the built bundle.

Copies ../src/hc_valuation/api/static_exec to <tmp>/exec/ and serves <tmp> so the
`/exec/` base path resolves, injects data/sample_exec.json as window.__HC_EXEC__ via an
init script (the same path the single-file exec_report.html uses), then captures the
sections executives look at first. Also captures the empty state (no payload, /api/exec 404).

    python screenshot.py [--out /home/claude/hc/screenshots/exec]
"""
from __future__ import annotations

import argparse
import functools
import http.server
import shutil
import socketserver
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "hc_valuation" / "api" / "static_exec"
SAMPLE = ROOT / "data" / "sample_exec.json"

SECTIONS = {
    "top": "#top",
    "decisions": "#decisions",
    "funds": "#funds",
    "risk": "#risk",
    "sensitivity": "#sensitivity",
    "composition": "#composition",
    "activity": "#activity",
}


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass


def serve(directory: Path) -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(_Quiet, directory=str(directory))
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/home/claude/hc/screenshots/exec")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="hc-exec-"))
    shutil.copytree(STATIC, tmp / "exec")
    payload = SAMPLE.read_text()
    srv, port = serve(tmp)
    url = f"http://127.0.0.1:{port}/exec/"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for scheme in ("dark", "light"):
                ctx = browser.new_context(viewport={"width": args.width, "height": args.height}, color_scheme=scheme, device_scale_factor=1)
                ctx.add_init_script(f"window.__HC_EXEC__ = {payload};")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.goto(url)
                page.wait_for_selector("#bridge svg", timeout=15000)
                page.wait_for_timeout(600)
                for name, sel in SECTIONS.items():
                    page.evaluate(f"window.scrollTo({{top: document.querySelector('{sel}').getBoundingClientRect().top + window.scrollY - 56, behavior: 'instant'}})")
                    page.wait_for_timeout(250)
                    page.screenshot(path=str(out / f"{name}-{scheme}.png"))
                page.evaluate("window.scrollTo(0,0)")
                page.wait_for_timeout(200)
                page.screenshot(path=str(out / f"full-{scheme}.png"), full_page=True)
                # hover the largest bridge bar so the tooltip is captured
                page.evaluate("window.scrollTo({top: document.querySelector('#bridge').getBoundingClientRect().top + window.scrollY - 56, behavior: 'instant'})")
                bars = page.query_selector_all("#bridge svg g[tabindex]")
                if len(bars) > 1:
                    bars[1].hover()
                    page.wait_for_timeout(200)
                    page.screenshot(path=str(out / f"bridge-hover-{scheme}.png"))
                ctx.close()
                print(f"{scheme}: {'no console errors' if not errors else errors}")

            # empty state: no payload injected, /api/exec 404s from the static server
            ctx = browser.new_context(viewport={"width": args.width, "height": args.height}, color_scheme="dark")
            page = ctx.new_page()
            page.goto(url)
            page.wait_for_selector("text=No quarter has been released yet", timeout=10000)
            page.screenshot(path=str(out / "empty-dark.png"))
            ctx.close()
            browser.close()
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote screenshots to {out}")


if __name__ == "__main__":
    main()
