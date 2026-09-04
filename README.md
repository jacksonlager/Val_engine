# Val_engine — HC quarterly valuation engine

Rolls a venture portfolio forward through a quarter's activity feed, proposes a mark for
every position, and flags what a human must decide before anything is booked. Built for
the HC finance assessment against the synthetic 100-company workbook in `data/`.

The engine is deterministic and pure: the same workbook and policy file always produce
the same marks, the same queue and the same audit chain. Judgment lives in the policy
file and in the committee's override ledger, never in the code path that computes a number.

## Run it (Python 3.11+, nothing else)

```bash
git clone https://github.com/jacksonlager/Val_engine.git
cd Val_engine
python3 --version                                      # must be 3.11 or newer — see note below
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip                   # the pip bundled with older Pythons cannot do editable installs
pip install -e .
hc-valuation run
```

> **Python version.** macOS ships a system `python3` that is often 3.9 with pip 21.x; that
> combination fails `pip install -e .` with "editable mode currently requires a setuptools-based
> build". Install a current Python (`brew install python@3.12`, or python.org) and create the
> venv with it: `python3.12 -m venv .venv`. Upgrading pip inside the venv is always safe.

`run` computes the Q3 2026 valuation, starts a local server on http://127.0.0.1:8765 and
opens the review dashboard in your browser (`--no-browser` to skip that, `--port` to move
it). The dashboard bundle is committed under `src/hc_valuation/api/static/`, so no Node is
required; if it is absent the same URL serves a plain report page instead.

No server wanted? Build the deliverables into a folder and open the report:

```bash
hc-valuation build --out dist/
open dist/report.html                                  # single self-contained file
```

`build` writes `report.html`, `valuation_Q3_2026.xlsx` (Summary, Marks, Exceptions, Audit
Trail, Fund Rollup, Open Items, Validation, Alternatives), the same tables as CSV,
`run.json` (the full run), `manifest.json`, and the next-quarter input workbook
`portfolio_Q4_2026.xlsx` with its `open_items_carry.yaml` sidecar.

Other commands: `validate` (ingest + integrity checks only; exit 1 if anything blocks),
`export` (workbook + CSVs only), `rules` (the rule catalogue), `next-policy` (the next quarter's
rules file), `version`. Every command
accepts `--input <workbook>` and `--policy <rules file>`; `hc-valuation --help` lists the rest.

## What you are looking at

**The queue.** Every company lands in one of four dispositions. `BLOCK` means the engine
has produced a number it will not let anyone book without a decision — an IPO price
source to confirm, a down round whose headline post-money is only an upper bound, an
announced deal whose close probability needs ratifying, an event type the engine does not
recognise. `REVIEW` is a single judgment call; two independent REVIEW families on one
company escalate to BLOCK. `MONITOR` is information; `CLEAR` had no activity and no
signal. Exception rules only ever add flags: no flag has changed a mark, and none can.

**The audit chain.** A mark is not a value, it is a list of steps. Each `MarkStep` records
the rule that fired, its version, every input it read, the prior and new value, a
one-sentence rationale and the activity-tab row it came from. `proposed_mark` is asserted
equal to the last step's `new_value`; the review table is that chain rendered. Companies
with no activity carry an explicit `M-000` step rather than silence.

**Overrides.** The committee books a different number by appending to
`data/overrides.yaml` (or `POST /api/overrides` from the dashboard) with a reason and an
approver. The engine keeps `proposed_mark` untouched, sets `booked_mark`, appends an
`E-01` step naming the approver, and flags the override for re-confirmation if the
proposal it was recorded against has since moved.

**Proposals.** An unrecognised event type blocks the position (`M-999`). The optional
adjudication layer then drafts a *treatment proposal* — an analogue rule, a formula in a
restricted DSL, the facts still missing — for a human to accept, promote into the policy
file as a declarative rule, or reject. A proposal never contains a mark and never books one.

## Two sites: the review tool and the executive dashboard

`hc-valuation run` serves two front ends from one process.

**`/` — the review tool** is the back office's editing surface: the live run, the audit
chain, overrides, proposals. It changes every time someone records a decision.

**`/exec/` — the executive dashboard** is what the partners and the investment committee
open. It never reads the live run. It reads only a **published snapshot**, frozen by a named
person from the review tool's *Publish* button (or `hc-valuation publish --approver "…"`).
A run with open BLOCK positions publishes as **PROPOSED** and the page says how many
decisions are still owed; it becomes **FINAL** only when every block has been resolved.
Re-publishing replaces the snapshot and keeps the previous one under
`data/published/history/`, so what executives were shown is itself auditable.

The executive page covers the September 30 marks, the quarter-over-quarter bridge by
driver (reconciled to booked NAV), largest movers, the exception queue with each decision
stated as an imperative, fund TVPI / DPI / RVPI, composition, a risk watch (short runway,
revenue contraction, stale marks), the ±20% multiple sensitivity, open items, and full
provenance. `hc-valuation publish --out dist/` also writes `exec_report.html`, a single
self-contained file for the IC pack.

## Repository layout

