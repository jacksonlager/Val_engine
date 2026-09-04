# training/ — the hardening corpus and gauntlet

This is **not machine-learning training data**. It is a regression corpus: synthetic
workbooks that exhaust the VC event types and the ways a real quarterly file arrives dirty,
each paired with the outcome the engine must produce, run as a permanent gauntlet. It is
what makes the engine safe to point at next quarter's file. The contract every workbook
encodes is `SPEC.md`; the governing principle is *an unhandled case blocks, nothing is
guessed silently*.

```
training/
  SPEC.md            the contract (event taxonomy, normalization ids, new rules, this corpus)
  README.md          this file
  generate.py        seeded, deterministic: scenarios/*.yaml -> workbooks/*.xlsx
  run_gauntlet.py    runs every scenario, checks expectations, writes report.md + report.json
  scenarios/*.yaml   one scenario per workbook: base book, mutations, activity rows, expectations
  workbooks/*.xlsx   generated and committed, so a reviewer can open exactly what the engine saw
  report.md          the last run (a table per scenario: check, expected, actual, ✓/✗)
  report.json        the same, machine-readable
tests/test_gauntlet.py   one pytest per scenario; the whole corpus is part of `pytest`
```

## Run it

```bash
python training/generate.py                 # rebuild every workbook (or name one: 06_value_formats)
python training/run_gauntlet.py             # run everything; exit 1 if any check fails
python training/run_gauntlet.py 02_event_type_typos 20_garbage_csv
pytest tests/test_gauntlet.py               # the same checks, one test per scenario
```

Each scenario runs in isolation: a temp copy of `rules/` (plus a generated `2026Q4.yaml`
inheriting `2026Q3.yaml` when the policy is 2026Q4 — never written into the real `rules/`),
a copy of the workbook, no override ledger, no proposals, adjudication off, the stub
market-data provider, `generated_at` pinned to the policy's measurement date. The runner
never crashes on a failing scenario: an `IngestError` is the expected result for
`ingest_ok: false`; any other exception is recorded as a failure carrying the traceback's
last line — an unexpected exception is exactly what this corpus exists to catch.

## Reading report.md

The top table is one line per scenario (pass / fail / crash, checks passed, seconds), then a
**Failures** list — one line per failed check: scenario, check, expected vs actual — then a
section per scenario with every check. The one-line summaries the runner prints are the
same as the top table. `report.json` carries identical content for tooling.

A check name reads `Company: what` for per-company checks (`Solvantra: proposed mark`,
`Kilnbrook: flag X-107 present`), `validation …` for validation-issue checks, and
`totals.*` / `manifest.*` / `snapshot: *` for run-level checks.

## Scenario YAML

```yaml
name: 02_event_type_typos
description: what this workbook exercises, in one paragraph
base: HC_Mock_Portfolio_Data.xlsx     # or "snapshot:2026Q3": the Q4 book emitted from a fresh Q3 run
policy: 2026Q3                        # rules/<policy>.yaml (2026Q4 is generated at run time)
workbook: 12_listed_carry.xlsx        # optional: share another scenario's workbook
synthesize: { companies: 1000, events: 120, seed: 19 }   # 19_big_book only
garbage: csv | no_portfolio | headers_only | empty       # 20_* only
sheet_names: { portfolio: Book, activity: "Q3'26 Activity" }
extra_sheets: [ { name: "Activity Q3 2026", copy_of: activity } ]
header_mutations: { activity: { "Event": "Event Type" }, portfolio: { "Prior Mark ($M)": "Carrying Value" } }
drop_columns:     { activity: [Notes] }
extra_columns:    { activity: { Source: "Board deck" } }
column_order:     [Company, Event, Date, ...]            # activity tab, original header names
structure:                                               # per tab, or flat = activity tab
  activity:  { title_rows: 2, titles: [...], blank_rows_every: 3, totals_row: true, trailing_note: "Source: …" }
portfolio_mutations:                                     # by company; an unknown company with a full row is appended
  Drayvenn: { Stage: Public }
  Aravine Labs: { Sector: ..., Fund: ..., ... }
portfolio_duplicates: [Rivenmark]                        # paste a book row twice (27_portfolio_edges)
policy_overrides: { custom_rules: [ ... ] }              # a scenario-local child policy inheriting `policy` (31_*)
market: { drop_quotes: [Drayvenn] }                      # remove quotes after the connectors assemble them
activity:                                                # replaces the base activity tab, values written verbatim
  - { date: 2026-07-06, company: "Dovelane Systems", event: "Priced Equtiy Round", detail: "Series B",
      value: "$103.8M", hc_investment: null, ownership_after: "5.5%", proceeds: null, notes: "…" }
  - { ..., notes: { repeat: "lorem ", times: 2000 } }    # a cell value built by repetition (30_long_notes)
expect: ...
```

