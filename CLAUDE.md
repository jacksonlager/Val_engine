# Val_engine — orientation for Claude Code

A quarterly valuation engine for a VC portfolio: it rolls the book forward through the
quarter's activity feed, proposes a mark for every position, and decides which ones a human
must look at before the quarter can be published. Built as an interview exercise for Human
Capital; the reviewer is a CFO, not an engineer.

`README.md` is the full tour. This file is the short version plus the rules that are easy to
break without noticing.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate   # .venv already exists on this machine
pip install -e ".[dev,live]"
hc-valuation run                                     # dashboard + API on 127.0.0.1:8765, opens a browser
```

Python 3.11+. If `pip install -e .` fails with "editable mode currently requires a
setuptools-based build", make the venv with `python3.12 -m venv .venv` (see README §Install).

## Test

```bash
python3 -m pytest -q tests/          # 1,047 tests, ~90s — run the whole suite, it is fast enough
python3 -m pytest -q tests/stress/   # 213 adversarial tests on the escalation controls
```

Everything must pass before a commit. Two suites are load-bearing:

- `tests/test_golden.py` pins all 100 companies against `tests/fixtures/golden_q3_2026.json`.
  A diff here means the numbers moved. If the change was intended, regenerate with
  `python3 scripts/regen_golden.py` and **say in the commit message why the book moved**. If it
  was not intended, it is a bug — do not regenerate to make the failure go away.
- `tests/test_determinism.py` runs the engine twice and compares. Anything that reads the
  clock, the filesystem or the network from inside the engine breaks it.

## Frontend

```bash
cd frontend && npm install && npm run build     # -> src/hc_valuation/api/static
cd frontend-exec && npm install && npm run build # -> src/hc_valuation/api/static_exec
```

`npm run build` type-checks first and fails on a type error. Node 20+. Python serves whatever
is in those two directories, so **rebuild after every frontend change** or you will be testing
the old bundle. Each build writes a new hashed filename; delete the superseded pair rather than
letting them pile up.

To see a change: rebuild, restart `hc-valuation run`, hard-reload the browser.

## Layout

```
src/hc_valuation/
  engine/          the pure core — models, marking rules, readiness, exceptions, run
  connectors/      EDGAR + Yahoo market data, prices, the live/fixture providers
  ingest/          workbook reader and the X-9xx integrity checks
  api/             FastAPI app, publish gate, and the built frontends under static/
  recommend.py     the two-level recommender (per finding, and one step per position)
  cli.py           hc-valuation run | build | validate | export | rules | publish |
                   market | history | recommend | next-policy | version
rules/
  2026Q3.yaml      every threshold and switch — the policy, nothing else
  rationale.yaml   the rule catalogue: what each rule is for and why that severity
data/
  overrides.yaml   the E-01 committee ledger, append-only
  sample_run.json  what the static export and the screenshots read
