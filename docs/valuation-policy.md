# HC Valuation Engine — Marking Policy 2026Q3-0.2

Measurement date **2026-09-30** · prior close **2026-06-30** · 100 positions (96 active before, 93 after) · 18 Q3 events · prior NAV **$1,139.3M**

> Rendered version: https://claude.ai/code/artifact/df056a40-d661-4734-a85b-738c5dd48707
> Destination in repo: `docs/valuation-policy.md`

---

## 1. Design principles

1. **Mechanical rules produce a number.** Deterministic, no run-time judgment. All judgment lives in a rule definition or a config value, both versioned.
2. **Exception rules never change a number.** They annotate only. If flags could move marks, nobody could tell whether a figure came from policy or heuristic.
3. **Config holds every threshold.** No magic numbers in code. Changing a threshold bumps the policy version; re-running Q3 under v0.1 always reproduces v0.1.
4. **Every mark is a chain, not a value.** Each rule appends a `MarkStep` (rule ID, inputs, prior, new, rationale, evidence). `proposed_mark` == last step's `new_value`. The review table is that chain rendered.
5. **Severity test:** a rule may gate a mark only if a reviewer could change the booked number. Otherwise it is MONITOR, however interesting.

Base identity: `mark = FD ownership × post-money`.

---

## 2. Layer 1 — mechanical marking rules

| ID | Rule | Formula | Notes |
|---|---|---|---|
| **M-000** | Carry forward | `mark(t) = mark(t−1)` | Default. 82 companies in Q3. |
| **M-010** | Priced equity round | `mark = ownership_after × post_money`; `invested += hc_investment` | Resets mark, ownership, stage, staleness clock. |
| **M-011** | Flat / same-terms extension | as M-010, **staleness clock NOT reset** | No price discovery occurred. → Pellagrin. |
| **M-012** | Down round / recap | as M-010, with the headline treated as **the allocation the workbook cannot see**; `structure_adjusted = equity × (1 − down_round.structure_haircut_pct)` written as an alternative | A recap re-cuts the preference stack. `ownership × post` is right only if every class shares pro rata; the new senior class moves HC's share **down if HC is junior to it, up if HC funded it** (the row records `hc_funded_new_class`). Always BLOCK; the resolutions are as proposed, the policy's 25% junior-class haircut (a priced placeholder until the round documents give a waterfall), or hold. → Oakenvale, Tarnwick. |
| **M-020** | Closed exit | `mark = 0`; `realized += proceeds`; status → Acquired | Schema supports escrow/holdback as a receivable; none in Q3. → Cindral. |
| **M-021** | Shutdown | `mark = 0`; `realized += residual` | Terminal; suppresses all carry-side exceptions. → Larkspell, Islewind. |
| **M-030** | Secondary sale | `realized += proceeds`; `remainder = ownership_after × basis` | `basis: last_round` (default) or `secondary_price`. The sale price is the row's own value column ("implied valuation for secondaries"); proceeds ÷ stake sold is the recorded cross-check. A spread beyond tolerance is X-104. → Marrowick Bio. |
| **M-040** | IPO / direct listing | `mark = ownership_after × market_cap(measurement_date) × (1 − lockup_discount)` | **9/30 close, not the IPO print.** L3 → L1. Default lockup discount 0% (ASU 2022-03: a contractual sale restriction is not a characteristic of the security; blockage on a Level 1 price is separately prohibited). Always BLOCK. `Direct Listing` dispatches here too. → Drayvenn. |
| **M-050** | Announced acquisition | `mark = ownership × deal_value × close_probability` (default 0.90) | Alternatives: `full_deal_value`, `hold_prior`. Always BLOCK. → Gryphonel. |
| **M-060** | Convertible note / SAFE | equity mark unchanged; `note_at_cost += hc_investment` | A cap is a ceiling, not a price. Cap parsed from `$X valuation cap`, `$X post-money cap`, `$X pre-money cap`, `$X cap`, `cap of $X`, `cap $X`. A note outstanding at a later priced round or listing converts (note leg folds into equity). → Duskfern (funded), Emberfold (unfunded). |
| **M-070** | Signed term sheet | mark unchanged, disclosed | Non-binding. → Halcyra. |
| **M-013** | Ownership adjustment | `ownership = ownership_after`; `mark = ownership_after × latest_post`; `invested += hc_investment` (warrant strike) | No price event (warrant exercise, pool expansion, cap-table restatement): re-marked on the unchanged last-round basis; staleness clock untouched. Always REVIEW (X-110). |
| **M-014** | New investment | `mark = ownership_after × post`; `invested += hc_investment`; anchor = date | First check. A company not in the Portfolio tab is created from the row (fund from `Fund I/II/III` in Notes/Detail else `Unassigned`; sector from a known sector name else `Unclassified`; stage from Detail else `Unknown`) and additionally raises X-918. |
| **M-022** | Distribution | `realized += proceeds`; mark unchanged | Dividend, escrow release, earn-out, holdback, milestone. Allowed on Acquired / Shut Down companies (cash arriving after the exit). |
| **M-024** | Stock-consideration exit | `mark = ownership × deal_value`; status stays Active; stage `Acquired (stock)`; `latest_post = deal_value`; anchor = date | Dispatched from `Acquisition (Closed)` when Detail/Notes say stock / shares / all-stock / stock-for-stock / equity consideration **and** no proceeds. Opens an `acquirer_shares` item. Always BLOCK (X-112). |
| **M-025** | Chapter 11 | mark unchanged; **not** terminal; fv stays 3 | Reorganisation, going concern. Carry-side screens still run. Always BLOCK (X-116): the recovery estimate is a human's job. |
| **M-031** | Secondary purchase | `ownership = ownership_after`; `invested += hc_investment`; `mark = ownership_after × latest_post`; implied post = `hc_investment / (after − before)` recorded as `at_implied_price` | HC buys more from another holder. Spread vs last round beyond tolerance → X-104 REVIEW; else X-121 MONITOR. |
| **M-041** | Listed carry | `mark = ownership × market_cap(measurement_date)`; fv 1 | Carry side: a `Public` position with no event re-marks to the quote. No quote → M-000 and X-113 BLOCK. |
| **M-051** | Deal terminated | `mark = ownership × latest_post` (back to the last-round basis); drops `pending_acquisition`; anchor unchanged | X-114 REVIEW. An announcement and its termination in one quarter: the announcement is superseded. |
| **M-061** | Note repaid | `realized += proceeds`; `note_at_cost = max(0, note_at_cost − principal)`, principal = `hc_investment` else `proceeds`; equity unchanged | X-115 REVIEW — if the note sat inside the prior mark rather than the note leg, the reviewer reduces the carrying basis. |
| **M-999** | Unrecognised event | mark unchanged + **validation error + BLOCK** | Never falls through to carry. An unregistered event type halts that position. |
| **M-080** | Stale-round comps calibration | `equity_mark × comp_mult(t) / comp_mult(round_month)`, bounded ±35% | **On, gated to an observed comps history** (`require_live_history`): the vendor-shaped fixture never calibrates; `--provider live` does. Writes the `calibrated_to_comps` alternative only, never the proposal. Section 2b. |

