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

`hc-valuation run --watch` keeps the run current: the server polls the workbook, the policy
folder, the override and precedent ledgers, the carried open items and the proposals for
changes and recomputes on any of them, and the open dashboard reloads itself when the run
changes — drop a new workbook in place and the page you have open shows the new run.

> **If `hc-valuation` is not on your PATH** (macOS Python installers often do not add the
> scripts directory), `python3 -m hc_valuation <command>` is the same program:
> `python3 -m hc_valuation run`, `python3 -m hc_valuation build --out dist/`, and so on.

No server wanted? Build the deliverables into a folder and open the report:

```bash
hc-valuation build --out dist/
open dist/report.html                                  # single self-contained file
```

`build` writes `report.html`, `valuation_Q3_2026.xlsx` (Summary, Marks, Exceptions, Audit
Trail, Fund Rollup, Open Items, Validation, Alternatives), the same tables as CSV
(`marks`, `exceptions`, `audit_trail`, `open_items`, `alternatives`), `mark_history.csv`
(the per-company quarter-over-quarter archive), `run.json` (the full run), `manifest.json`,
and the next-quarter input workbook `portfolio_Q4_2026.xlsx` with its `open_items_carry.yaml`
sidecar. The Audit Trail carries a `Portfolio Row` and an `Input Cells` column
(`post_money='Q3 2026 Activity'!E14; prior_post_money=Portfolio!H21`), so any number in
Marks traces to the workbook cell it was read from.

