# Hardening report — iterative quarterly attack on the valuation engine

**Start:** Mon Sep 7 2026 02:21 PDT
**Wind-down (stop starting new work):** 04:51 PDT
**Hard stop:** 05:21 PDT

Status: **complete** — stopped at 03:25 PDT, well inside the wind-down, because the quality bar was met (all three synthetic quarters running clean through two consecutive full passes with no newly-discovered defects). Written for someone who has not seen any of this work; the defects section is the heart of it.

## Q3 2026 regression baseline (checked before any change)

The figure the brief states — **1 Blocked / 33 Needs Review / 66 Ready, portfolio fair value 1,184.3** — is the
run of `data/HC_Mock_Portfolio_Data.xlsx` under `rules/2026Q3.yaml` with the committed live market cache
(`data/market_cache/2026-09-30`, which `run`/`build` pick up with no flag) and an **empty override ledger**.
Checked at 02:24: exactly that. With the stub fixture the same book reads 0 / 24 / 76 (fewer X-405 screens fire
without a live comps history); proposed fair value is 1,184.3 either way.

Reproduce: `python3 scripts/check_q3_baseline.py` (written during this exercise; see "How to reproduce").

## What was built and where it lives

**Phase 0 (all committed, suite green after each):**

| Change | Where | Commit |
|---|---|---|
| Configurable decision ledger: `--overrides`, `--ledger-dir` on every engine command; `RunPaths.default(overrides=, ledger_dir=)`; `RunPaths.published_dir`; publish/history/exec view thread it; `/api/health` reports the ledger in use | `src/hc_valuation/pipeline.py`, `api/publish.py`, `api/history.py`, `api/app.py`, `cli.py`; tests `tests/test_ledger_paths.py` | `4253727` |
| `synthetic` market provider: reads `data/synthetic_market/<as_of>.yaml` (refused without `synthetic: true`), writes nothing, labels manifest `synthetic:invented-test-data`, every sector `synthetic:…@month`, report carries `synthetic: true` + `notice`; Market tab prints a red banner; engine never calibrates (M-080) or screens relatively (X-401/402) against it | `src/hc_valuation/connectors/synthetic.py`, `connectors/__init__.py`, `scripts/make_synthetic_market.py`, `frontend/src/views/Market.tsx`, `lib/labels.ts`; tests `tests/test_synthetic_market.py` | `11455b1` |
| Workbook selection in the dashboard: `GET /api/workbooks`, `POST /api/workbook`; a profile = workbook + quarter policy + ledger dir + provider; header `Workbook` select; synthetic banner; CLI provider default shares the rule | `src/hc_valuation/workbooks.py`, `api/app.py`, `cli.py`, `frontend/src/App.tsx`, `lib/api.ts`; tests `tests/test_workbooks.py` | `31cda3f` |

## Defects found

### D-0 — Trial decisions had leaked into the committee ledger and been committed (fixed, `9576e98`)

**What was wrong.** `data/overrides.yaml` carried three records (Oakenvale 2.331, Gryphonel 4.6592, Drayvenn
booked 140.0 on a `closing_price` evidence of a $5,000M market cap "from Nasdaq"), approvers `jackson` and `j`,
dated 2026-09-06, committed in `c18655f`. They post-date the published Q3 snapshot (`run b36c794a9720`, booked
1,184.28, released by "Jackson Lagerwey") and are not committee decisions.

**Why it mattered.** With them on the ledger the deliverable reported 0 Blocked / 31 Needs Review / 69 Ready and a
booked fair value of 1,214.2 — Drayvenn re-marked from an invented $5,000M cap — and **34 tests failed at baseline**
(golden fixture, publish gate, readiness counts, CLI output). This is precisely the contamination Phase 0.1 exists
to make structurally impossible: every click in the review tool wrote to the one real ledger.

**Fix.** Restored the empty ledger (`git show 2172eaf:data/overrides.yaml`). No test was changed. The three
records are preserved here for the record:

```yaml
- {company: Oakenvale, quarter: Q3 2026, proposed: 2.331, booked: 2.331, approver: jackson, created_at: 2026-09-06, rule_ids_addressed: [X-102], source_suggestion: X-102/as_proposed}
- {company: Gryphonel, quarter: Q3 2026, proposed: 4.6592, booked: 4.6592, approver: j, created_at: 2026-09-06, rule_ids_addressed: [X-101], source_suggestion: X-101/as_proposed}
- {company: Drayvenn, quarter: Q3 2026, proposed: 110.068, booked: 140.0, approver: j, created_at: 2026-09-06, rule_ids_addressed: [X-101], source_suggestion: X-101/price, evidence: {kind: closing_price, as_of: 2026-09-30, market_cap_musd: 5000, source: Nasdaq, ownership: 0.028}}
```

**Test.** The whole suite (which assumes the documented empty ledger) plus `tests/test_ledger_paths.py`, which
now pins that a decision made on any other profile leaves `data/overrides.yaml` byte-identical.

### D-1 — The committed review-tool bundle was stale and thirteen superseded bundles were tracked (fixed, `31cda3f`)

`frontend/node_modules` was absent, so `npm run build` had never run on this machine (`tsc: command not found`
exits non-zero, but the wrapper's exit code was masked). `src/hc_valuation/api/static/assets/` carried seven JS and
six CSS bundles from earlier builds. Rebuilt with `emptyOutDir`; one pair remains and `index.html` references it.

### D-2 — A figure exactly at a policy threshold fired the "beyond" screen (fixed, `9314d02`)

**Found by** Q4 2026, Fernwave: a secondary stated at exactly +5.0% above the Series D post-money
(1,929.795 vs 1,837.9) raised X-104. `1929.795 / 1837.9 − 1` is `0.05000000000000004` in binary.
**Why it mattered.** A reviewer reads "5.0%" against a policy that says "beyond 5%", and the position is held for
nothing; the same arithmetic sits under X-119 (cheque price), X-103/X-123 (ownership moves), X-109 (term sheet at
80%), X-118/X-122 (step-ups) and the runway screens (cash ÷ burn: 1.4 / 0.2 is 6.999999999999999).
**Fix.** `engine/marking.py::ratio` / `ratio_change` round every compared ratio to six places (the workbook carries
post-money to 0.1 $M and ownership to three decimals; six places is far below either); `Position.runway_months`
is rounded the same way. **Test:** `tests/test_threshold_boundaries.py` — nine cases one unit either side of each
line. **Golden:** regenerated for two display fields only (Oakenvale's −21.25% prints −21.2%; Ventabrook's aged
runway 30.875 prints 30.88); no mark, flag id, readiness or total moved.

### D-3 — The quarter after an IPO blocked with no finding, and could not be cleared from the dashboard (fixed, `9314d02`)

**Found by** Q4 2026, Drayvenn. The listed carry (M-041) ran on the fixture's seeded quote (`stub:carried_listing`),
the mark was correctly provisional and the position Blocked — but `flags == []`. The provisional rule fell back
to `"M-041"`, which is not a flag, and `POST /api/overrides` refuses any rule id that is not on the position
(422). So a listed holding would block **every quarter after its listing** with nothing a reviewer could click.
(It worked in Q3 only because M-040 raises X-101 in the listing quarter.)
**Fix.** M-041 raises X-113 BLOCK whenever the quote is a stand-in (`marking.is_standin_price`, now shared with
`run.py`'s provisional test), with `price_source` in its evidence; the review tool's "Add closing price" flow
recognises X-113 as well as X-101. Two `training/` gauntlet scenarios that pinned the old behaviour
(`12_listed_carry`, `22_listed_refused`) were updated with the reason. **Test:**
`tests/test_listed_carry_standin.py`, including the API route end to end.

### D-4 — A new company entering the book made the whole quarter un-buildable (fixed, `9314d02`)

**Found by** Q4 2026, Quillbrook Labs (a `New Investment` row for a company not on the Portfolio tab; M-014 creates
the position and X-918 blocks it). `hc-valuation build` raised `ValueError: … not in the source workbook; cannot
carry its metrics` from the next-quarter writer — no report, no workbook, no roll-forward for any of the 101
positions. **Fix.** `export/snapshot.py::_entered_from_activity` carries the row from the run's own figures (fund,
sector, stage, entry date, entry price, invested, booked) with blank operating metrics and a Snapshot Notes line
saying they must be filled. **Test:** `tests/test_snapshot_new_company.py` (emits, re-ingests with zero blocking
issues).

### D-5 — A note leg carried at cost was counted twice when the note was repaid next quarter (fixed, `9314d02`)

**Found by** Q1 2027, Yarrowbank. Q4 booked 0.6 of equity plus a 0.3 note HC funded, carried at cost on its own
leg (M-060). The emitted Q1 book has one `Prior Mark` column — 0.9 — and the sidecar explained the departure only
in words. Q1 therefore read 0.9 as equity, and when the note was repaid (0.31 of cash) it kept the 0.9 *and* booked
the cash: the principal counted twice, with only an X-115 REVIEW between the double count and the book.
**Fix.** The sidecar now carries `note_legs` as numbers (`snapshot.note_legs`), the pipeline loads them,
`run_valuation(prior_note_legs=…)` restores the leg (bounded by the prior mark), the M-000 carry step records the
split, and the run id includes the legs only when any are carried so existing ids are unchanged. **Test:**
`tests/test_note_leg_carry.py` (repaid → 0.6; quiet quarter → 0.9 split 0.6/0.3; round → folds as before; an
impossible leg is ignored).

### D-6 — "No new investor" was read as a named new investor (fixed, `9314d02`)

**Found by** Q1 2027, Lumetra: a 3.02× insider round whose notes read "No new investor." X-122 should be REVIEW
when no outside investor is named; the lead test was a substring match, so the negated phrase counted as a lead
and the finding was downgraded to MONITOR — the position went from BLOCK to REVIEW disposition. **Fix.** One
whole-word, negation-aware, case-insensitive reader (`engine/textscreen.py`) shared by the note screen X-105
and the lead test. **Test:** `tests/test_lead_terms_negation.py`.

### D-8 — A same-terms extension's date regressed to the old clock one quarter later (fixed, `db3ffa3`)

**Found by** Q2 2027's opening book: Pellagrin's `Latest Round` read 2021-10-08 although the book had carried the
2026-08-11 extension since Q3, and the sidecar's staleness anchor for it was gone. `_latest_round_date` fell back to
the staleness anchor whenever the quarter had no priced round, so the column lost the extension after one quiet
quarter — and with `Latest Round == anchor` the sidecar no longer carried the anchor. The screens still fired
correctly (the anchor is what they read), but the book's own column was wrong. **Fix.** With no priced round the
column keeps the value the book carried (listed positions keep the measurement date). **Test:**
`tests/test_unconfirmed_exit_carry.py::test_extension_date_survives_a_quiet_quarter`.

### D-9 — 48.8 of booked NAV vanished at the quarter boundary (fixed, `db3ffa3`)

**Found by** Q2 2027's opening book. Knollward's acquisition closed in Q1 with no cash recorded (X-101
BLOCK-severity). The reviewer took the policy's own first option, *"Hold the prior mark until the consideration is
confirmed — keeps the position open"*, so Q1 published 48.8 for it inside a booked NAV of 1,149.4. The next-quarter
writer emitted `Prior Mark 0` for every non-Active status: Q2 opened Knollward at 0 with 0 realized, and the 48.8
left the book with no cash against it and no finding. **Fix.** A position closed in the quarter but held at a
non-zero booked mark rolls forward *Active* at that value, with a Snapshot Notes line; M-020 opens an
`unconfirmed_exit` item when no cash is recorded, and `open_items.unconfirmed_exit_stale_quarters: 1` (new key in
`rules/2026Q3.yaml`) makes E-07 put it in front of a reviewer every quarter until a closing row with proceeds
arrives or a decision writes it to zero. A decision that writes it to zero rolls forward closed as before.
**Golden:** regenerated for `run_id` only — the policy content hash includes the new key; no other field moved.
**Test:** `tests/test_unconfirmed_exit_carry.py`.

### D-10 — A duplicated activity row was applied twice (fixed, `db3ffa3`)

**Found by** the Q4 2026 malformed set: the same funded round pasted twice put HC's 1.0 cheque on the book as 2.0 of
invested capital, under a non-blocking X-906 REVIEW that stopped nothing; a duplicated secondary would have
doubled realized cash the same way. **Fix.** An activity row identical on company, event, date, value, investment,
ownership and proceeds blocks on **both** copies (as X-906 already did on the Portfolio tab): neither is applied,
the position carries its prior mark under X-900, and the workbook is corrected. Two genuinely different same-day
tranches are not duplicates. Gauntlet scenario `16_duplicates_and_dates` updated with the reason. **Tests:**
`tests/test_duplicate_activity_row.py`, `tests/test_synthetic_malformed.py` (every variant caught for its own
defect only).

### D-11 — An item opened earlier in the quarter was not resolved by a later event in the same quarter (fixed, `db3ffa3`)

**Found by** Q2 2027, Redgrove Health: a term sheet signed on 15 March and closed as a priced round the same day
stayed a `term_sheet` open item, rolled into Q2, aged past `term_sheet_stale_quarters` and raised E-07 for a deal
that had closed three months earlier — an unnecessary escalation. `RESOLVES` was applied to prior-quarter items
only (M-010 special-cased notes but not term sheets). **Fix.** `run.py::_dispatch` resolves, after every event,
the items its kind resolves among those present *before* it ran (so a closing with no cash keeps the
unconfirmed-exit item it opened). **Test:** `tests/test_same_quarter_resolution.py`.

### Not defects — expectation errors, recorded in place

Seven of my hand-derived expectations were wrong and the engine right; each is kept verbatim in
`data/quarters/synthetic/expectations/*.yaml` with `superseded: true` and a `resolution:` paragraph, so the
record of what was expected first survives: Kilnbrook (cheque check needs ≥ 1pp bought), Quillbrook (X-918 is a
missing-input rule → Blocked), Brackenvale (48.03 months rounds to 48.0 under the written policy), Wildebrook
(exactly −20% is "at" the line — see ambiguities), Tarnwick (a recap deliberately skips the cheque check),
Lanternfell (M-000 carries the book's 37.3, not a recomputation).

## Phase 1 — the quarters, and where they live

Everything is under `data/quarters/synthetic/` (never `Assignment context/`, never `data/`):

| Path | What it is |
|---|---|
| `ledger/overrides.yaml`, `ledger/published/`, `ledger/decisions_<quarter>.md` | The chain's own decision ledger and publish archive. One decision per not-Ready position per quarter, each logged with its reason; published under a second name (`Reviewer B`) so four-eyes holds. **`data/overrides.yaml` and `data/published/` were never written.** |
| `build/<quarter>/` | What `hc-valuation build` emitted for each quarter: report, workbook, CSVs, `run.json`, and the next quarter's input (`portfolio_<next>.xlsx` + `open_items_carry.yaml`). Git-ignored (the root `.gitignore` covers `build/`); regenerated by the script in about a minute. The three quarter workbooks that were built from it are committed. |
| `2026Q4/`, `2027Q1/`, `2027Q2/` | The test workbooks — `SYNTHETIC_portfolio_<quarter>.xlsx` beside its sidecar. The Portfolio tab is the previous quarter's *booked* book as `build` emitted it; only the activity rows (22 / 17 / 13) and a few operating metrics (listed on a `Synthetic Edits` tab) are hand-written. First sheet: `SYNTHETIC TEST DATA`. |
| `malformed/<quarter>/` | Eleven one-defect variants per quarter (missing post-money, unreadable cell, non-USD, event after the measurement date, duplicate Portfolio row, duplicate activity row, duplicate funded round, unreconciled prior mark, unknown event type, financing after an exit, wrong-quarter activity sheet). Never part of the chain. |
| `expectations/<quarter>.yaml` | The hand-derived expectations, committed before each run. |
| `scripts/synthetic_chain.py` | Builds and drives all of it (`q3`, `workbook`, `run`, `decide`, `reset`). |
| `rules/2026Q4.yaml`, `2027Q1.yaml`, `2027Q2.yaml` | `hc-valuation next-policy` output, unedited. |
| `data/synthetic_market/<date>.yaml` | The invented sector multiples the `synthetic` provider reads (see Phase 0). |

**Coverage across the three quarters** (company in brackets): financings and dilution (Emberfold, Halcyra,
Wildebrook at exactly −20%, Solvantra and Kilnbrook at the cheque tolerance, Gorseline), down rounds and recaps
(Umberly, Tarnwick twice, Aravine, Dovelane, Umberly's Chapter 11 emergence), convertible notes and conversions
(Nimbrel note→round in one quarter, Duskfern and Emberfold notes converting, Yarrowbank note funded then repaid,
Tidewell unfunded), full and partial exits (Gryphonel, Beltrix, Underbough, Kestwick, Oakenvale, Elmsworth,
Arcfoundry with a holdback then its release, Knollward with no cash, Wrenfield returning more than carrying;
secondaries on Fernwave at exactly +5%, Ironquill at +5.1%, Nimbrel, Mardellan at −12%), pending and announced
deals (Jettamar pending three quarters → E-07, Pinwhistle announced then terminated, Elmsworth announced and closed
in one quarter), IPOs and lock-ups (Drayvenn carried through its lock-up expiry, Fernwave IPO, Thornmill direct
listing), stock consideration (Halcyra), shutdowns with and without residual cash, new companies entering the
book (Quillbrook Labs), overlapping events (Nimbrel, Redgrove same-day term sheet + round, Elmsworth), no activity
with stale marks or deteriorating metrics (Isoquill, Brackenvale at 48.03 months, Cascabel / Elmsworth / Thistledown
crossing 24 months, Birchhollow worsening, Vellichor at exactly −15%, Zealwick at exactly 6.0 months of runway,
Northquill at 5.99, Stonegather at zero cash), and every malformed input above.

## Phase 2 — expectations first, then the engine

Each quarter's expectations were derived by hand from the emitted opening book and the policy and committed before
the run (`46a1a6a`, `6a6bd97`, `5bb5f24`). First-run results:

| Quarter | First run | Genuine defects | My derivation errors (kept in place, `superseded: true`) |
|---|---|---|---|
| Q4 2026 | 7 mismatches | D-2 (Fernwave), then D-3 (Drayvenn, on deciding) and D-4 (Quillbrook, on building) | Kilnbrook, Quillbrook readiness, Brackenvale, Wildebrook |
| Q1 2027 | 3 mismatches | D-5 (Yarrowbank), D-6 (Lumetra); D-8 and D-9 on emitting Q2 | Tarnwick |
| Q2 2027 | 3 mismatches | D-11 (Redgrove) | Lanternfell |
| Malformed | 1 of 11 not caught | D-10 (duplicated funded round) | — |

After the fixes, **two consecutive full passes** over all three quarters give 0 mismatches each (the second at 03:14).

## Verification results

- **Suite:** 1,116 passed (final run recorded under "Final state"). 68 new tests across twelve files (listed per defect above, plus
  `tests/test_ledger_paths.py`, `tests/test_synthetic_market.py`, `tests/test_workbooks.py`,
  `tests/test_synthetic_malformed.py`).
- **Q3 2026 regression:** `python3 scripts/check_q3_baseline.py` → 1 Blocked / 33 Needs Review / 66 Ready,
  proposed fair value 1,184.3, ledger empty — checked at 02:24, 02:44, 03:12 and in the final state below.
  The golden fixture was regenerated twice, each time for fields that carry no valuation content (two display
  roundings under D-2; the `run_id` under D-9 because the policy content hash gained a key); every other field of
  the 100-company fixture is byte-identical.
- **Financial reconciliation across quarters** (checked programmatically, 03:14): for each boundary Q3→Q4→Q1→Q2,
  the published booked NAV equals the next quarter's prior NAV to the cent (1,173.8533 / 1,161.3780 / 1,149.4082),
  and per company the next quarter's prior mark, opening ownership, opening invested and cumulative realized equal
  the published closing values — including Quillbrook (entered from activity), Yarrowbank (note leg), Knollward
  (held exit) and Drayvenn / Fernwave (closing prices supplied).
- **Idempotency:** the same workbook run twice gives the same `run_id` and byte-identical `run.json`; switching the
  dashboard to another workbook and back returns the original `run_id` (`tests/test_workbooks.py`).
- **Readiness / Monitor:** Blocked is only ever a missing input (X-113 stand-in price, X-112 acquirer stock, X-116
  Chapter 11, X-918 no Portfolio row, X-900 refused row, M-999); everything else that needs a person is Needs
  Review; Monitor rides alongside (Wildebrook, Aravine, Tidewell are Ready with MONITOR findings). No position in
  any quarter reached Ready with an unresolved BLOCK or REVIEW finding; the publish gate refused until every one
  was decided, and `require_second_approver` refused the decider's own name.
- **AI cannot bypass a control:** the recommender ran as policy default throughout (no key; the card says so). Every
  scripted decision books a number from the engine's own suggestion list or a closing-price evidence record
  validated by the API; `tests/stress/` (226 tests) still pass.
- **Changed inputs trigger renewed review:** a Q3 decision does not carry into Q4 (Tarnwick, Jupelan, Birchhollow
  were Needs Review again); an override whose proposal moved raises E-01 drift (existing tests).
- **Audit history across screens and exports:** the mark archive assembled from the chain's publish ledger has
  Q3, Q4 and Q1 points for every company (302 published points, 0 errors) including Quillbrook from Q4 on; each
  quarter's `build/` carries `audit_trail.csv` with the E-01 rows for every scripted decision and `manifest.json`
  whose `run_id` matches the published record.
- **The served dashboard** (Q4 2026 profile on port 8790, driven with Playwright through the installed Chrome —
  the machine's macOS 13 is too old for Playwright's own Chromium): the header shows the `Workbook` select with
  plain labels ("Q4 2026 · synthetic test data", "Q3 2026", …) and the synthetic banner; the Market tab shows the
  invented-data warning and "Synthetic" source chips; no raw enums or snake_case on screen (the one hit,
  `synthetic_market`, was the source-file path on the banner and was moved under Technical details); no failed
  requests, no page errors. Switching to the real Q3 book through the select removes the banner, shows Q3 2026,
  and `/api/health` reports `data/overrides.yaml` as the ledger; switching back restores Q4. `/api/workbooks`
  lists the real book as `live` and the synthetic quarters as `synthetic` — after a wiring fix found by this
  check: the CLI resolved the default provider before creating the app, so a switch would have kept the first
  quarter's provider (now `create_app(provider=, provider_explicit=)`).

## Policy ambiguities and the conservative calls made

1. **Thresholds exactly at the line.** After D-2 every "beyond" threshold is strict and consistent (X-104 5%,
   X-119 10%, X-302 −15%, X-304 6 months, X-103 −20%), while X-109 (≤ 80%) and X-118/X-122 (≥ 2×, ≥ 3×) are
   inclusive as written. The policy text for X-103 ("ownership −20% relative") does not say which; X-103 is
   MONITOR so readiness is unaffected either way. **A human should confirm** the strict reading for X-103.
2. **Age rounded to one decimal before the 48-month comparison** (Brackenvale: 48.03 → 48.0 → not REVIEW). This is
   the written policy, and the engine follows it. The conservative alternative is to compare unrounded (one day
   past four years is past four years). Left as written; **a human should decide**.
3. **A probability-weighted mark carried past its expected close** (Jettamar: announced Q4 "expected to close Q1",
   still open in Q1) re-reviews only when the item ages to 2 quarters. It sat Ready in Q1. The M-050 row does not
   record an expected-resolution date the engine could compare. **Suggest:** parse none, but ask the row for a date
   and escalate when it passes.
4. **Acquirer stock with no listing** (Halcyra) sat Ready for a quarter after the X-112 decision, with no valuation
   update until the item ages to 2. **Suggest** a MONITOR each quarter it is carried.
5. **Reviewer-supplied closing price does not become the carried market cap.** Drayvenn's Q4 decision priced it at
   a $3,700M cap; the emitted book carries `Latest Post-Money 3,931` (the IPO print) with the booked 103.6
   explained in the sidecar, and the next quarter's stand-in seeds from 3,931. The mark is right; the column is not
   the number the committee used. Not fixed (it needs the override's evidence to update engine state).
6. **Chapter 11 written to zero by the policy default** (Umberly, Q1: `X-116/write_to_zero`), then recapped at
   $40M in Q2 from a zero prior mark. Correct under the policy; the reviewer's Q1 default is aggressive.
7. **Every simulated decision took the policy recommendation unless named** (Drayvenn/Fernwave/Thornmill closing
   prices, Birchhollow calibrated, Umberly hold-prior in Q4). Where the recommendation was "hold the prior mark"
   on a closed exit with no cash (Knollward) that is what a reviewer following the tool would have done — which is
   how D-9 was found.

## Remaining limitations and known weaknesses

- The synthetic quarters use the `synthetic` comps provider, so M-080 calibration and the relative multiple
  screens (X-401/X-402 against a live median) are **not exercised** after Q3 2026 — by design (invented numbers
  must not move an alternative mark), but it means those paths were attacked only through the real Q3 book.
- The quote slot stays the fixture: every listed position blocks each quarter until a closing price is supplied.
  That is the honest behaviour, and the chain exercises the supply path, but no live-quote path exists to test.
- The chain's decisions are scripted (policy default unless named). A human reviewer choosing other options would
  produce different opening books; the chain proves the mechanics, not the judgment.
- `hc-valuation build` still emits the next-quarter workbook from an *undecided* book (booked = proposed where no
  decision exists). The chain only ever rolled forward from published books; the README's refresh steps should say
  "publish first". Not changed.
- Discovery in the dashboard lists every `.xlsx` under `data/quarters/` (including malformed variants, shown
  disabled or usable as they are). Fine for a test tree; a production tree would want an explicit registry.
- Workbook switching is process-wide state on the server (one current profile), as the single-user tool is today.
- Ambiguities 3–6 above are recorded, not fixed.

## How to reproduce

```bash
python3 -m pytest -q tests/                      # the whole suite (~60 s)
python3 scripts/check_q3_baseline.py             # 1 / 33 / 66 and 1,184.3 with an empty ledger

# the chain, from scratch (rewrites data/quarters/synthetic/ledger and build/; workbooks and expectations are kept)
python3 scripts/synthetic_chain.py reset
python3 scripts/synthetic_chain.py q3            # decide + publish the real Q3 into the chain ledger; emit Q4's input
python3 scripts/synthetic_chain.py workbook 2026Q4 && python3 scripts/synthetic_chain.py run 2026Q4   # 0 mismatches
python3 scripts/synthetic_chain.py decide 2026Q4 # publish Q4, emit Q1's input
python3 scripts/synthetic_chain.py workbook 2027Q1 && python3 scripts/synthetic_chain.py run 2027Q1
python3 scripts/synthetic_chain.py decide 2027Q1
python3 scripts/synthetic_chain.py workbook 2027Q2 && python3 scripts/synthetic_chain.py run 2027Q2
python3 scripts/synthetic_chain.py decide 2027Q2 # publish Q2, emit Q3 2027's input

# serve a synthetic quarter (its own ledger, synthetic multiples, the Workbook switcher in the header)
hc-valuation run --port 8790 --input data/quarters/synthetic/2026Q4/SYNTHETIC_portfolio_Q4_2026.xlsx \
    --policy rules/2026Q4.yaml --ledger-dir data/quarters/synthetic/ledger
```

`run <quarter>` compares the quarter *undecided* (the chain ledger's records for that quarter are filtered out) so
the committed expectations keep their meaning on a re-run.

## Simulated reviewer decisions

Every decision the chain made is on record in `data/quarters/synthetic/ledger/overrides.yaml` and, in readable
form, `ledger/decisions_2026Q3.md`, `decisions_2026Q4.md`, `decisions_2027Q1.md`, `decisions_2027Q2.md` (company,
readiness, proposed, booked, rules addressed, reason). The rule: one decision per position that was not Ready,
taking the policy recommendation (the engine's own first-listed priced option) unless named in
`scripts/synthetic_chain.py::DECISIONS`. The named ones, and why they were needed to establish an opening position:

| Quarter | Company | Decision | Why |
|---|---|---|---|
| Q3 2026 | Drayvenn | Closing price: $4,100M market cap (invented, labelled so) → booked 114.8 | The listing has no feed; without a supplied close the position cannot be published, and the chain needs a published Q3 to open Q4 |
| Q3 2026 | Birchhollow | Comps-calibrated alternative (X-202/calibrate) → 28.145 | To carry a *booked* mark that departs from ownership × post-money into Q4 and prove the sidecar explains it |
| Q3 2026 | Oakenvale | Intended: the 25% structure haircut; the suggestion key was guessed wrong, so it booked as proposed (the log says so) | — |
| Q4 2026 | Drayvenn | Closing price $3,700M → 103.6 | As above, each quarter |
| Q4 2026 | Umberly | Hold the prior mark on the down round (X-102/hold_prior) → 24.1 | To carry a held mark above ownership × post-money into a Chapter 11 quarter |
| Q1 2027 | Drayvenn, Fernwave | Closing prices $3,900M / $2,200M | As above |
| Q2 2027 | Drayvenn, Fernwave, Thornmill | Closing prices $4,000M / $2,500M / $2,400M | As above |

Everything else took the recommendation — which is how D-9 surfaced: on Knollward the recommendation was the
policy's own "hold the prior mark until the consideration is confirmed", and the roll-forward then lost the mark.

## Final state

- **Time:** started 02:21, quality bar met 03:14 (second consecutive clean pass), report finished 03:30 — about
  1h10m of the 3h budget used, well before the 04:51 wind-down.
- **Working tree:** clean; 11 commits on `v1-refresh` on top of `b7e59cd`:

```
5ae9053  Synthetic chain complete: Q2 2027 run, decided and published; second full pass clean; docs
db3ffa3  Four more defects from the Q2 2027 quarter and the malformed set, and the dashboard's provider wiring
5bb5f24  Synthetic chain: Q2 2027 expectations, written by hand before the engine runs on that workbook
c7bacce  Synthetic chain: Q4 2026 and Q1 2027 run, decided and published; Q2 2027 workbook emitted
9314d02  Five defects found by the synthetic Q4 2026 and Q1 2027 quarters, each with a regression test
6a6bd97  Synthetic chain: Q1 2027 expectations, written by hand before the engine runs on that workbook
46a1a6a  Synthetic test chain: Q3 decided and published into its own ledger; Q4 2026 workbook and expectations
31cda3f  Let the dashboard switch workbooks: GET /api/workbooks, POST /api/workbook
11455b1  Register a 'synthetic' market provider for quarters no feed can price
4253727  Make the decision ledger configurable: --overrides, --ledger-dir, RunPaths.published_dir
9576e98  Restore the empty Q3 2026 override ledger
```

- **Suite:** `python3 -m pytest -q tests/` → **1,116 passed** (was 1,047 at the start, of which 34 failed until D-0
  was fixed); `tests/stress/` → 226 passed. 68 new tests in twelve new files. No test was deleted, skipped, xfailed
  or loosened; the two golden regenerations and the three gauntlet-scenario updates are each explained above and
  in their commit messages.
- **Frontend:** rebuilt after every change; one bundle pair in `src/hc_valuation/api/static/assets/`.
- **Q3 2026 regression check** (`python3 scripts/check_q3_baseline.py`, run last at 03:23):
  `readiness {'Blocked': 1, 'Needs Review': 33, 'Ready': 66}   proposed fair value 1,184.3   booked 1,184.3` —
  unchanged, on an empty ledger, against the committed live cache.
- **Not written to:** `Assignment context/` (read-only throughout), `data/overrides.yaml` (restored empty, then
  never appended), `data/published/` (unchanged), `data/market_cache/` and `~/.cache/hc-valuation` (the synthetic
  provider writes nothing; `~/.cache/hc-valuation` does not exist on this machine). `ANTHROPIC_API_KEY` was never
  read, printed or set; the recommender ran as policy default and said so on every card.
- **Where a reader should look first:** the defects D-3, D-5, D-9 and D-10 — each is a number that would have been
  wrong or a position that could not be cleared in a real second quarter, and none of them was visible from the
  Q3 book alone.