### Departures from the brief's base rule

The brief's base rule — a priced round marks at ownership after × post-money, an exit goes to realized and the mark to zero, no activity carries — is exactly what M-010, M-020/M-021 and M-000 do, and it covers 14 of the 18 Q3 events. The engine departs from the literal rule in four places, each on purpose, each BLOCK- or REVIEW-gated so the committee sees the departure and can reverse it with one override, and each with the literal-rule number recorded as an alternative:

- **M-050 announced acquisition, probability-weighted.** Literal rule: nothing has closed, so Gryphonel carries at $3.50M. Engine: **$4.66M = 0.90 × $4.79M (the deal closes: ownership × $133M) + 0.10 × $3.50M (the deal breaks: the standalone mark at the last round)** — a probability-weighted expected return, with the break branch at the value HC would still hold, not at zero. An announced, signed deal at a known price is better evidence of value than a round from years earlier; ASC 820 asks what a market participant would pay for the position today, and that is the deal price weighted by the risk it fails. No time-value discount is applied for a Q4 close (one quarter at a venture discount rate is inside the rounding of the probability itself). `at_full_deal_value` ($4.79M) and `hold_prior` ($3.50M) are the alternatives; X-101 blocks until the committee ratifies the probability.
- **M-060 funded convertible note, at cost.** Literal rule: a note is not a priced round, so Duskfern carries at $6.10M. Engine: $6.60M — the equity leg unchanged and HC's $0.50M of new money carried at cost on a separate note leg, because cash HC just put in is an asset at cost until it converts, and a cap is a ceiling, not a price. X-107 REVIEW asks whether the bridge is a distress signal that should pull the equity leg down instead.
- **M-040 IPO, at the measurement-date market cap.** Literal rule: a listing is a priced event at the offer price. Engine: the 9/30 close, because a listed position is Level 1 and the exchange price is the fair value, not the print. In this tree the quote is seeded to the print (the ticker is synthetic) so the two numbers coincide at $110.07M; X-101 blocks until the price source is confirmed.
- **M-030 secondary sale, remainder at the last round.** Literal rule: the print is a transaction in the security, so Marrowick's remaining 70% marks at the secondary price. Engine: the remainder stays at the last-round basis ($8.77M) because a partial, negotiated secondary is a weaker price signal than a primary round; `at_secondary_price` is the alternative and X-104 REVIEW fires when the print departs from the round by more than 5%. Marrowick's row states the price — $516M, the round exactly — so no spread is flagged; proceeds ÷ stake sold ($3.9M ÷ 0.8%) would say $487.5M, −5.5%, but that is the rounding of a three-decimal ownership figure on a small block, and the step records it as the cross-check rather than the price. `secondary.remainder_basis: secondary_price` flips the default.

### Event precedence (multi-event quarters)

1. Shutdown / closed exit (terminal — suppresses everything except a later Distribution / Note Repaid, which move cash only)
2. IPO / Direct Listing; Chapter 11 (not terminal)
3. Priced round (latest by date); New investment
4. Secondary sale / purchase; Distribution; Ownership adjustment; Note repaid
5. Acquisition terminated (wins over an announcement in the same quarter); Announced acquisition
6. Convertible note / SAFE
7. Term sheet
8. Carry forward (M-000, or M-041 for a listed position)

Within a tier, later date wins. A note outstanding at a priced round or listing converts: the note leg folds into the equity mark.

---

## 2b. M-080 — stale-round comps calibration

**What it computes.** After the roll, for every active Level 3 position with an ARR whose price anchor is at least `calibration.min_age_months` (24) old, and whose sector has a comp history covering the measurement month and the round month (or the nearest month with a basket value within `round_month_tolerance`, ±3 — a round closes over weeks, and the month actually used is recorded on the step):

```
factor      = comp_multiple(measurement month) / comp_multiple(round month)
factor      = clamp(factor, 1 − bound_pct, 1 + bound_pct)          # bound_pct: 0.35
calibrated  = equity_mark × factor
```