The full command list is `run | build | validate | export | rules | publish | market |
history | next-policy | version`: `validate` (ingest + integrity checks only; exit 1 if
anything blocks), `export` (workbook + CSVs only), `rules` (the rule catalogue), `publish`
(freeze the run for the executive dashboard under a named approver), `market` (the sector
comps feed report), `history` (the mark archive per company, `--company` for one),
`next-policy` (the next quarter's rules file), `version`. Every command accepts
`--input <workbook>` and `--policy <rules file>`; `hc-valuation --help` lists the rest. The
activity tab's quarter must match the policy's quarter or the run blocks (X-922) —
`next-policy` writes the matching file.

## What you are looking at

**The queue.** Every company lands in one of four dispositions. `BLOCK` means the engine
has produced a number it will not let anyone book without a decision — an IPO price
source to confirm, a down round whose headline post-money is only an upper bound, an
announced deal whose close probability needs ratifying, an event type the engine does not
recognise. `REVIEW` is a single judgment call; two independent REVIEW families on one
company escalate to BLOCK. `MONITOR` is information; `CLEAR` had no activity and no
signal. On the Q3 book that is 7 BLOCK / 20 REVIEW / 39 MONITOR / 34 CLEAR. Exception
rules only ever add flags: no flag has changed a mark, and none can. Every BLOCK and
REVIEW flag carries an imperative action, two or three scannable points, and one to three
priced suggestions (ratify, hold the prior mark, the full deal value, cost, an alternative
mark). One of them is put forward first as the **recommendation**: by default the rule's own
policy default; with `recommendation.provider: claude` in the policy (or `--recommender claude`)
Claude chooses among the engine's priced options for that company's facts and writes the
sentence and two reasons — it can never propose a number of its own, the choice is validated
against the candidates, and every answer is cached under `data/recommendations/` so reruns are
deterministic and offline (`pip install -e ".[adjudication]"`, set `ANTHROPIC_API_KEY`, run
`hc-valuation recommend` once, commit the folder). Accepting a recommendation, or any other
option, records an ordinary override under a named approver.

**The audit chain.** A mark is not a value, it is a list of steps. Each `MarkStep` records
the rule that fired, its version, every input it read, the prior and new value, a
one-sentence rationale and the activity-tab row it came from. `proposed_mark` is asserted
equal to the last step's `new_value`; the review table is that chain rendered. Companies
with no activity carry an explicit `M-000` step rather than silence.

**Overrides.** The committee books a different number by appending to
`data/overrides.yaml` (or `POST /api/overrides` from the dashboard) with a reason and an
approver. The engine keeps `proposed_mark` untouched, sets `booked_mark`, appends an
`E-01` step naming the approver, and flags the override for re-confirmation if the
proposal it was recorded against has since moved. The decision records — `data/overrides.yaml`,
`data/precedent.yaml`, `data/proposals/*.json` and `data/published/` — are versioned in git on
purpose, so a booked number always travels with the decision behind it; only the superseded
publish copies (`data/published/history/`) and the emitted `open_items_carry.yaml` stay local.

**Vendor signals.** A company's detail panel also shows a "Vendor signals" card
(`GET /api/signals`): the Foresight-shaped operating metrics beside the workbook's own, with
any gap above 10% highlighted, and the quarter's AlphaSense-shaped news with sentiment. Both
are fixtures in this tree, and neither ever touches a mark, a flag or a disposition — the
card exists so a restatement or a headline is seen by the reviewer, not booked by the engine.

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
rules/comps_baskets.yaml     which public companies stand for each workbook sector (the live comps feed)
data/                        input workbook, override ledger, proposals, vendor-shaped mock responses,
                             market_cache/<as_of>/ (trimmed live-feed extracts after a real run)
src/hc_valuation/
  config.py                  rules.yaml -> RuleConfig (strict; unknown keys raise; `inherits` supported)
  ingest/                    workbook -> snapshot + feed (activity tab found by pattern), normalize.py
                             (typos, synonyms, units, headers — every correction recorded), X-9xx checks
  engine/                    PURE: registry, marking rules M-0xx, exception screens X-1xx..4xx,
                             overrides, open items, rollup, sensitivity, run_valuation()
  connectors/                market data: protocols, vendor stubs, the live EDGAR + Yahoo/Stooq comps feed
                             (edgar.py, prices.py, stooq.py, cache.py, live.py) — docs/market-feed.md
  adjudication/              E-09 proposals for novel cases (runs after the engine, never inside it)
  export/                    review workbook, CSVs, next-quarter snapshot, single-file HTML report
  api/app.py                 FastAPI over the pipeline; api/static/ is the built review tool,
                             api/static_exec/ the built executive dashboard (served at /exec/)
  api/publish.py             the publish gate: freezes a run into data/published/ under a named approver
  api/history.py             the mark archive: booked marks per company per quarter, assembled from the
                             publish ledger, data/mark_history.yaml (backfill) and the current run
  api/signals.py             the vendor-signals card: Foresight-shaped metrics beside the workbook's,
                             AlphaSense-shaped news — context for the reviewer, never an input to a number
  api/exec_view.py           the executive view-model (bridge, movers, funds, decisions, risk watch)
  cli.py                     hc-valuation run | build | validate | export | rules | publish | market | history | next-policy | version
  __main__.py                python3 -m hc_valuation ... == hc-valuation ...
frontend/                    React + Vite source for the review tool (builds into api/static)
frontend-exec/               React + Vite source for the executive dashboard (builds into api/static_exec)
tests/                       golden file, determinism, rules, ingest, normalize, edge cases, connectors, market
                             feed, adjudication, export, api, cli, publish, history, flag points, suggestions, gauntlet
training/                    SPEC.md (the hardening contract), scenario corpus, workbook generator, gauntlet
docs/valuation-policy.md     the marking policy the rules implement
docs/architecture.md         the run as a diagram: feeds, triggers, the review and publish gates, what is stubbed
docs/market-feed.md          the live comps feed contract
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
pip install -e ".[dev]"             # adds pytest and httpx to the install above
pytest                              # 740+ tests (743 at the time of writing), ~25 s, no network
python training/run_gauntlet.py     # 44 dirty-workbook scenarios, 1,785 checks -> training/report.md
```

The golden test pins all 100 companies; the determinism test checks two runs serialise
identically; `test_coverage` asserts every event type in the workbook's Field Definitions
has a registered handler; the export test re-ingests the emitted next-quarter workbook and
requires zero blocking issues.

### Rebuilding the front ends

Not needed to run: both built bundles are committed. Only if you change the React source:

```bash
cd frontend && npm install && npm run build         # -> src/hc_valuation/api/static
cd frontend-exec && npm install && npm run build    # -> src/hc_valuation/api/static_exec
```

Node 20 or newer (Vite 5, TypeScript 5.9). `npm run build` type-checks first and fails on a
type error. Python serves whatever is in those two directories; restart `hc-valuation run`
after a rebuild.

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

## Mark history

Clicking a company in the review tool opens its detail panel, whose first card is a line
chart of the booked mark quarter over quarter (with the cost basis dashed underneath). The
engine itself never looks back — the archive is assembled at read time by `api/history.py`
from three places, and nothing on the chart is interpolated or invented:

- the **publish ledger** (`data/published/<quarter>.json`): one point per company for every
  quarter released to executives. Publishing a quarter is what extends the archive; nobody
  maintains it by hand;
- the **current run**: the workbook's `Prior Mark` fills the previous quarter when the ledger
  has no point for it, and this quarter is always the live booked mark (drawn hollow until a
  matching snapshot has been published);
- an optional **backfill file** (`data/mark_history.yaml`, shipped empty and documented
  inline) for the quarters before the engine's first run.

Every point says which of these it came from, and a disagreement between them (a published
mark that differs from the `Prior Mark` the next run started from; a live run that moved
after publishing) is noted on the point rather than hidden. `GET /api/history` serves the
archive, `build` inlines it into `report.html` and writes it as `mark_history.csv`, and
`hc-valuation history [--company X]` prints it.

## Live market data

The one external *market* input the engine reads is the sector public-comparable multiple
(`MarketData.comps`, with a monthly history) behind the X-401/X-402 screens in
`relative_to_comps` mode and the M-080 calibration alternative. By default it comes from
the PitchBook-shaped fixture and the manifest says `stub`. A free, keyless live source
fills the same slot honestly:

- **SEC EDGAR** (`companyfacts` XBRL API) for quarterly revenue, shares outstanding and
  net cash of the public companies in `rules/comps_baskets.yaml`, and **Yahoo Finance's
  public chart API** for their daily closes (keyless; undocumented but stable — it is what
  `yfinance` reads). Per constituent, per month: `EV = close × shares − net cash`,
  `EV / TTM revenue`; per sector, the median of the basket. The full contract — what is
  read, how a missing quarter or a multi-class filer is handled, and the exact JSON the
  review tool renders — is `docs/market-feed.md`.
- Run with `--provider live` (`hc-valuation run --provider live`, `build --provider live`)
  or `HC_MARKET_PROVIDER=live`. Requires the `live` extra: `pip install -e ".[live]"`.
- **Price source.** The price half is pluggable: `--price-source yahoo|stooq` on
  `hc-valuation market`, or `HC_PRICE_SOURCE` for every command, over
  `defaults.price_source` in the baskets file. Stooq is retained as the alternative, but it
  currently answers non-browser clients with a JavaScript browser-verification page (with
  HTTP 404), which the feed reports as such and does not attempt to bypass.
- **The cache.** Trimmed extracts land in `data/market_cache/<measurement date>/` (the
  directory exists only once a live run has been made); with a complete cache a run makes
  no network call and is deterministic offline, so commit the directory after a real run
  and a reviewer gets live-shaped data without a network. `--refresh-market` (or
  `market --refresh`) refetches; a partial cache fetches only what is missing.
- **`hc-valuation market [--provider live|stub] [--price-source yahoo|stooq] [--refresh] [--json]`**
  prints one line per sector (multiple, source, month, constituents ok/total) and the
  errors — a source-wide outage is one line, not one per ticker; `--json` dumps the
  `GET /api/market` payload. It exits 0 when the fixture answered — the fall-back is a
  reported condition, not a failure.
- **Honesty.** Every failure is caught per constituent and listed; a sector with fewer than
  `min_constituents` priced names keeps the fixture value and says so; if no sector reaches
  live the manifest says `stub`. Multiples are labelled `live:edgar+yahoo@YYYY-MM` (or
  `+stooq`) or `fixture:pitchbook@YYYY-MM` down to the sector.
- **SEC contact.** SEC's fair-access policy requires a `User-Agent` naming the app and a
  real contact e-mail: set `HC_SEC_CONTACT=you@yourfirm.com` before a live run (the default
  `valuation@example.com` is a placeholder SEC may block).
- **Replacing it with PitchBook.** A vendor connector is one class implementing
  `CompsProvider` and one `register_comps_provider("pitchbook", factory)` call in
  `connectors/__init__.py` — providers are a registry keyed by name, not an `if` chain.
  `--provider pitchbook` is registered and reports "not configured" until
  `PITCHBOOK_API_KEY` and `connectors/pitchbook.py` exist. The engine, the policy, the
  golden test and the review tool do not change.

## Boundaries

- **Synthetic tickers.** The IPO'd company is invented, so no live feed can price it. Its
  quote is seeded to the IPO print and labelled as such in the audit chain; the position
  blocks until a real measurement-date close is confirmed.
- **Live market data is optional.** The stub connectors are the default and the golden
  test runs against them. The live EDGAR + Yahoo feed is selected with `--provider live`
  without touching the engine, and falls back to the stub — labelled as such — whenever
  it cannot answer.
- **Adjudication is optional and never books a number.** It can be disabled in the policy
  file and the engine produces identical marks either way; an unhandled event stays
  blocked until a human decides.
- **Structure the schema cannot see.** Preference stacks, pay-to-play, escrow and
  holdbacks are not in the workbook. Rules that would need them (down rounds, closed
  exits with proceeds that do not tie) block or flag rather than guess.

## AI tooling, reuse and open-source

The rule set, the thresholds, the flag wording, the two front ends, the tests and the
gauntlet corpus, and the docs were drafted with Claude in agentic coding sessions, and the
build is agent-assisted: the phases in the build plan were implemented by coding agents
with a human gate at each phase (golden numbers, determinism, edge cases) before the next
began. Thresholds were tuned by running the exception screens over all 100 companies and
reading the resulting queue — the first cut flagged 58 of 96 active companies, which is
how it was caught and fixed. Nothing a model produces enters a booked mark: the one place
a model sits inside the product is the optional E-09 adjudicator, whose drafts are rules
for a human to promote, and the deterministic engine computes every value.
`docs/architecture.md` §12 has the specifics.

No prior code was reused. Open-source components: FastAPI, uvicorn, Typer, pydantic,
openpyxl, PyYAML, httpx (live feed) and the optional `anthropic` SDK (E-09) on the Python
side; React, Vite, TypeScript, Tailwind CSS, TanStack Table and Recharts in the front ends;
pytest for the tests and Playwright for the screenshot scripts.
