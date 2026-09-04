# Hardening contract — the event taxonomy, the normalization rules, and the IDs everyone uses

This is the single contract three work packages build against: **ingest hardening** (A),
**new marking rules** (B), and the **scenario corpus + gauntlet** (C). Nothing in here is
optional; if a package finds the contract wrong it says so in its report rather than
quietly diverging.

`training/` is a *hardening corpus*: synthetic workbooks that exhaust the VC event types and
the ways a real file arrives dirty, each with expected outcomes, run as a permanent
regression gauntlet. It is not ML training; it is the thing that makes the engine safe to
point at next quarter's file.

The governing principle is unchanged from the policy: **an unhandled case blocks; nothing
is guessed silently.** Every correction the ingest layer makes is recorded as a validation
issue with the original text, so a reviewer can see what was read as what.

---

## 1. Canonical event types

The eight that exist today, unchanged:

| Canonical | Rule |
|---|---|
| `Priced Equity Round` | M-010 / M-011 / M-012 |
| `Convertible Note` | M-060 |
| `IPO` | M-040 |
| `Acquisition (Closed)` | M-020 (M-024 when consideration is stock) |
| `Acquisition (Announced)` | M-050 |
| `Shutdown` | M-021 |
| `Secondary Sale` | M-030 |
| `Term Sheet Signed` | M-070 |