The M-080 step records `comp_multiple_at_round`, `comp_multiple_now`, `round_month`, `comp_month_used`, `factor_raw`, `factor_bounded`, `bound_hit` and `comps_source`, so a workpaper reader sees the two multiples, the ratio, and whether the bound rather than the comps set the number. The indication's raw ratio is shown beside the bounded one, on the step and on the Market page, and with five-name baskets the limit binds often: on the live history in the committed cache (55 months) M-080 produces 42 indications, 24 of them set by the ±35% limit on raw ratios between 0.26× and 2.59×.

It writes `calibrated_to_comps` into `alternative_marks` and appends an M-080 step whose prior and new value are both the proposal. **It never writes the proposal.** The base mark stays at the last round; the calibrated figure is a labelled alternative a reviewer can choose, and choosing it is an E-01 override like any other. It has nothing to do with the ±20% multiple sensitivity in the Summary — that is `rollup.py`, a portfolio-level shock on multiple-exposed NAV, and it runs with or without M-080. The three share one exposure test, `multiple_exposed`: a Level 3 mark with ARR at or above `multiple.min_arr`; Level 1, pre-revenue and terminal positions are never moved by a multiple regime.

**Worked example (Birchhollow, Cybersecurity, from a scratch run with `calibration.enabled: true` on the fixture).** Round anchor 2021-05, 64 months before 2026-09-30. Fixture Cybersecurity multiple 18.03× in the round month, 13.01× now. Factor 13.01 / 18.03 = 0.7216, inside the bound. Equity mark $43.30M × 0.7216 = **$31.24M** recorded as `calibrated_to_comps`; proposal unchanged at $43.30M. Halcyra (71 months, 15.54× → 13.01×, factor 0.837) calibrates to $2.26M against a $2.70M proposal. Pellagrin (Climate & Energy, 13.05× → 7.14×, raw factor 0.547) pins at the −35% floor: $13.93M × 0.65 = $9.05M.

**Why ±35%.** A stale Level 3 mark moved purely by a public-comps ratio is an estimate of direction, not a valuation: the comps say what the sector re-rated by, not what this company did. The bound stops a sector that tripled from tripling a company that did not, and caps the alternative at roughly one round's worth of re-rating in either direction — enough to say "this mark is likely off by a third", which is what a reviewer needs, without producing a number the engine would have to defend on its own.

**On the fixture, the bound sets the number — so the fixture never calibrates.** The PitchBook-shaped fixture trends hard: with the gate waived, **33 of the 45 candidates pin at +35% and two more at −35%**; only ten land between. On the stub it is the bound, not the comps, that sets most alternatives — a property of the fixture, not the rule. Policy 2026Q3-0.2 therefore ships calibration **on** but gated: `require_live_history: true` means M-080 runs only when the sector's comps carry an observed source (`live:edgar+yahoo`), and the fixture leaves every alternative absent. Under `--provider live` the baskets carry `months_of_history: 96` (Yahoo `range=10y`), so the history can reach the round months of this book's stale positions (48–71 months old) — on the condition that at least `min_constituents` (3) of the sector's basket were listed and had filed in that month; a month below that has no value, the ±3-month tolerance covers most such gaps, and the M-080 step records how many names stood behind each of the two multiples (`n_constituents_at_round`, `n_constituents_now`) so a reviewer sees when a 2020 value rests on three names and a 2026 one on five. Every month of the history is point-in-time: the revenue, share count and balance sheet used are those *filed* by that month's end, so the multiple in a round month is the one the market saw when the round was priced, not one restated later. Where it does not, the M-080 step and the alternative are simply absent and the "calibrate" suggestion does not appear.

**The sensitivity view.** The ±20% shock the brief asks for is `rollup.sensitivity`, reported on every multiple-exposed mark and on the software sectors alone (`sensitivity.software_sectors` names what "software multiples" means); the review tool's Movement page carries a *Sensitivity view* with a slider from −20% to +20% that interpolates the same arithmetic — NAV(s) = booked + exposed × s — by sector, by fund and by position, with a scope switch between the two.

**Observed sensitivity (`comps_move`).** The same history answers a second question the brief asks — what the book looks like if software multiples move — with what they actually did: each sector's basket multiple in the measurement month against three months earlier, applied to that sector's multiple-exposed NAV (the positions the ±20% shock moves). It is alternative arithmetic like M-080, reported beside the shock on the Movement page and in `run.comps_move`, and labelled fixture or live by the source of each sector's history.

**Down rounds and the structure haircut.** Ownership × post-money on a down round or recap is a ceiling: the preference stack and pay-to-play the schema cannot see only lower it. `marking.down_round.structure_haircut_pct` (25%) is a policy placeholder for that structure, written as the `structure_adjusted` alternative and offered as the middle option on X-102 beside "book the ceiling" and "hold prior"; it is replaced by a waterfall (or an OPM backsolve) when the round documents are read, and the step records the haircut used. It is deliberately a round number a committee can argue with, not an estimate the engine pretends to have made.

**How a reviewer uses it.** X-202 (round older than 48 months), X-106 (flat extension without price discovery) and X-405 (stale price that a live screen argues with) each carry a "Calibrate the mark to public comps" suggestion that books `calibrated_to_comps`. Accepting it is an E-01 override addressed to that rule, under a named approver, with `source_suggestion` on the ledger record. If the alternative was not produced (calibration off, sector history missing, round too old for the live history) the suggestion is dropped rather than shown with no number.

---

## 3. Layer 2 — exception rules