```
rules/2026Q3.yaml            the policy: every threshold, the quarter window, the schema pattern
data/                        input workbook, override ledger, proposals, vendor-shaped mock responses
src/hc_valuation/
  config.py                  rules.yaml -> RuleConfig (strict; unknown keys raise; `inherits` supported)
  ingest/                    workbook -> snapshot + feed (activity tab found by pattern), normalize.py
                             (typos, synonyms, units, headers — every correction recorded), X-9xx checks
  engine/                    PURE: registry, marking rules M-0xx, exception screens X-1xx..4xx,
                             overrides, open items, rollup, sensitivity, run_valuation()
  connectors/                market data: protocols, vendor stubs, one optional live feed
  adjudication/              E-09 proposals for novel cases (runs after the engine, never inside it)
  export/                    review workbook, CSVs, next-quarter snapshot, single-file HTML report
  api/app.py                 FastAPI over the pipeline; api/static/ is the built review tool,
                             api/static_exec/ the built executive dashboard (served at /exec/)
  api/publish.py             the publish gate: freezes a run into data/published/ under a named approver
  api/exec_view.py           the executive view-model (bridge, movers, funds, decisions, risk watch)
  cli.py                     hc-valuation run | build | publish | validate | export | rules | next-policy | version
frontend/                    React + Vite source for the review tool (builds into api/static)
frontend-exec/               React + Vite source for the executive dashboard (builds into api/static_exec)
tests/                       golden file, determinism, rules, ingest, edge cases, export, api, cli, gauntlet
training/                    SPEC.md (the hardening contract), scenario corpus, workbook generator, gauntlet
docs/valuation-policy.md     the marking policy the rules implement
```

## The policy

`rules/2026Q3.yaml` holds every number the engine uses — staleness months, growth and
runway thresholds, the announced-deal close probability, the secondary basis, the IPO
price source, the escalation count. There is no numeric threshold in the code. Changing
a value is a policy change: bump `policy_version`, and the golden test fails with a
readable diff until you regenerate it on purpose (`scripts/regen_golden.py`). A later
quarter's file can `inherits: 2026Q3` and override only what moved; rules carry an
`effective_from` date so a Q4 rule never rewrites a Q3 re-run.

## Tests

```bash
pip install -e ".[dev]"
pytest                              # 671 tests
python training/run_gauntlet.py     # 44 dirty-workbook scenarios, 1,785 checks -> training/report.md
```

The golden test pins all 100 companies; the determinism test checks two runs serialise
identically; `test_coverage` asserts every event type in the workbook's Field Definitions
has a registered handler; the export test re-ingests the emitted next-quarter workbook and
requires zero blocking issues.

`training/` is the hardening corpus: a generator that writes deliberately dirty workbooks
(typos, synonyms, `$28.2M` in a number cell, headers on row 4, euro figures, 150%
ownership, a refused row next to an applied one, 500-company books, a rolled-forward Q4
run) and a gauntlet that checks every one against hand-computed expectations. The
contract it enforces is `training/SPEC.md`; its first principle is that **a cell the
engine cannot read never becomes a number** — the row is recorded as not applied, the
position blocks (X-900), and the flag names the cell to fix. The gauntlet is part of
`pytest` (`tests/test_gauntlet.py`), so a future rule change that breaks any scenario
fails the build.

## Refreshing next quarter

1. Take `dist/portfolio_Q4_2026.xlsx` from the previous `build` (booked marks are now
   `Prior Mark`, ownership / invested / realized are post-activity, the activity tab is
   empty and named for the new quarter) — or drop in a fresh workbook in the same schema.
2. Fill the `Q4 2026 Activity` tab. The sheet is located by pattern, so the name just has
   to look like `Qn YYYY Activity`; headers, event names and company names are matched
   with tolerance and every correction is recorded (X-911…X-920).
3. Keep `dist/open_items_carry.yaml` beside the workbook (or copy it to
   `data/open_items_carry.yaml`) so unresolved notes, pending deals and lock-ups age
   instead of being forgotten, and so marks the prior quarter deliberately set away from
   ownership × post-money (a note at cost, a weighted pending deal) are explained rather
   than blocked.
4. `hc-valuation next-policy` writes `rules/2026Q4.yaml` — `inherits: 2026Q3` with only the
   quarter window changed (the year-end rollover to `2027Q1` is parsed, not typed). Edit it
   only for thresholds that moved, and bump `policy_version` when you do.
5. `hc-valuation validate --input <file> --policy rules/2026Q4.yaml`, then `run` or `build`.

## Boundaries

- **Synthetic tickers.** The IPO'd company is invented, so no live feed can price it. Its
  quote is seeded to the IPO print and labelled as such in the audit chain; the position
  blocks until a real measurement-date close is confirmed.
- **Live market data is optional.** The stub connectors are the default and the golden
  test runs against them. A live feed can be selected with `--provider` without touching
  the engine.
- **Adjudication is optional and never books a number.** It can be disabled in the policy
  file and the engine produces identical marks either way; an unhandled event stays
  blocked until a human decides.
- **Structure the schema cannot see.** Preference stacks, pay-to-play, escrow and
  holdbacks are not in the workbook. Rules that would need them (down rounds, closed
  exits with proceeds that do not tie) block or flag rather than guess.

## AI tooling

The rule set and the thresholds were drafted against this dataset with Claude, and the
build is agent-assisted: the phases in the build plan were implemented by coding agents
with a human gate at each phase (golden numbers, determinism, edge cases) before the next
began. Thresholds were tuned by running the exception screens over all 100 companies and
reading the resulting queue — the first cut flagged 58 of 96 active companies, which is
how it was caught and fixed. Nothing a model produces enters a booked mark: proposals are
rules for a human to promote, and the deterministic engine computes every value.