Activity row keys are the attribute names from `ingest/schema.py` (`date, company, event,
detail, value, hc_investment, ownership_after, proceeds, notes`); any other key becomes an
extra column. Values land in the cell exactly as written: a quoted `"2026-07-06"` is a
string, an unquoted `2026-07-06` is an Excel date, `46266` is an Excel serial, `"$28.2M"`
is text. Mutation order is fixed: portfolio_mutations → activity rows → header mutations →
structure → sheet names.

### Expectations

```yaml
expect:
  ingest_ok: true | false | any        # false: must raise IngestError; any: either outcome is checked
  error_contains: ["csv", "zip"]       # for a raised IngestError: any one substring, case-insensitive
  no_crash: true
  max_seconds: 15
  validation_ids: { must: [X-912], must_not: [X-909] }
  validation_must:                     # ≥ 1 matching issue (or exactly `count`)
    - { id: X-914, company: Quillshade, contains: "Aravine Labs", blocking: true, count: 1 }
  validation_must_not: [ { id: X-907, company: "Kolvani Health" } ]
  validation_blocking: false           # whether any blocking validation issue exists
  anywhere_must: [X-918]               # id present as a validation issue OR as a flag on any company
  totals: { events: 8, positions: 100, dispositions: { BLOCK: 1, ... } }
  manifest: { quarter_label: "Q4 2026" }
  snapshot: { next_label: "Q1 2027", activity_sheet: "Q1 2027 Activity", portfolio_rows: 100 }
  companies:
    Dovelane Systems:
      disposition: MONITOR             # or disposition_in: [CLEAR, MONITOR]
      rules: [M-010]                   # the exact audit chain; or rules_contains / rules_must_not
      proposed: 5.709                  # with tol (default 0.01)
      flags_must: [X-103]
      flags_must_not: [M-999]
      status: Acquired | stage: Public | listed: true | fv_level: 1 | fund: "Fund III" | sector: Healthcare
      realized_quarter / ownership_after / invested_after / note_at_cost / equity_mark / latest_post_money: number
      open_items_must: [convertible_note, { kind: term_sheet, age_quarters: 1, escalated: true }]
      open_items_must_not: [pending_acquisition]
      open_items_count: 0
      alternative_marks: { at_implied_price: 4.27 }
    Nonesuch Ventures: { present: false }
```

`totals.events` is the number of rows the ingest layer produced (the workbook is re-read
with the run's config), so a skipped `Total` row or a blank row must not count.

Two semantics the checker takes a position on, because the SPEC's principle demands it:

* **A row that blocks blocks its position.** Where a validation issue is blocking (X-902,
  X-903 > 100 points, X-914, X-920, an uncoercible cell), the company's disposition must be
  BLOCK and the engine must not have booked a number it could not compute. A run-level block
  with a CLEAR position carrying 150 × post is the failure mode this corpus exists to catch.
* **SPEC §2.3 vs §2.5 on uncoercible cells.** §2.3 says X-902-style BLOCK naming the cell,
  §2.5 says hard `IngestError`. `ingest_ok: any` accepts either — what it rejects is a silent
  blank (13b, 16b).

## Adding a scenario

1. Write `scenarios/NN_name.yaml`. Choose companies that are CLEAR at carry (see the base
   run) so the disposition you assert is the rule's own, and compute the mark from the row:
   `ownership_after × post` for rounds, 0 for exits and shutdowns, `own_after × last_round_post`
   for a secondary at the default basis, `prior + hc_investment` for a funded note,
   `ownership × deal × 0.90` for an announced deal — every formula is in
   `docs/valuation-policy.md`. "Did not crash" is the floor, not the bar.
2. `python training/generate.py NN_name` and open the workbook: the dirty representation
   you asked for must be visibly in the cells.
3. `python training/run_gauntlet.py NN_name`, read the failure lines, and decide whether the
   engine or the expectation is wrong. Commit the YAML and the workbook together.

A scenario that needs its own workbook variant (two activity-like sheets, a quote removed)
gets its own file with a letter suffix (`09e_…`, `12b_…`); the pytest id is the file stem.