Severity ∈ {BLOCK, REVIEW, MONITOR}. **Escalation:** any BLOCK rule → BLOCK; ≥2 REVIEW rules from different families → BLOCK; 1 REVIEW → REVIEW; MONITOR only → MONITOR. A terminal position (realized, written off) drops its carry-side screens — staleness, growth, runway and multiples mean nothing for a company that no longer exists — but keeps every BLOCK and every event-driven REVIEW (an exit whose cash is short of the deal value carries an escrow question a reviewer could still change), so terminal → CLEAR only when nothing event-driven is left. A priced round that records HC's ownership going to zero with no exit is X-101 BLOCK (a cram-out the columns cannot describe, or a wrong cell).

| ID | Rule | Severity | Trigger |
|---|---|---|---|
| **X-101** | Non-mechanical treatment | BLOCK / REVIEW | BLOCK: announced acquisition, IPO w/ lock-up (when no exchange quote is on file the flag says the listing-day market cap is standing in for the close), closed exit with no proceeds or proceeds of zero, secondary with no ownership change. REVIEW: a shutdown that returns more cash than its carrying value (the write-off may be a partial recovery, not a zero). |
| **X-102** | Down-round structure risk | BLOCK | New post < prior post |
| **X-103** | Non-participation dilution | MONITOR | No HC participation, ownership −20% relative. *Portfolio signal, not a valuation one — the mark comes from a fresh arm's-length round.* |
| **X-104** | Secondary price spread | REVIEW | \|implied − last round\| > 5% |
| **X-106** | Flat extension, no price discovery | REVIEW | Same-terms extension (M-011); mark repriced, clock not reset |
| **X-107** | Funded bridge note | REVIEW | HC put new money into a note (M-060); cost basis + distress signal |
| **X-108** | Unfunded bridge note | MONITOR | Note HC did not fund; nothing to decide |
| **X-109** | Term sheet disclosure | MONITOR / REVIEW | Non-binding; indicated value disclosed, not booked. REVIEW when the indicated post is at or below `indications.term_sheet_review_below` (80%) of the last round: a lower price in writing is evidence a market participant would not pay the carried price, and "mark down to the indication" is a priced option. |
| **X-105** | Note language screen | REVIEW | `Notes` free text contains a term the schema cannot encode (escrow, holdback, earn-out, milestone, contingent, participating, ratchet, preference, litigation, restated, bankruptcy, conversion, warrant, pay-to-play, cram-down, lock-up, related party, going concern, covenant, default). Whole-word matches only ("warranty" is not "warrant"); a negated term ("no default", "without escrow") does not fire; `note_screen.exempt` lists per event type the terms that row's own rule already handles (lock-up on a listing, warrant on an ownership adjustment, escrow/holdback on a distribution), and a term that names the event type itself ("Earn-out True-up") is never re-raised. Family `notes`, its own: a note the columns cannot hold plus a treatment question are two independent reasons. **Never parses a note into a number** — it exists only to guarantee a human reads that sentence. |
| **X-110** | Ownership moved with no price event | REVIEW | M-013: confirm the cap table. |
| **X-111** | Cash distribution received | MONITOR | M-022: stake unchanged, realized up. |
| **X-112** | Consideration was shares | BLOCK | M-024: confirm the acquirer, whether it is listed, the share count and any lock-up. |
| **X-113** | Listed position has no measurement-date price | BLOCK | M-041 with no quote: supply the close. |
| **X-114** | Announced deal fell through | REVIEW | M-051: mark reverted to the last round — confirm nothing about the round basis has changed. |
| **X-115** | Note repaid | REVIEW | M-061: if the note sat inside the prior mark, reduce the carrying basis by the principal. |
| **X-116** | Chapter 11 | BLOCK | M-025: estimate recovery; the carrying value is almost certainly impaired. |
| **X-117** | HC-led round | REVIEW | M-010/011/012 when Notes/Detail say `led by HC`, `HC led`, `HC-led`, `Human Capital led`: a related-party price is not arm's-length. Confirm an independent investor set or validated it. Family `related_party`. |
| **X-118** | Insider-led round | MONITOR / REVIEW | Priced round marked `insider-led` / `insider round` and not HC-led. Weaker evidence than a new lead; nothing to decide — unless the round re-priced the company by `indications.insider_round_review_step_up` (2×) or more with no new investor testing it, when a reviewer could reasonably book less and "hold the prior mark" is offered. Family `related_party`. |
| **X-119** | Cheque price mismatch | REVIEW | M-010: HC's cheque implies a different post-money than the row states (`hc_investment ÷ Δownership` vs `post_money`, outside `indications.cheque_price_tolerance` = 10%, only when Δownership ≥ `cheque_check_min_ownership_delta` = 1pp). One of the two cells is wrong or HC bought at a different price; "book at the cheque price" is a priced option. Family `treatment`. → Willowmere (scenario 11). |
| **X-122** | Outsized step-up | MONITOR / REVIEW | M-010: the round re-priced the company by `indications.step_up_review_at` (3×) or more. MONITOR when the notes name a new lead or outside investor (the price was tested); REVIEW otherwise, with "hold the prior mark" offered. Family `treatment`. |
| **X-123** | Stake rose without a cheque | REVIEW | M-010: HC's ownership after the round is at least `indications.cheque_check_min_ownership_delta` (1pp) above the book's ownership with no HC investment on the row. Anti-dilution, a ratchet or a warrant exercise does that; so does a wrong cell, and the row cannot say which. "Book at the prior stake against the new post-money" is a priced option. Family `treatment`. X-103 (dilution) screens the other direction. |
| **X-120** | New position entered at cost | MONITOR | M-014. |
| **X-121** | Secondary purchase at the last-round price | MONITOR | M-031 with the implied price inside tolerance; outside it X-104 REVIEW carries the spread. |
| **X-918** | New investment for a company not in the book | REVIEW | M-014 created the position; add the row to the Portfolio tab and confirm the entry terms. |
| **X-201/202** | Stale round | MONITOR >24mo / REVIEW >48mo | M-011 extensions do not reset the clock |
| **X-301/302** | ARR contraction | MONITOR <0% / REVIEW <−15% | |
| **X-303/304** | Runway | MONITOR <12mo / REVIEW <6mo | Recomputed from cash/burn **and aged 1 month** — metrics are as of late August. A financing that closed this quarter (priced round, funded note, new investment) is named on the flag with its date and HC's cheque: the workbook carries HC's cheque, not the round size, so the screen says the cash figure may predate the raise rather than guessing a post-raise number (Duskfern: 4.1 months, note closed 28 Aug). |
| **X-401/402** | Mark vs performance | MONITOR | Implied post / ARR outside the bounds; fires **both directions** (over- and under-marked). Policy 0.2 ships `mode: relative_to_comps`, gated (`require_live_comps`) to sectors whose comps are an observed public history: there the bounds are 2.0× / 0.5× the live sector median; a sector on the fixture, or with no basket, keeps the absolute 30× / 3×. Every flag records which (`basis`). |
| **X-403** | ARR below screening floor | MONITOR | ARR < $0.5M — multiple is meaningless, own bucket |
| **X-404** | MOIC outlier on stale round | MONITOR | MOIC > 5× on a round older than 24 months |
| **X-405** | Mark no longer squares with performance | REVIEW | Price anchor older than 24 months **and** a live screen against it (X-401, X-402, X-404 or X-301), unless X-202 / X-302 already put the position in REVIEW. Each half alone is MONITOR; together a reviewer could change the number. `performance_gap.enabled` |

