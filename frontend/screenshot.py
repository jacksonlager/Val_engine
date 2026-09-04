"""Screenshot every dashboard view in light and dark from the built bundle.

Serves ../src/hc_valuation/api/static over a local static server (no API, so the page
runs in static mode) and injects data/sample_run.json as window.__HC_RUN__ via an init
script — the same path `hc-valuation build` uses for the single-file report.

    python screenshot.py [--out /home/claude/hc/screenshots]
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "hc_valuation" / "api" / "static"
SAMPLE = ROOT / "data" / "sample_run.json"

VIEWS = ["queue", "companies", "movement", "funds", "open", "proposals"]


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
    ap.add_argument("--out", default="/home/claude/hc/screenshots")
    ap.add_argument("--full", action="store_true", help="full-page screenshots instead of the 1440x900 viewport")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    run_json = SAMPLE.read_text()
    srv, port = serve(STATIC)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for scheme in ("light", "dark"):
                ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=scheme, device_scale_factor=1)
                ctx.add_init_script(f"window.__HC_RUN__ = {run_json};")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                for view in VIEWS:
                    page.goto(f"http://127.0.0.1:{port}/index.html#{view}")
                    page.wait_for_selector("main")
                    page.wait_for_timeout(600)
                    if view == "queue":
                        # expand the first BLOCK card so the audit chain is in the shot
                        page.locator("main button", has_text="Audit chain").first.click()
                        page.wait_for_timeout(300)
                    if view == "companies":
                        page.locator("tr.row").first.click()
                        page.wait_for_timeout(300)
                    page.screenshot(path=str(out / f"{view}-{scheme}.png"), full_page=args.full)
                    print("wrote", out / f"{view}-{scheme}.png")
                # a synthetic proposal so the card layout is exercised even when the run has no M-999 halt
                ctx.add_init_script("""window.__HC_PROPOSALS__ = [{
                    proposal_id: 'spac-merger-2026q3', company: 'Gryphonel', event_type: 'SPAC Merger', event_signature: 'spac_merger|deal_value|ownership_after',
                    analogue_rule_id: 'M-040', proposed_kind: 'new_rule',
                    formula: 'ownership_after * deal_value * close_probability',
                    parameter_map: { deal_value: 'event.value', close_probability: 'config.marking.announced.close_probability' },
                    suggested_severity: 'BLOCK', confidence: 0.62,
                    rationale: 'A SPAC merger is an announced business combination whose consideration is listed equity; treat like M-050 until close, then M-040 at the market close.',
                    missing_facts: ['Redemption rate and resulting float', 'Sponsor earn-out and lock-up terms', 'Whether HC shares are registered at close'],
                    provenance: { model: 'stub-heuristics', prompt_hash: 'ab12cd34', catalogue_version: '2026Q3-0.1' },
                    status: 'pending', repeat_count: 0 }];""")
                page2 = ctx.new_page()
                page2.goto(f"http://127.0.0.1:{port}/index.html#proposals")
                page2.wait_for_selector("main")
                page2.wait_for_timeout(500)
                page2.screenshot(path=str(out / f"proposals-sample-{scheme}.png"))
                page2.locator("button", has_text="Accept once").first.hover()
                page2.wait_for_timeout(300)
                if errors:
                    print(f"[{scheme}] console/page errors:")
                    for e in errors:
                        print("   ", e)
                ctx.close()
            browser.close()
    finally:
        srv.shutdown()

    # sanity: the sample run's headline numbers, so a reader can check them against the shots
    d = json.loads(run_json)
    t = d["totals"]
    print(f"prior {t['prior_nav']} -> proposed {t['proposed_nav']}  dispositions {t['dispositions']}")


if __name__ == "__main__":
    main()