Eight new canonical types (package B implements the rules; A's normalizer maps to them):

| Canonical | Rule | Meaning |
|---|---|---|
| `Secondary Purchase` | M-031 | HC **buys** more of an existing position from another holder |
| `Distribution` | M-022 | Cash to HC with no change in the stake: dividend, escrow release, earn-out, holdback, milestone |
| `Ownership Adjustment` | M-013 | Ownership changes with **no price event**: warrant exercise, option-pool expansion, cap-table restatement |
| `New Investment` | M-014 | First check into a company; may or may not already be a row in the Portfolio tab |
| `Acquisition (Terminated)` | M-051 | A previously announced deal fell through |
| `Note Repaid` | M-061 | A bridge note redeemed in cash rather than converted |
| `Bankruptcy (Chapter 11)` | M-025 | Reorganisation; going concern; **not** terminal |
| `Direct Listing` | M-040 | Same treatment as IPO |

Not events, but must be handled: a **listed position with no event** re-marks to the
measurement-date quote (M-041, carry side). A **SAFE** is a `Convertible Note` (M-060; cap
parsed from "post-money cap $X" / "valuation cap $X" / "$X cap").

### 1.1 Synonym table (A implements; exact after case/whitespace/punctuation folding)

Folding = lowercase, collapse whitespace, strip trailing/leading punctuation, replace
`–`/`—` with `-`, drop content in trailing parentheses *unless it distinguishes closed vs
announced* (e.g. "Acquisition (Closed)" keeps its qualifier; "IPO (Nasdaq)" drops it).

```
Priced Equity Round      ← priced round | equity round | priced equity | financing round | equity financing |
                           series seed | series a | series a extension | series b … series f | seed round | seed |
                           series a (recap) | pro rata | follow-on | insider round | up round | down round | recap | round
Convertible Note         ← note | convertible | bridge | bridge note | bridge loan | convertible bridge | safe |
                           post-money safe | pre-money safe | convertible security
IPO                      ← initial public offering | ipo | listing | public listing | listed | went public
Direct Listing           ← direct listing | direct list
Acquisition (Closed)     ← acquisition closed | acquired | exit | exit closed | m&a closed | sale of company | sold |
                           acquisition - closed | acquisition: closed | acqui-hire | acquihire | trade sale | merger closed
Acquisition (Announced)  ← acquisition announced | announced acquisition | definitive agreement | signed definitive agreement |
                           pending acquisition | acquisition pending | acquisition - announced | merger announced | loi signed (acquisition)
Acquisition (Terminated) ← acquisition terminated | deal terminated | deal cancelled | deal canceled | acquisition withdrawn |
                           deal fell through | merger terminated
Shutdown                 ← shut down | shutdown | wind down | wound down | wind-down | ceased operations | dissolved |
                           dissolution | liquidation | liquidated | chapter 7 | bankruptcy (chapter 7) | abc |
                           assignment for the benefit of creditors | closed down | company closed
Bankruptcy (Chapter 11)  ← chapter 11 | bankruptcy (chapter 11) | reorganization | reorganisation | restructuring (chapter 11)
Secondary Sale           ← secondary | secondary sale | sold shares | partial sale | tender offer (sold) | tender (sold) | sale of shares
Secondary Purchase       ← secondary purchase | purchased shares | bought shares | tender offer (bought) | acquired shares from |
                           secondary buy
Term Sheet Signed        ← term sheet | term sheet signed | signed term sheet | ts signed | loi (financing) | loi signed (financing)
Distribution             ← distribution | dividend | cash distribution | escrow release | escrow released | holdback release |
                           earn-out | earnout | earn out | milestone payment | contingent consideration | deferred consideration
Ownership Adjustment     ← ownership adjustment | warrant exercise | warrants exercised | option pool expansion | pool expansion |
                           option pool top-up | cap table restatement | cap table correction | ownership correction | true-up
New Investment           ← new investment | initial investment | first investment | first check | new position | new portfolio company
Note Repaid              ← note repaid | note repayment | note redeemed | bridge repaid | loan repaid
```

Bare "loi" is ambiguous (acquisition vs financing) → **X-914 block**, never guessed.

### 1.2 Typo tolerance (A implements)

After folding, if the text is not an exact synonym, compare to every canonical name and
every synonym with Damerau-Levenshtein distance. Accept when **distance ≤ 2 AND the best
match is unique AND the text is ≥ 6 characters**. Record as **X-912**. If two candidates tie
within the threshold, or the text is short, raise **X-914** (BLOCK) and leave the raw type
for M-999. Examples that must resolve: `Aquisition (Closed)`, `Priced Equtiy Round`,
`Convertable Note`, `Shutdwon`, `Secondry Sale`, `Term Sheet Signd`, `IPO ` (trailing space).
Examples that must NOT resolve: `Acquisition` alone (closed or announced? → X-914),
`Round` alone is fine (synonym), `Sale` alone (secondary? exit? → X-914).

---

## 2. Ingest normalization contract (package A)

All corrections are **recorded, never silent**. New validation IDs, all non-blocking unless
stated:

| ID | Severity | Blocking | Meaning |
|---|---|---|---|
| X-911 | MONITOR | no | Header matched by normalization (case, whitespace, punctuation, typo ≤ 2, known alias) — message carries `original → canonical` |
| X-912 | MONITOR | no | Event type matched by synonym or typo tolerance — carries `original → canonical` and the method (`synonym` / `distance=1`) |
| X-913 | MONITOR | no | Company name matched by normalization (case, whitespace, `Inc.`/`Ltd`/`LLC`/`Corp` suffix, "formerly X", typo ≤ 1 on names ≥ 8 chars) |
| X-914 | BLOCK | yes | Ambiguous match: ≥ 2 candidates within tolerance for an event type, company or header; or a company typo-match that another book name extends by a word (`Aravin` → `Aravine` when `Aravine Labs` is also in the book). Names every candidate. Exact and case-folded matches are never second-guessed. |
| X-915 | MONITOR | no | Value coerced from a non-numeric representation — `"$28.2M"`, `"5.5%"`, `"(1.2)"`, `"28,200,000"`, a date string, an Excel serial — carries original and parsed |
| X-916 | REVIEW | no | Unit suspicion: ownership > 1 (treated as percentage points, divided by 100), post-money / deal value > 100,000 (treated as USD and divided by 1e6), proceeds/investment likewise. Carries the assumption. |
| X-917 | MONITOR | no | Structure tolerated: header found on row N ≠ 1, blank rows skipped, a `Total`/`Totals`/`Sum` row skipped, a trailing notes row skipped, merged title cell above header |
| X-918 | REVIEW | no | `New Investment` for a company not in the Portfolio tab — the engine creates the position (M-014); fund taken from Notes/Detail if it says `Fund I/II/III`, else `Unassigned` |
| X-919 | MONITOR | no | Activity sheet matched by a relaxed pattern (see 2.1) rather than the policy regex; carries the sheet name |
| X-920 | BLOCK | yes | Currency other than USD detected (`€`, `£`, `EUR`, `GBP`, `CHF`, `¥`, `JPY`, `CAD`, `AUD`) in a value cell, Detail or Notes. The engine is USD-only; the row blocks. |

**A row that blocks blocks its position (X-900).** Any row of the activity tab — or the
position's own Portfolio row — that carries a blocking issue is *recorded* in the audit
chain as not applied and the prior mark is carried; the engine never books a number from
a cell it could not read. The one exception is an unrecognised or ambiguous event type,
which still reaches M-999 so the adjudication proposal is raised. A refused close never
supersedes an announced deal. Money outside its domain is X-903 (a post-money or price
≤ 0, negative proceeds or investment); a `Latest Round` after the measurement date is
X-921; an event dated after the measurement date, or more than
`tolerances.late_event_grace_days` before the window, is X-905 BLOCK (inside the grace
period it is applied on REVIEW as a transaction missed at the last close); every copy of a
duplicated Portfolio row is X-906 BLOCK.

Existing X-901 (unknown company) stays BLOCK when no normalization resolves it and the
event is not `New Investment`. X-907 (activity on a terminal company) **must allow**
`Distribution` on an `Acquired` company (escrow release after an exit is normal) and
`Distribution` / `Note Repaid` on `Shut Down`.

### 2.1 Sheet discovery

Portfolio sheet: exact name from config, else case/whitespace-folded match, else any of
`portfolio | book | positions | holdings | portfolio tab`. Activity sheet: policy regex
first; then relaxed forms — `Q4 2026 Activity`, `Q4-2026 Activity`, `Q4'26 Activity`,
`4Q26 Activity`, `Activity Q4 2026`, `2026 Q4 Activity`, `Q4 2026 Events`, `Activity`,
`Events`, `Q4 Activity` — any sheet whose folded name contains `activity` or `events`. If
exactly one candidate, use it and raise X-919. If several, X-914 BLOCK naming them. The
quarter label is parsed from the sheet name when present, else taken from the policy.

### 2.2 Header discovery and aliases

The header row is the first row (scanning the first 10) in which ≥ 3 cells fold to known
column names. Rows above it are ignored (X-917). Header aliases, in addition to typo ≤ 2:

```
Company                         ← company name | portfolio company | name | co
Sector                          ← industry | vertical
Fund                            ← vehicle | fund name
Stage                           ← round | last round | latest stage
Status                          ← state
First Investment                ← initial investment date | first invested | entry date
Latest Round                    ← last round date | latest round date | last priced round
Latest Post-Money ($M)          ← post-money | post money | latest post money | post-money valuation | last post
Invested ($M)                   ← invested capital | total invested | cost | cost basis
Ownership (FD %)                ← ownership | fd ownership | fully diluted ownership | ownership % | fd %
Prior Mark ($M)                 ← prior mark | carrying value | fair value | fv | mark | current mark
Realized ($M)                   ← realized | realised | proceeds to date | distributions
MOIC (x)                        ← moic | multiple
ARR ($M)                        ← arr | revenue | annual recurring revenue | run-rate revenue
ARR Growth (YoY %)              ← arr growth | growth | yoy growth | revenue growth
Gross Margin (%)                ← gross margin | gm | gm %
Net Burn ($M/mo)                ← net burn | burn | monthly burn | burn rate
Cash ($M)                       ← cash | cash on hand | cash balance
Runway (mo)                     ← runway | runway months | months of runway
Headcount                       ← employees | fte | ftes | team size
Date                            ← event date | transaction date | close date
Event                           ← event type | activity | transaction | type
Detail                          ← details | description | round name
Post-Money / Deal Value ($M)    ← post-money | deal value | valuation | post money / deal value | value | post-money/deal value
HC Investment ($M)              ← hc investment | new investment | invested this round | hc participation | our investment
HC Ownership After (FD %)       ← ownership after | hc ownership after | fd % after | post-round ownership | ownership post
Proceeds to HC ($M)             ← proceeds | proceeds to hc | cash received | cash to hc | distributions
Notes                           ← note | comments | commentary | remarks
```

Column order never matters. Extra columns are recorded (X-910, existing). A required column
that cannot be found is still a hard `IngestError` naming the missing column and the
closest header seen.

### 2.3 Value coercion

Numbers: accept `28.2`, `"28.2"`, `"$28.2M"`, `"$28.2 M"`, `"28.2m"`, `"$28,200,000"` (→ 28.2 with
X-916 if > 100,000), `"(1.2)"` → −1.2, `"1.2%"` → 0.012, `"5.5 %"` → 0.055, `" 12 "`. Blank tokens
→ None: `""`, `"-"`, `"—"`, `"n/a"`, `"N/A"`, `"na"`, `"tbd"`, `"TBD"`, `"?"`, `"none"`, `"null"`.
Anything else non-numeric → X-902-style BLOCK naming the cell.

Percent fields (`Ownership (FD %)`, `HC Ownership After (FD %)`, `ARR Growth (YoY %)`,
`Gross Margin (%)`): a value > 1 and ≤ 100 is percentage points → divide by 100 with X-916;
> 100 → BLOCK.

Dates: Excel datetime, Excel serial number (int/float 20000..80000 → date), `YYYY-MM-DD`,
`MM/DD/YYYY`, `M/D/YY`, `DD-Mon-YYYY`, `Mon D, YYYY`, `YYYY/MM/DD`. Day-first vs month-first
ambiguity (`03/04/2026`) → parse month-first and raise X-915 noting the ambiguity. Anything
else → BLOCK naming the cell.

Company names: strip, collapse whitespace, unify curly quotes/dashes. Matching order: exact
→ folded exact → folded after stripping a corporate suffix (`Inc`, `Inc.`, `LLC`, `Ltd`,
`Ltd.`, `Corp`, `Corp.`, `Co.`, `plc`) → "X (formerly Y)" / "X, formerly Y" / "Y → X" where
either side matches → Damerau-Levenshtein ≤ 1 on names ≥ 8 chars, unique. Record X-913.
Two book names within tolerance → X-914.

### 2.4 Structure tolerance

Blank rows anywhere: skipped (X-917 once per sheet, with count). A row whose first cell folds
to `total`, `totals`, `sum`, `grand total`, `subtotal`: skipped (X-917). A trailing row with
text in the first cell and nothing else (a note): skipped (X-917). Merged cells in the header
area: the header discovery handles it. A sheet with a header and zero data rows: allowed
(empty quarter) — the run proceeds with every position on M-000 and the manifest says 0 events.

### 2.5 Hard failures (still `IngestError`, with a message that names the fix)

No Portfolio sheet by any rule; no activity sheet by any rule; required column missing;
zero portfolio rows; a value cell that is not numeric after coercion; a date that does not
parse; a workbook that is not a workbook (wrong extension, corrupt zip, CSV) — the message
must say what was found and what was expected, never a traceback.

---

## 3. New marking rules (package B)

All follow the existing conventions: `@rule(...)` registration with `effective_from =
2026-07-01`, a `MarkStep` per change, BLOCK/REVIEW flags carry an `action`, MONITOR flags
carry none. Rule ids and flag ids below are fixed.

| Rule | Event | Mechanics | Flag |
|---|---|---|---|
| **M-013** Ownership adjustment | `Ownership Adjustment` | `ownership = ownership_after`; `equity = ownership_after × latest_post`; `invested += hc_investment` (warrant strike); staleness clock unchanged | **X-110** REVIEW "Ownership moved from a% to b% with no price event — confirm the cap table." |
| **M-014** New investment | `New Investment` | If the company is in the book: `ownership = ownership_after`, `latest_post = value`, `invested += hc_investment`, `equity = own × post`, anchor = date, status Active. If not in the book: create the position (fund from Notes/Detail `Fund I/II/III` else `Unassigned`, sector from Detail if it matches a known sector else `Unclassified`, stage from Detail else `Unknown`) and raise X-918 | **X-120** MONITOR "New position entered at cost" — plus X-918 REVIEW if created |
| **M-022** Distribution | `Distribution` | `realized += proceeds`; mark unchanged; allowed on Acquired / Shut Down companies | **X-111** MONITOR "Cash distribution received; stake unchanged" |
| **M-024** Stock-consideration exit | `Acquisition (Closed)` where Detail/Notes contain `stock`, `shares`, `all-stock`, `stock-for-stock`, `equity consideration` **and** proceeds is None or 0 | `equity = ownership × deal_value` (value of shares received); status stays Active; stage `"Acquired (stock)"`; `latest_post = deal_value`; anchor = date; open item `acquirer_shares` (new `OpenItemKind.ACQUIRER_SHARES`) | **X-112** BLOCK "Consideration was shares: confirm the acquirer, whether it is listed, the share count and any lock-up." |
| **M-025** Chapter 11 | `Bankruptcy (Chapter 11)` | mark unchanged; **not** terminal; fv stays 3 | **X-116** BLOCK "Chapter 11: estimate recovery; the carrying value is almost certainly impaired." |
| **M-031** Secondary purchase | `Secondary Purchase` | `ownership = ownership_after` (> before); `invested += hc_investment`; `equity = own_after × latest_post`; implied post = `hc_investment / (after − before)`; alternative mark at implied price | **X-104** REVIEW reused with spread wording when |spread| > tolerance; else **X-121** MONITOR "Bought a% more at the last-round price" |
| **M-041** Listed carry | carry side: no event, position is listed (`stage == "Public"` or `listed`) | if `market.quotes[company]` exists: `equity = ownership × market_cap`; fv 1; step M-041. Else mark unchanged | **X-113** BLOCK when no quote: "Listed position has no measurement-date price — supply the close." |
| **M-051** Deal terminated | `Acquisition (Terminated)` | `equity = ownership × latest_post` (back to last-round basis); drop `pending_acquisition` open item; anchor unchanged | **X-114** REVIEW "Announced deal fell through; mark reverted to the last round — confirm nothing about the round basis has changed." |
| **M-061** Note repaid | `Note Repaid` | `realized += proceeds`; `note_at_cost = max(0, note_at_cost − principal)` where principal = `hc_investment` if given else proceeds; equity unchanged | **X-115** REVIEW "Note repaid: if the note sat inside the prior mark, reduce the carrying basis by the principal." |
| **M-040** | `Direct Listing` | identical to IPO | as today |
| **M-060** | SAFE variants | identical to Convertible Note; cap regex extended to `post-money cap`, `pre-money cap`, `$X cap`, `cap of $X` | as today |

Additional treatment flags on existing rules:

- **X-117** REVIEW on M-010/M-011/M-012 when Notes/Detail say the round was **led by HC** (`led by hc`, `hc led`, `hc-led`, `human capital led`): a related-party price is not arm's-length. Action: "Confirm an independent investor set or validated this price."
- **X-118** MONITOR on M-010 when `insider-led` / `insider round` and not HC-led.
- **X-105** note screen gains terms: `warrant`, `ratchet`, `pay-to-play`, `cram`, `cram-down`, `escrow`, `holdback`, `earn-out`, `lock-up` (only when the event is not an IPO/listing), `related party`, `restated`, `going concern`, `covenant`, `default`.
- Precedence additions: `Acquisition (Terminated)` before `Acquisition (Announced)`; `Distribution`, `Ownership Adjustment`, `Note Repaid`, `Secondary Purchase` tier 4 (after rounds); `New Investment` tier 3; `Bankruptcy (Chapter 11)` tier 2 (not terminal). `RESOLVES` gains: `Acquisition (Terminated)` resolves `pending_acquisition`; `Note Repaid` resolves `convertible_note`; `Priced Equity Round` also resolves `convertible_note` (conversion) — already true.
- `exec_view.DRIVERS` gains `distributions`, `adjustments`, `new_investments`, `stock_exits`, `impairments (Ch. 11)`; `_driver_for` maps the new rules. Bridge must still reconcile.
- `KNOWN_EVENT_TYPES` / `EventType` gain the eight new canonical strings; `test_coverage` must keep passing (every canonical type has a handler).

---

## 4. Scenario corpus (package C)

`training/` layout:

```
training/
  SPEC.md                 this file
  README.md               what the corpus is, how to run it, how to add a case
  generate.py             deterministic (seeded) generator: scenarios/*.yaml -> workbooks/*.xlsx
  scenarios/NN_name.yaml  one per workbook: base book, mutations, activity rows, expectations
  workbooks/NN_name.xlsx  generated, committed (a reviewer can open them)
  run_gauntlet.py         runs every scenario, checks expectations, writes report.md + report.json
  report.md               last run
```

Scenario YAML shape:

```yaml
name: 02_event_type_typos
description: Every known event type spelled wrong in a way a human would produce.
base: HC_Mock_Portfolio_Data.xlsx          # or "snapshot:2026Q3" for the emitted Q4 book
policy: 2026Q3                              # rules/<policy>.yaml
sheet_names: { portfolio: Portfolio, activity: "Q3 2026 Activity" }   # mutations allowed
header_mutations: { activity: { "Post-Money / Deal Value ($M)": "Post Money / Deal Value ($M)" } }
structure: { title_rows: 2, blank_rows_every: 5, totals_row: true }   # optional
portfolio_mutations:                        # optional, by company
  Drayvenn: { Stage: Public }
activity:                                   # replaces the base activity tab
  - { date: 2026-07-06, company: "Dovelane Systems", event: "Priced Equtiy Round", detail: "Series B", value: 103.8, ownership_after: 0.055, notes: "…" }
expect:
  ingest_ok: true                           # or false with `error_contains`
  validation_ids: { must: [X-912], must_not: [X-909] }
  companies:
    Dovelane Systems: { disposition: MONITOR, rules: [M-010], proposed: 5.709, tol: 0.01, flags_must: [], flags_must_not: [M-999] }
  totals: { events: 8 }
  no_crash: true
```

Runner semantics: every scenario runs in isolation against a temp copy of `rules/` and the
workbook; `execute(...)` with `adjudicate=False`; expectations compared; every failure is
one line in `report.md` with scenario, company, expected vs actual. `tests/test_gauntlet.py`
parametrizes over `scenarios/*.yaml` so the whole corpus is part of `pytest`.

### 4.1 Required workbooks (minimum set; add more if a case needs its own)

| # | Workbook | What it exercises |
|---|---|---|
| 01 | `all_events_clean` | Every canonical type (16) once, cleanly spelled, on companies chosen so each rule's arithmetic is checkable |
| 02 | `event_type_typos` | The 8 known types misspelled per §1.2 plus trailing/leading spaces, mixed case; one ambiguous (`Acquisition`) that must X-914 |
| 03 | `event_type_synonyms` | `Series B`, `Bridge`, `Exit`, `Wind down`, `SAFE`, `Dividend`, `Escrow release`, `Warrant exercise`, `LOI` (ambiguous → block) |
| 04 | `company_name_variants` | case, whitespace, `Inc.`, `(formerly …)`, a typo, and two near-duplicates in the book (add a fake `Aravine Labs` row) that make `Aravin` ambiguous → X-914 |
| 05 | `header_variants` | header typos, case, spacing, aliases from §2.2, reordered columns, an extra column, a missing optional column |
| 06 | `value_formats` | `$28.2M`, `28,200,000`, `5.5%`, `(1.2)`, dates as strings in 5 formats, Excel serials, blank tokens |
| 07 | `units` | post-money in dollars, ownership in percentage points, proceeds in dollars |
| 08 | `structure` | two title rows above the header, blank rows, a `Total` row, a trailing note row |
| 09 | `sheet_names` | each relaxed sheet-name form; one workbook variant with two activity-like sheets that must X-914 |
| 10 | `multi_event` | round+round, round then closed exit, note then round (conversion), announced then closed, shutdown then a later term sheet, secondary sale then round |
| 11 | `new_events` | one row per new canonical type with clean arithmetic; stock-consideration exit; HC-led round; insider-led round; EUR round (X-920) |
| 12 | `listed_carry` | `base: snapshot:2026Q3` — Drayvenn is Public with no Q4 event → M-041 with the stub quote; a second variant with the quote removed → X-113 |
| 13 | `numeric_edges` | ownership 0, ownership 150 (> 100 → block), negative proceeds, post-money 0, 1e12, text in a number cell |
| 14 | `missing_required` | priced round without post-money; IPO without ownership; closed exit without value; note without a parseable cap |
| 15 | `terminal_activity` | `Distribution` on Kolvani Health (Acquired) → allowed; `Priced Equity Round` on Kolvani → X-907 |
| 16 | `duplicates_and_dates` | exact duplicate rows; a date outside the window; a date in 2030; a date as text; day-first ambiguity |
| 17 | `notes_language` | one row per X-105 term |
| 18 | `quarter_rollforward` | `base: snapshot:2026Q3` with `policy: 2026Q4`; carried open items age; Gryphonel closes; Duskfern converts; year-end rollover to `Q1 2027` |
| 19 | `big_book` | 1,000 synthetic companies, 120 events — must finish in < 15 s and produce a manifest |
| 20 | `garbage` | a CSV renamed `.xlsx`; a workbook with no Portfolio sheet; a workbook with only headers; an empty file — each must raise `IngestError` with a message naming the problem |

Scenarios must make the expectations **specific**: a disposition, the rule ids in the
chain, and a mark with tolerance wherever the arithmetic is determinable from the row.
"Did not crash" is the floor, not the bar.

---

## 5. Definition of done

- `python training/run_gauntlet.py` exits 0 and `report.md` shows every scenario green
  (status at hand-off: 44 scenarios, 1,785 checks, all green; `pytest` 671 passed).
- `pytest` is green including `tests/test_gauntlet.py`, the golden file (regenerated once,
  deliberately, if new MONITOR flags on existing companies move the Q3 counts), and
  `test_coverage` for all 16 canonical types.
- `docs/valuation-policy.md` lists the new rules and validation ids; `rules/2026Q3.yaml`
  gains `note_screen.terms` and a `normalization:` block with the tolerances above
  (`event_type_max_distance: 2`, `company_max_distance: 1`, `header_max_distance: 2`,
  `min_length_for_fuzzy: 6`) — no threshold literal in code.
- Nothing in the review or executive dashboards breaks: new flag ids render like the old ones.