#### Why these numbers

Every threshold is a policy choice and lives in `rules/2026Q3.yaml`; these are the reasons behind the defaults, so the committee can defend or move them.

- **X-104, 5% spread.** A secondary print within 5% of the last round is the same price with negotiation noise; beyond it the market is saying something about the round, and a reviewer should decide whether the remainder follows it.
- **X-201 / X-202, 24 / 48 months.** Venture companies at these stages raise every 18–24 months, so 24 months is one funding cycle — a price that is merely due for refresh — and 48 months is two: the company has twice not repriced, and the round probably predates the business it now describes. Age is a duration, `days ÷ 30.4375` to one decimal, compared strictly: a round dated 2022-09-02 is 48.9 months old on 2026-09-30 and is REVIEW (Knollward); calendar-month arithmetic would have called it 48 and let it slip under the threshold.
- **X-301 / X-302, 0% / −15%.** Any contraction in a growth company is worth noticing; −15% is roughly one lost growth cohort and the point at which the last round's growth assumptions no longer hold, so the mark could move.
- **X-303 / X-304, 12 / 6 months.** Twelve months of runway is one raise cycle — the company must be in market within the quarter; six months means it must close before the next measurement date or fail, which a reviewer may need to reflect in the mark.
- **X-401 / X-402, 2.0× / 0.5× the live sector median, else 30× / 3×.** Against an observed public history the screen asks whether a private mark sits at twice — or half — what the public market pays for the same kind of business today, the question a reviewer actually asks; the absolute bounds are the fallback where no live basket exists: 30× revenue is the 2021-peak ceiling — a multiple the public market has not paid at scale since — and 3× is a mature-SaaS floor below which a growth-stage mark is probably stale-low. Both are MONITOR because a multiple is a screen, not a valuation. The queue counts in this document are the stub run; under `--provider live` the screens on live sectors re-bound and the MONITOR / X-405 counts move with them.
- **X-404, 5× MOIC on a round older than 24 months.** A five-times unrealised gain resting on a price nobody has tested in over a funding cycle is where a write-up is most likely to be optimistic; it is context until something else disagrees with the mark.
- **X-405.** The rationale is in the row above: staleness is not evidence of a move and a screen is not a valuation, so each stays MONITOR; both together are the case the policy exists for.
- **`review_rules_to_block: 2`.** One judgment call is a reviewer's job; two independent ones on the same position mean the number should not be booked without the committee, because the reviewer would be deciding them jointly and nobody would see the pair.
| **X-9xx** | Ingestion integrity | BLOCK | Unknown company (X-901), missing post-money / ownership / deal value (X-902), a number outside its domain (X-903: ownership outside 0–100%, a post-money or price ≤ 0, negative proceeds or investment), **prior-mark reconciliation** (X-904, ±$0.05M; a departure the prior quarter's sidecar explains is a non-blocking REVIEW), an event dated after the measurement date or more than `tolerances.late_event_grace_days` before the window (X-905 BLOCK; inside the grace period it is applied on REVIEW), a duplicated Portfolio row (X-906 on **every** copy — the engine cannot know which is the position), activity on a terminal company (X-907; a `Distribution` on an Acquired company and a `Distribution` / `Note Repaid` on a Shut Down company are allowed), unrecognised event type (X-909, routed to M-999), a `Latest Round` dated after the measurement date (X-921). Normalization records X-911…X-920 (training/SPEC.md §2). |
| **X-900** | Row refused, position blocked | BLOCK | **A row that blocks blocks its position.** An activity row (or the position's own Portfolio row) carrying a blocking X-9xx issue is recorded in the audit chain as *not applied* and the prior mark is carried; the engine will not book a number from a cell it could not read. The same for a row that contradicts the position's own history — a financing on a company the book already shows as acquired, a round dated after this quarter's shutdown: recorded, not applied, blocked until the date or the event is corrected (a term sheet after an exit is set aside quietly, since nothing about it could have moved the mark). The one exception is an unrecognised or ambiguous event type, which still reaches M-999 so the adjudication proposal is raised. The flag names the row and the issue ids to fix. A blank or unreadable Date refuses its row this way rather than the whole workbook. |
| **X-923** | Row applied on a corrected reading | REVIEW | The row was applied, but on a reading ingest had to correct — `5.5` taken as 5.5% (X-916), a row dated inside `tolerances.late_event_grace_days` before the window (X-905). The mark moved on that reading and nobody has confirmed it; "confirm the reading" and "hold the prior mark until the cell is fixed" are the options. Family `data`. |
| **X-911** | Header matched by normalization | MONITOR | Case, whitespace, a known alias (`Carrying Value` → `Prior Mark ($M)`) or a typo ≤ 2 edits. Message carries `original → canonical`. |
| **X-912** | Event type matched by synonym or typo | MONITOR | `Series B` → `Priced Equity Round`, `Aquisition (Closed)` → `Acquisition (Closed)` (distance 1). Typo tolerance needs ≥ 6 characters and a unique best match; the raw text is kept in `Event.extra["raw_event_type"]`. |
| **X-913** | Company matched by normalization | MONITOR | Case, whitespace, corporate suffix (`Inc.`, `Ltd`, `LLC`, `Corp`, `plc`), `X (formerly Y)`, or a typo ≤ 1 on names ≥ 8 characters. |
| **X-914** | Ambiguous match | BLOCK | ≥ 2 candidates within tolerance for an event type (`Acquisition`, `Sale`, `LOI`), a company, a header, or an activity sheet; a typo match on a token too short to trust; or a company typo-match that another book name extends (`Aravin` when the book holds both `Aravine` and `Aravine Labs`). Names every candidate; never guessed. An exact or case-folded match is never second-guessed. |
| **X-915** | Value coerced from text | MONITOR | `$28.2M`, `5.5%`, `(1.2)`, `28,200,000`, a date string, an Excel serial. `03/04/2026` is read month-first and the ambiguity noted. |
| **X-916** | Unit suspicion | REVIEW | A percent field > 1 read as percentage points (÷100); a $M field > 100,000 read as dollars (÷1e6). ARR growth is exempt from the points rule (growth above 100% is real). Carries the assumption. |
| **X-917** | Structure tolerated | MONITOR | Header found below row 1 (title rows ignored), blank rows inside the data, a `Total` / `Subtotal` row, a trailing note row. |
| **X-919** | Activity sheet matched by the relaxed rule | MONITOR | Any sheet whose name contains `activity` or `events` when nothing matches the policy regex (`Q4-2026 Activity`, `4Q26 Activity`, `Events`). The quarter label is parsed from the name when present. |
| **X-920** | Non-USD currency | BLOCK | `€ £ ¥` or `EUR GBP CHF JPY CAD AUD` in a value cell, Detail or Notes. The engine is USD-only. |

### Resulting queue (Q3 2026)

**7 BLOCK · 20 REVIEW · 39 MONITOR · 34 CLEAR** *(engine output, policy 2026Q3-0.2; the extended rule set left the blocks unchanged — X-118 also annotates the two insider-led recaps, Oakenvale and Tarnwick, which were already blocked — and X-405 moved five positions from MONITOR to REVIEW: Arcfoundry, Pinwhistle, Yarrowbank, Foxtrellis, Mirthstone)*

Blocked: Drayvenn (IPO), Gryphonel (announced), Oakenvale (recap), Tarnwick Aerospace (recap + ARR −16%), Duskfern (funded note + runway 4.1mo), Birchhollow (64mo stale + ARR −20%), **Pellagrin (flat extension + 59mo stale)**.

> The hand count in the first draft of this policy was 6 / 15 / 41 / 34, and the engine's count before X-405 was 7 / 15 / 44 / 34. The engine is stricter in two places, both correct: (1) it applies the staleness clock to companies *with* activity, so Pellagrin's same-terms extension — which by policy does not reset the clock — is a 59-month-stale round plus a treatment flag, two REVIEW families, hence BLOCK; and (2) the revenue-multiple screen uses the *new* post-money for repriced companies (Jettamar, Nimbrel), which is the basis the mark now rests on. Halcyra similarly moves to REVIEW because its 71-month-stale round is screened alongside the term-sheet disclosure.

> Note: an earlier threshold set flagged 58 of 96. The fix was compound escalation plus the "could a reviewer change the number?" test, which moved X-103, unfunded notes and term sheets down to MONITOR.

---

## 4. Layer 3 — `rules.yaml`

```yaml
quarter:      { measurement_date: 2026-09-30, prior_close: 2026-06-30 }
metrics:      { reporting_lag_months: 1 }

marking:
  secondary:   { remainder_basis: last_round }        # | secondary_price
  ipo:         { price_source: market_close, lockup_discount_pct: 0.00 }
  announced:   { treatment: probability_weighted, close_probability: 0.90 }
  convertible: { new_money_basis: cost }
  calibration: { enabled: true, min_age_months: 24, bound_pct: 0.35, require_live_history: true, round_month_tolerance: 3 }

exceptions:
  staleness:  { monitor_months: 24, review_months: 48 }
  arr_growth: { monitor_below: 0.00, review_below: -0.15 }
  runway:     { monitor_below_mo: 12, review_below_mo: 6 }
  dilution:   { monitor_relative_drop: 0.20 }
  secondary:  { spread_tolerance_pct: 0.05 }
  multiple:   { mode: absolute, absolute_high: 30, absolute_low: 3,    # mode: absolute | relative_to_comps
                high_x_comp: 2.0, low_x_comp: 0.5, min_arr: 0.5 }
  moic:       { monitor_above: 5.0 }
  performance_gap: { enabled: true }                    # X-405
  escalation: { review_rules_to_block: 2 }

tolerances:  { prior_mark_reconciliation_musd: 0.05 }
sensitivity: { multiple_shock_pct: [-0.20, 0.20],
               software_sectors: [AI/ML, Developer Tools, Enterprise SaaS, Fintech, Cybersecurity, Data & Analytics, Infrastructure] }

# forward compatibility — for quarters this policy has not seen
schema:
  activity_sheet_pattern: "^Q[1-4] \\d{4} Activity$"   # never a literal name
  unknown_event_type: block                            # never carry silently
  unknown_column: record_and_warn
  missing_required_column: fail
  unknown_sector: absolute_thresholds_and_flag
note_screen:
  terms: [escrow, holdback, earn-out, milestone, contingent, participating,
          ratchet, preference, litigation, restated, bankruptcy, conversion,
          warrant, pay-to-play, cram, cram-down, lock-up, related party, going concern,
          covenant, default]
open_items:
  announced_deal_stale_quarters: 2    # still pending this long -> escalates alone
  term_sheet_stale_quarters: 1
  note_unconverted_quarters: 3
adjudication:                         # E-09 — assist, never a dependency
  enabled: true
  auto_accept: never                  # not a threshold. there is no value here.
  cache_proposals: true               # same signature -> same draft, no re-query
  promote_after_repeats: 3            # then the queue suggests writing a rule
  allowed_fields: [ownership_before, ownership_after, post_money, deal_value,
                   proceeds, prior_mark, hc_investment, close_probability]
  allowed_operators: ["*", "/", "+", "-", "min", "max"]
```

---

## 5. Engine components (all in scope)

| ID | Component | Why it exists |
|---|---|---|
| **E-00** | Four eyes on publish | `publish.require_second_approver: true` — the person releasing the snapshot may not be the approver on any override recorded this quarter (names case-folded). Refused at the API (409) and the CLI. Segregation of duties at the one place a number leaves the back office. |
| **E-01** | Override ledger | `booked = override.booked ?? proposed`. An override that names the BLOCK rule it addresses (`rule_ids_addressed`) resolves the block — the flag stays visible, the position stops waiting, and its disposition is never below MONITOR so the decision itself remains in the queue. The missing half of human review — without it the committee's decision evaporates and the same flag re-litigates every quarter. Record: company, quarter, proposed, booked, reason, approver, created_at, rule_ids_addressed. Never mutates `proposed_mark`. |
| **E-02** | Next-quarter snapshot | Emits a Q4 Portfolio tab in the identical input schema. This quarter's output is next quarter's input; otherwise automation covers half the job. Every column keeps its own definition — `Latest Round` is the most recent priced round, a same-terms extension included — and what the column cannot carry travels in the `open_items_carry.yaml` sidecar: the deliberate mark departures X-904 accepts, the open items, and the staleness anchors an extension must not reset (Pellagrin's clock still runs from 2021-10-08 next quarter). |
| **E-03** | Run manifest + determinism | run_id = hash(sha256(input), policy_version, engine_version, decisions ledger), sha256(input), policy_version, engine_version, measurement_date, generated_at. Same input and same decisions → byte-identical output; a new override → a new run_id. |
| **E-04** | Fair value hierarchy | L1/L2/L3 per position, assigned by the marking rule. Q3: 93 active after the quarter — Drayvenn L1, 92 L3. |
| **E-05** | Fund roll-up | TVPI / DPI / RVPI per Fund I–III, plus top-10 concentration. Q3 moves DPI materially ($32.5M returned). |
| **E-06** | Golden-file test | Pins 18 event treatments, 4 queue counts, portfolio total. Prevents the quiet regression. |
| **E-07** | Open items register | Carries unfinished business across quarter boundaries — outstanding notes, pending announced deals, disclosed term sheets, lock-up expiries — each aging, each escalating on its own if unresolved too long. Q3 opens: Duskfern note, Emberfold note, Gryphonel pending close, Halcyra term sheet, Drayvenn lock-up (expires 2027-03-19). |
| **E-09** | Novel-case adjudication | When M-999 halts on something unseen, the engine drafts an opinion — closest analogous rule, proposed treatment, and the facts only a human can supply — and puts it beside the blocked position. Three outcomes: **reject** (falls back to manual override), **accept once** (applied as an E-01 override with the draft as documented reason, no rule created), **promote** (written into the next quarter's rule file with approver + `effective_from` + link to the proposal). A precedent system: settled cases mechanical, novel cases adjudicated once, decisions become precedent. |
| **E-09a** | Adjudicator constraints | (1) Never produces a mark — proposes a *rule*; the engine computes the number. (2) Formulas are a restricted expression language over a field whitelist, never executable code. (3) No auto-accept at any confidence. (4) Runs at ingest, outside `run_valuation`; proposals cached by event signature so re-runs reproduce, not re-query — determinism and golden test intact. (5) Promotion goes through git with a named approver and must leave prior quarters unchanged. (6) Optional — with no model configured, M-999 blocks exactly as before. |
| **E-08** | Rule registry + effective dating | `@rule(id, version, applies_to, severity, effective_from)`. Adding a rule = adding a function + a config entry, no engine edit. `effective_from` means a Q4 rule never silently rewrites Q3. Config is per-quarter with inheritance, so the diff between quarters *is* the policy audit trail. |

---

## 6. Q3 2026 event walkthrough

| Company | Event | Rule | Prior | Proposed | Δ | Realized | Flag |
|---|---|---|---:|---:|---:|---:|---|
| Fernwave | Series D, $1,837.9M | M-010 | 38.5 | 73.52 | +35.02 | — | — |
| Drayvenn | IPO, Nasdaq | M-040 | 80.3 | 110.07* | +29.77 | — | BLOCK |
| Cindral | Acquisition closed, $324M | M-020 | 18.2 | 0.00 | −18.20 | 28.2 | — |
| Ironquill Security | Series D, $764.2M | M-010 | 15.8 | 29.04 | +13.24 | — | MONITOR |
| Larkspell | Shutdown | M-021 | 11.4 | 0.00 | −11.40 | 0.4 | — |
| Islewind | Shutdown | M-021 | 10.0 | 0.00 | −10.00 | — | — |
| Aravine | Series B, $128.5M | M-010 | 6.9 | 13.88 | +6.98 | — | MONITOR |
| Marrowick Bio | Secondary, 30% of position | M-030 | 12.9 | 8.77 | −4.13 | 3.9 | — |
| Oakenvale | Series B recap, $37.0M | M-012 | 5.7 | 2.33 | −3.37 | — | BLOCK |
| Jettamar | Series A, $43.0M | M-010 | 2.9 | 4.77 | +1.87 | — | MONITOR |
| Nimbrel | Series A, $45.1M | M-010 | 1.2 | 3.07 | +1.87 | — | MONITOR |
| Dovelane Systems | Series B, $103.8M | M-010 | 4.1 | 5.71 | +1.61 | — | MONITOR |
| Pellagrin | Series B extension, flat | M-011 | 13.0 | 13.93 | +0.93 | — | BLOCK |
| Tarnwick Aerospace | Series A recap, $14.2M | M-012 | 2.0 | 1.14 | −0.86 | — | BLOCK |
| Gryphonel | Acquisition announced, $133M | M-050 | 3.5 | 4.66 | +1.16 | — | BLOCK |
| Duskfern | Bridge note, $133M cap | M-060 | 6.1 | 6.60 | +0.50 | — | BLOCK |
| Emberfold | Bridge note, $32M cap | M-060 | 1.8 | 1.80 | 0.00 | — | MONITOR |
| Halcyra | Term sheet, ~$50M | M-070 | 2.7 | 2.70 | 0.00 | — | REVIEW |

\* at the IPO print; booked figure comes from the 9/30 close.

**Totals:** proposed NAV **$1,184.3M** (from $1,139.3M, +3.9%) · net movement **+$45.0M** · realized in quarter **$32.5M** (cumulative $49.6M) · written off **$21.4M** (Larkspell, Islewind) · exited **$18.2M** at prior mark (Cindral, for $28.2M cash).

---

## 6b. Quarters we have not seen

This policy was written against one quarter. The honest risk is that it is *fitted* to that quarter — that it handles these eight event types and breaks, or worse quietly does the wrong thing, on the ninth. Five design decisions carry that weight; each is cheap now and expensive to retrofit.

1. **Fail loud.** An unrecognised event type BLOCKS (M-999). The difference between an engine that says "I don't know what a SPAC merger is" and one that reports an unchanged mark and looks confident doing it. Same for missing required columns, out-of-range ownership, and activity naming an unknown company.
2. **Read the notes.** A new kind of deal appears in prose long before anyone adds a column for it. X-105 screens the free text and escalates — without letting a keyword touch a number.
3. **Carry the unfinished.** E-07 keeps open items alive across quarters and ages them, so nothing spanning a boundary depends on a person remembering.
4. **Tolerate the file, not the schema.** Activity sheet located by pattern, never by literal name. New columns recorded and surfaced, never silently ignored. Missing required columns are a hard stop. Unknown sectors fall back to absolute thresholds and flag.
5. **Prove the coverage.** A test asserts every event type in the Field Definitions tab has a registered handler, so enumeration and code cannot drift. A separate fixture pack exercises what Q3 lacks: two events on one company, round-then-exit, event on a terminal company, unknown type, a note converting, a prior-quarter deal closing.

**The honest risk in E-09** is a plausible-but-wrong draft that a busy reviewer waves through. Three counterweights: every proposal must cite the existing rule it reasons by analogy from, so a weak analogy is visible; every proposal must list the facts the schema doesn't contain, which is usually where the real work is; and *accept once* is deliberately cheaper than *promote*, so the low-friction path doesn't silently create policy. After the same treatment is accepted three times, the queue suggests promoting it — by then it's a pattern, not a guess.

**What still needs a person:** a genuinely new instrument — structured secondary, continuation vehicle, token — must not be absorbed by an existing rule because it superficially resembles one. The engine's job is to notice it does not fit and stop. Adding the rule is a policy decision with a version bump, not a quiet mid-quarter code change.

---

## 7. Rules deliberately not written

- **Margin trend** — gross margin is a single point, no prior period.
- **Headcount change** — one observation, no baseline.
- **Sector drift** — sector labels do not track company names in this workbook (Marrowick Bio is tagged AI/ML, Jadewell Payments Robotics). Comps map off the `Sector` column, never the name.
- **FX** — single currency. Schema carries a currency field; no conversion logic ships unused.

---

## 8. Open decisions (defaults set, engine runs either way)

1. **Gryphonel** — probability-weight at 0.90 *(default)*, full deal value, or hold at prior?
2. **Drayvenn** — lock-up discount 0% *(default)* or a haircut for the 180-day restriction?
3. **Marrowick** — remainder at last round *(default)*; the stated print equals the round, so the alternative coincides with the proposal. Would the committee want the proceeds-implied price ($487.5M, −5.5%) treated as evidence rather than rounding?
4. **M-080 calibration** — on, gated to the live comps history (section 2b). Open question for the committee: keep it as a reviewer's suggestion, or promote the calibrated figure to the proposal for rounds older than 48 months once a quarter of live history has been reviewed?