frontend/          the review tool (React + TS + Vite + Tailwind + Recharts)
frontend-exec/     the executive dashboard, a separate build
docs/              how-it-works.md is the plain-English guide; architecture, policy, market-feed
```

## The invariants — break these and the design is gone

**1. The engine is pure.**

```python
run_valuation(portfolio, activity, market, overrides, config, *, validation=(), ...) -> ValuationRun
```

No file reads, no network, no `datetime.now()`. The measurement date comes from config; market
data arrives as an already-fetched value object. All I/O lives in `pipeline.py::execute` and the
connectors. This is what makes the determinism test and the golden fixture possible. **If a
change makes this function need I/O, the change is wrong.**

**2. Never fabricate market data.** If a feed fails, the run says so and the affected position
goes Blocked. A plausible-looking number invented to make a screen render is the worst possible
bug in this codebase. The same goes for filling a gap in the sample data.

**3. Never handle the API key.** The Claude recommender is off unless `ANTHROPIC_API_KEY` is set,
and Jackson sets it himself. Do not read it, echo it, write it to a file, or put it in a command
you print. Without it the engine falls back to the policy default and states the reason on the
card — that is correct behaviour, not a failure to fix.

**4. An unresolved material issue cannot become an approved mark.** Readiness (Blocked / Needs
Review / Ready) gates publication. A missing input (`MISSING_INPUT_RULES`) blocks until a decision
names the rule. Two REVIEW findings from different families escalate to BLOCK. An AI suggestion
chooses among the engine's candidates — it never invents a number and never bypasses a control.
`tests/stress/` exists to keep this true; if a change makes one of those tests fail, the change
is almost certainly wrong.

**5. Display text and engine values are different things.** `frontend/src/lib/labels.ts` is the
one place where enums and snake_case keys become words a CFO reads. The *values* still drive the
logic and the `disp-*` / `rd-*` CSS classes, so never rename a value to make a screen read better
— add or fix a label. Rule ids (X-101, M-080) stay visible in evidence, chips and tooltips; they
do not belong in a headline, a button or a dialog title.

**6. Claude only adds.** The same rule binds all three uses (note reader, E-09 adjudicator, recommender): a model may explain, classify, draft a rule or pick among the engine's priced options, never produce a number, lower a severity or unblock a position. The note reader: Claude reads each activity row's free text against the case
catalogue (`src/hc_valuation/notes/catalogue.py`) and the engine turns the reading into review
findings (X-130 what no rule applied, X-131 a conflict with a column, X-126 supersedes the tab,
X-132 not read). A reading never produces a number, never lowers a severity, never removes a
finding, never runs inside `run_valuation` (readings are inputs, cached under `data/note_reads/`).
`HC_NOTE_READER=off` pins it off; the test suite pins it off and hides the key. A new situation
goes in the catalogue with a definition, terms and the rule that handles it, then
`python3 scripts/case_catalogue.py` regenerates `docs/case-catalogue.md`.

## Conventions

- Marks are `$M`. Tables 2 decimals, tiles 1, percentages 1 — via `frontend/src/lib/format.ts`.
- Say "Portfolio fair value", not "NAV", wherever the total is only the company marks.
- A new threshold goes in `rules/2026Q3.yaml`, never hard-coded in a rule function.
- A new rule needs an entry in `rules/rationale.yaml` (`why_flag` and `why_severity`), and
  `tests/test_rationale.py` enforces that.
- Comments explain *why*, not what. The code says what.

## Verifying a UI change

Do not trust the diff. Rebuild, serve, and look:

```bash
hc-valuation run --port 8790
```

then drive it with Playwright (already installed; `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`)
at 1440px, screenshot the affected card or view, and check the console is clean. Reading the
rendered `document.body.innerText` and grepping it for snake_case, raw enums, CLI flags and repo
paths is a cheap way to catch machine vocabulary leaking onto a reviewer's screen.

## Test quarters and ledgers (added by the hardening pass — see HARDENING_REPORT.md)

- `data/overrides.yaml` and `data/published/` are the **committee's** ledger. Anything that is not a real
  committee decision goes to its own ledger: `--ledger-dir <dir>` (every engine command) or
  `RunPaths.default(ledger_dir=…)` moves overrides, proposals, precedent and published snapshots together.
  A trial decision clicked into the real ledger and committed once cost 34 red tests (D-0 in the report).
- `data/quarters/synthetic/` is the synthetic test chain (Q4 2026 → Q2 2027) with its own `ledger/`;
  `scripts/synthetic_chain.py` builds and drives it; expectations live beside it and are committed before a
  run. Every workbook there says SYNTHETIC in its name and first sheet. Never write to `Assignment context/`.
- `--provider synthetic` reads `data/synthetic_market/<as_of>.yaml` (invented multiples for dates no feed can
  price; `scripts/make_synthetic_market.py`). It labels everything `synthetic:` and never calibrates a mark.
  The served dashboard's Workbook select (`GET /api/workbooks`, `POST /api/workbook`) picks the policy,
  ledger and provider per workbook.
- Threshold comparisons go through `marking.ratio` / `ratio_change`; a figure exactly at a policy line is
  *at* it, not beyond it (`tests/test_threshold_boundaries.py`).

## State

Branch **`v1-refresh`**. `main` holds an earlier full-redesign UI that was set aside — work
continues on `v1-refresh`. The market cache under `~/.cache/hc-valuation` is live data fetched
from EDGAR and Yahoo; refresh it with `hc-valuation market --provider live --refresh`.
