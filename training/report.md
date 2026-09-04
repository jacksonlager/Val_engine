# Gauntlet report

Run at 2026-09-04T07:40:28 — **44/44 scenarios green**, 1785/1785 checks passed.

| Scenario | Status | Checks | Time |
|---|---|---:|---:|
| [01_all_events_clean](#01-all-events-clean) | ✓ pass | 127/127 | 0.07s |
| [02_event_type_typos](#02-event-type-typos) | ✓ pass | 65/65 | 0.14s |
| [03_event_type_synonyms](#03-event-type-synonyms) | ✓ pass | 66/66 | 0.06s |
| [04_company_name_variants](#04-company-name-variants) | ✓ pass | 53/53 | 0.09s |
| [05_header_variants](#05-header-variants) | ✓ pass | 39/39 | 0.11s |
| [06_value_formats](#06-value-formats) | ✓ pass | 66/66 | 0.06s |
| [07_units](#07-units) | ✓ pass | 48/48 | 0.06s |
| [08_structure](#08-structure) | ✓ pass | 37/37 | 0.10s |
| [09_sheet_names](#09-sheet-names) | ✓ pass | 19/19 | 0.06s |
| [09b_sheet_names_4q26](#09b-sheet-names-4q26) | ✓ pass | 19/19 | 0.06s |
| [09c_sheet_names_events](#09c-sheet-names-events) | ✓ pass | 19/19 | 0.08s |
| [09d_sheet_names_bare](#09d-sheet-names-bare) | ✓ pass | 19/19 | 0.06s |
| [09e_sheet_names_ambiguous](#09e-sheet-names-ambiguous) | ✓ pass | 6/6 | 0.06s |
| [09f_sheet_names_activity_first](#09f-sheet-names-activity-first) | ✓ pass | 19/19 | 0.06s |
| [10_multi_event](#10-multi-event) | ✓ pass | 53/53 | 0.06s |
| [11_new_events](#11-new-events) | ✓ pass | 114/114 | 0.07s |
| [12_listed_carry](#12-listed-carry) | ✓ pass | 30/30 | 0.09s |
| [12b_listed_carry_no_quote](#12b-listed-carry-no-quote) | ✓ pass | 11/11 | 0.07s |
| [13_numeric_edges](#13-numeric-edges) | ✓ pass | 32/32 | 0.06s |
| [13b_text_in_number_cell](#13b-text-in-number-cell) | ✓ pass | 4/4 | 0.06s |
| [14_missing_required](#14-missing-required) | ✓ pass | 27/27 | 0.06s |
| [15_terminal_activity](#15-terminal-activity) | ✓ pass | 35/35 | 0.06s |
| [16_duplicates_and_dates](#16-duplicates-and-dates) | ✓ pass | 30/30 | 0.06s |
| [16b_unparseable_date](#16b-unparseable-date) | ✓ pass | 1/1 | 0.04s |
| [17_notes_language](#17-notes-language) | ✓ pass | 128/128 | 0.06s |
| [18_quarter_rollforward](#18-quarter-rollforward) | ✓ pass | 59/59 | 0.07s |
| [19_big_book](#19-big-book) | ✓ pass | 53/53 | 0.36s |
| [20_garbage_csv](#20-garbage-csv) | ✓ pass | 3/3 | 0.02s |
| [20b_garbage_no_portfolio](#20b-garbage-no-portfolio) | ✓ pass | 3/3 | 0.02s |
| [20c_garbage_headers_only](#20c-garbage-headers-only) | ✓ pass | 3/3 | 0.04s |
| [20d_garbage_empty](#20d-garbage-empty) | ✓ pass | 3/3 | 0.02s |
| [21_refused_and_applied](#21-refused-and-applied) | ✓ pass | 60/60 | 0.06s |
| [22_listed_refused](#22-listed-refused) | ✓ pass | 53/53 | 0.06s |
| [23_new_investment_refused](#23-new-investment-refused) | ✓ pass | 67/67 | 0.10s |
| [24_terminal_refused](#24-terminal-refused) | ✓ pass | 53/53 | 0.06s |
| [25_unknown_type_with_currency](#25-unknown-type-with-currency) | ✓ pass | 49/49 | 0.07s |
| [26_announced_then_refused_close](#26-announced-then-refused-close) | ✓ pass | 46/46 | 0.08s |
| [27_portfolio_edges](#27-portfolio-edges) | ✓ pass | 54/54 | 0.06s |
| [27b_portfolio_unknown_status](#27b-portfolio-unknown-status) | ✓ pass | 3/3 | 0.04s |
| [28_date_edges](#28-date-edges) | ✓ pass | 65/65 | 0.06s |
| [28b_date_serial_1900](#28b-date-serial-1900) | ✓ pass | 3/3 | 0.04s |
| [29_big_book_500](#29-big-book-500) | ✓ pass | 58/58 | 0.18s |
| [30_long_notes](#30-long-notes) | ✓ pass | 41/41 | 0.06s |
| [31_custom_rule_missing_field](#31-custom-rule-missing-field) | ✓ pass | 42/42 | 0.10s |

## Failures

None.

## 01_all_events_clean

Every canonical event type (the original 8 and the 8 new ones) exactly once, cleanly spelled, on companies that are CLEAR at carry so each rule's arithmetic and flag is checkable in isolation.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must not include X-909 | no X-909 | [] | ✓ |
| validation must not include X-901 | no X-901 | [] | ✓ |
| validation must not include X-912 | no X-912 | [] | ✓ |
| validation must not include X-913 | no X-913 | [] | ✓ |
| validation must not include X-914 | no X-914 | [] | ✓ |
| validation must not include X-902 | no X-902 | [] | ✓ |
| validation must not include X-903 | no X-903 | [] | ✓ |
| validation must not include X-907 | no X-907 | [] | ✓ |
| validation must not include X-920 | no X-920 | [] | ✓ |
| validation_blocking | False | False | ✓ |
| totals.events | 16 | 16 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: flag M-999 absent | no M-999 | [] | ✓ |
| Solvantra: flag X-102 absent | no X-102 | [] | ✓ |
| Solvantra: flag X-106 absent | no X-106 | [] | ✓ |
| Solvantra: flag X-117 absent | no X-117 | [] | ✓ |
| Solvantra: flag X-118 absent | no X-118 | [] | ✓ |
| Solvantra: ownership_after | 0.1100 | 0.1100 | ✓ |
| Solvantra: invested_after | 6.1000 | 6.1000 | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-060] | [M-060] | ✓ |
| Kilnbrook: proposed mark | 4.9000 | 4.9000 | ✓ |
| Kilnbrook: flag X-107 present | X-107 | [X-107] | ✓ |
| Kilnbrook: flag X-101 absent | no X-101 | [X-107] | ✓ |
| Kilnbrook: flag M-999 absent | no M-999 | [X-107] | ✓ |
| Kilnbrook: note_at_cost | 0.5000 | 0.5000 | ✓ |
| Kilnbrook: open item {'kind': 'convertible_note'} | present | [('convertible_note', 0, False)] | ✓ |
| Vinecroft: disposition | BLOCK | BLOCK | ✓ |
| Vinecroft: rule chain | [M-040] | [M-040] | ✓ |
| Vinecroft: proposed mark | 35.0000 | 35.0000 | ✓ |
| Vinecroft: flag X-101 present | X-101 | [X-101] | ✓ |
| Vinecroft: stage | Public | Public | ✓ |
| Vinecroft: listed | True | True | ✓ |
| Vinecroft: fv_level | 1 | 1 | ✓ |
| Vinecroft: open item {'kind': 'ipo_lockup'} | present | [('ipo_lockup', 0, False)] | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: flag X-101 absent | no X-101 | [] | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-050] | [M-050] | ✓ |
| Oxbowlane: proposed mark | 19.3500 | 19.3500 | ✓ |
| Oxbowlane: flag X-101 present | X-101 | [X-101] | ✓ |
| Oxbowlane: open item {'kind': 'pending_acquisition'} | present | [('pending_acquisition', 0, False)] | ✓ |
| Coppermoss Energy: disposition | CLEAR | CLEAR | ✓ |
| Coppermoss Energy: rule chain | [M-021] | [M-021] | ✓ |
| Coppermoss Energy: proposed mark | 0.0000 | 0.0000 | ✓ |
| Coppermoss Energy: status | Shut Down | Shut Down | ✓ |
| Coppermoss Energy: realized_quarter | 0.1000 | 0.1000 | ✓ |
| Lanternfell Space: disposition | CLEAR | CLEAR | ✓ |
| Lanternfell Space: rule chain | [M-030] | [M-030] | ✓ |
| Lanternfell Space: proposed mark | 26.1440 | 26.1440 | ✓ |
| Lanternfell Space: flag X-104 absent | no X-104 | [] | ✓ |
| Lanternfell Space: flag X-101 absent | no X-101 | [] | ✓ |
| Lanternfell Space: realized_quarter | 11.1112 | 11.1112 | ✓ |
| Lanternfell Space: ownership_after | 0.0400 | 0.0400 | ✓ |
| Willowmere Compute: disposition | MONITOR | MONITOR | ✓ |
| Willowmere Compute: rule chain | [M-070] | [M-070] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Willowmere Compute: flag X-109 present | X-109 | [X-109] | ✓ |
| Willowmere Compute: open item {'kind': 'term_sheet'} | present | [('term_sheet', 0, False)] | ✓ |
| Gorseline: disposition | MONITOR | MONITOR | ✓ |
| Gorseline: rule chain | [M-031] | [M-031] | ✓ |
| Gorseline: proposed mark | 3.6966 | 3.6966 | ✓ |
| Gorseline: flag X-121 present | X-121 | [X-121] | ✓ |
| Gorseline: flag X-104 absent | no X-104 | [X-121] | ✓ |
| Gorseline: flag M-999 absent | no M-999 | [X-121] | ✓ |
| Gorseline: ownership_after | 0.1220 | 0.1220 | ✓ |
| Gorseline: invested_after | 2.7060 | 2.7060 | ✓ |
| Dellforge: disposition | MONITOR | MONITOR | ✓ |
| Dellforge: rule chain | [M-022] | [M-022] | ✓ |
| Dellforge: proposed mark | 27.8000 | 27.8000 | ✓ |
| Dellforge: flag X-111 present | X-111 | [X-111] | ✓ |
| Dellforge: flag M-999 absent | no M-999 | [X-111] | ✓ |
| Dellforge: realized_quarter | 1.5000 | 1.5000 | ✓ |
| Dellforge: ownership_after | 0.0410 | 0.0410 | ✓ |
| Jadewell Payments: disposition | REVIEW | REVIEW | ✓ |
| Jadewell Payments: rule chain | [M-013] | [M-013] | ✓ |
| Jadewell Payments: proposed mark | 6.3200 | 6.3200 | ✓ |
| Jadewell Payments: flag X-110 present | X-110 | [X-105, X-110] | ✓ |
| Jadewell Payments: flag M-999 absent | no M-999 | [X-105, X-110] | ✓ |
| Jadewell Payments: ownership_after | 0.0800 | 0.0800 | ✓ |
| Jadewell Payments: invested_after | 4.8000 | 4.8000 | ✓ |
| Tidewell Health: disposition | MONITOR | MONITOR | ✓ |
| Tidewell Health: rule chain | [M-014] | [M-014] | ✓ |
| Tidewell Health: proposed mark | 2.0000 | 2.0000 | ✓ |
| Tidewell Health: flag X-120 present | X-120 | [X-120] | ✓ |
| Tidewell Health: flag M-999 absent | no M-999 | [X-120] | ✓ |
| Tidewell Health: flag X-918 absent | no X-918 | [X-120] | ✓ |
| Tidewell Health: ownership_after | 0.1000 | 0.1000 | ✓ |
| Tidewell Health: invested_after | 1.9000 | 1.9000 | ✓ |
| Tidewell Health: latest_post_money | 20.0000 | 20.0000 | ✓ |
| Inkmoor: disposition | REVIEW | REVIEW | ✓ |
| Inkmoor: rule chain | [M-051] | [M-051] | ✓ |
| Inkmoor: proposed mark | 2.9640 | 2.9640 | ✓ |
| Inkmoor: flag X-114 present | X-114 | [X-114] | ✓ |
| Inkmoor: flag M-999 absent | no M-999 | [X-114] | ✓ |
| Inkmoor: no open item pending_acquisition | no pending_acquisition | [] | ✓ |
| Rivenmark: disposition | REVIEW | REVIEW | ✓ |
| Rivenmark: rule chain | [M-061] | [M-061] | ✓ |
| Rivenmark: proposed mark | 2.9000 | 2.9000 | ✓ |
| Rivenmark: flag X-115 present | X-115 | [X-115] | ✓ |
| Rivenmark: flag M-999 absent | no M-999 | [X-115] | ✓ |
| Rivenmark: realized_quarter | 0.4000 | 0.4000 | ✓ |
| Rivenmark: note_at_cost | 0.0000 | 0.0000 | ✓ |
| Thornmill Systems: disposition | BLOCK | BLOCK | ✓ |
| Thornmill Systems: rule chain | [M-025] | [M-025] | ✓ |
| Thornmill Systems: proposed mark | 28.2000 | 28.2000 | ✓ |
| Thornmill Systems: flag X-116 present | X-116 | [X-116] | ✓ |
| Thornmill Systems: flag M-999 absent | no M-999 | [X-116] | ✓ |
| Thornmill Systems: status | Active | Active | ✓ |
| Thornmill Systems: fv_level | 3 | 3 | ✓ |
| Vexmoor: disposition | BLOCK | BLOCK | ✓ |
| Vexmoor: rule chain | [M-040] | [M-040] | ✓ |
| Vexmoor: proposed mark | 30.0000 | 30.0000 | ✓ |
| Vexmoor: flag X-101 present | X-101 | [X-101] | ✓ |
| Vexmoor: flag M-999 absent | no M-999 | [X-101] | ✓ |
| Vexmoor: stage | Public | Public | ✓ |
| Vexmoor: listed | True | True | ✓ |
| Vexmoor: fv_level | 1 | 1 | ✓ |

## 02_event_type_typos

The eight original event types spelled the way a human produces them under deadline: transposed letters, a dropped letter, trailing/leading spaces, mixed case. Each must resolve (X-912, never silently) and still drive the right rule. One bare "Acquisition" is ambiguous (closed or announced?) and must X-914 rather than be guessed.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-912 | X-912 | [X-912, X-914] | ✓ |
| validation must include X-914 | X-914 | [X-912, X-914] | ✓ |
| validation must not include X-901 | no X-901 | [X-912, X-914] | ✓ |
| validation must not include X-913 | no X-913 | [X-912, X-914] | ✓ |
| validation must not include X-902 | no X-902 | [X-912, X-914] | ✓ |
| validation must not include X-903 | no X-903 | [X-912, X-914] | ✓ |
| validation must not include X-907 | no X-907 | [X-912, X-914] | ✓ |
| validation X-912 containing 'Priced Equtiy Round' | ≥ 1 | 1 | ✓ |
| validation X-912 containing 'Aquisition (Closed)' | ≥ 1 | 1 | ✓ |
| validation X-912 containing 'Shutdwon' | ≥ 1 | 1 | ✓ |
| validation X-914 on Quillshade | ≥ 1 | 1 | ✓ |
| no validation X-914 on Solvantra | 0 | 0 | ✓ |
| no validation X-914 on Ambercrest | 0 | 0 | ✓ |
| totals.events | 10 | 10 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: flag M-999 absent | no M-999 | [] | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-060] | [M-060] | ✓ |
| Kilnbrook: proposed mark | 4.9000 | 4.9000 | ✓ |
| Kilnbrook: flag X-107 present | X-107 | [X-107] | ✓ |
| Kilnbrook: flag M-999 absent | no M-999 | [X-107] | ✓ |
| Vinecroft: disposition | BLOCK | BLOCK | ✓ |
| Vinecroft: rule chain | [M-040] | [M-040] | ✓ |
| Vinecroft: proposed mark | 35.0000 | 35.0000 | ✓ |
| Vinecroft: flag X-101 present | X-101 | [X-101] | ✓ |
| Vinecroft: flag M-999 absent | no M-999 | [X-101] | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: flag M-999 absent | no M-999 | [] | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-050] | [M-050] | ✓ |
| Oxbowlane: proposed mark | 19.3500 | 19.3500 | ✓ |
| Oxbowlane: flag X-101 present | X-101 | [X-101] | ✓ |
| Oxbowlane: flag M-999 absent | no M-999 | [X-101] | ✓ |
| Coppermoss Energy: disposition | CLEAR | CLEAR | ✓ |
| Coppermoss Energy: rule chain | [M-021] | [M-021] | ✓ |
| Coppermoss Energy: proposed mark | 0.0000 | 0.0000 | ✓ |
| Coppermoss Energy: flag M-999 absent | no M-999 | [] | ✓ |
| Coppermoss Energy: status | Shut Down | Shut Down | ✓ |
| Lanternfell Space: disposition | CLEAR | CLEAR | ✓ |
| Lanternfell Space: rule chain | [M-030] | [M-030] | ✓ |
| Lanternfell Space: proposed mark | 26.1440 | 26.1440 | ✓ |
| Lanternfell Space: flag M-999 absent | no M-999 | [] | ✓ |
| Lanternfell Space: flag X-104 absent | no X-104 | [] | ✓ |
| Willowmere Compute: disposition | MONITOR | MONITOR | ✓ |
| Willowmere Compute: rule chain | [M-070] | [M-070] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Willowmere Compute: flag X-109 present | X-109 | [X-109] | ✓ |
| Willowmere Compute: flag M-999 absent | no M-999 | [X-109] | ✓ |
| Palefire Labs: disposition | CLEAR | CLEAR | ✓ |
| Palefire Labs: rule chain | [M-010] | [M-010] | ✓ |
| Palefire Labs: proposed mark | 10.3500 | 10.3500 | ✓ |
| Palefire Labs: flag M-999 absent | no M-999 | [] | ✓ |
| Quillshade: disposition | BLOCK | BLOCK | ✓ |
| Quillshade: rule chain | [M-999] | [M-999] | ✓ |
| Quillshade: proposed mark | 8.9000 | 8.9000 | ✓ |
| Quillshade: flag M-999 present | M-999 | [M-999] | ✓ |

## 03_event_type_synonyms

Event types written the way analysts actually write them — "Series B", "Bridge", "Exit", "Wind down", "SAFE", "Dividend", "Escrow release", "Warrant exercise" — each must map to its canonical type (X-912, method synonym) and drive the right rule. A bare "LOI" is ambiguous (acquisition or financing?) and must X-914. The escrow release lands on Kolvani Health, which is already Acquired: a Distribution on a terminal company is allowed (no X-907).

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-912 | X-912 | [X-912, X-914] | ✓ |
| validation must include X-914 | X-914 | [X-912, X-914] | ✓ |
| validation must not include X-901 | no X-901 | [X-912, X-914] | ✓ |
| validation must not include X-907 | no X-907 | [X-912, X-914] | ✓ |
| validation must not include X-913 | no X-913 | [X-912, X-914] | ✓ |
| validation must not include X-902 | no X-902 | [X-912, X-914] | ✓ |
| validation must not include X-903 | no X-903 | [X-912, X-914] | ✓ |
| validation X-912 containing 'Series B' | ≥ 1 | 1 | ✓ |
| validation X-912 containing 'Wind down' | ≥ 1 | 1 | ✓ |
| validation X-912 containing 'SAFE' | ≥ 1 | 1 | ✓ |
| validation X-914 on Quillshade | ≥ 1 | 1 | ✓ |
| no validation X-907 on Kolvani Health | 0 | 0 | ✓ |
| totals.events | 9 | 9 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: flag M-999 absent | no M-999 | [] | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-060] | [M-060] | ✓ |
| Kilnbrook: proposed mark | 4.9000 | 4.9000 | ✓ |
| Kilnbrook: flag X-107 present | X-107 | [X-107] | ✓ |
| Kilnbrook: flag M-999 absent | no M-999 | [X-107] | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: flag M-999 absent | no M-999 | [] | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Coppermoss Energy: disposition | CLEAR | CLEAR | ✓ |
| Coppermoss Energy: rule chain | [M-021] | [M-021] | ✓ |
| Coppermoss Energy: proposed mark | 0.0000 | 0.0000 | ✓ |
| Coppermoss Energy: flag M-999 absent | no M-999 | [] | ✓ |
| Coppermoss Energy: status | Shut Down | Shut Down | ✓ |
| Ventabrook: disposition | REVIEW | REVIEW | ✓ |
| Ventabrook: rule chain | [M-060] | [M-060] | ✓ |
| Ventabrook: proposed mark | 2.6000 | 2.6000 | ✓ |
| Ventabrook: flag X-107 present | X-107 | [X-107] | ✓ |
| Ventabrook: flag M-999 absent | no M-999 | [X-107] | ✓ |
| Ventabrook: flag X-101 absent | no X-101 | [X-107] | ✓ |
| Ventabrook: note_at_cost | 0.3000 | 0.3000 | ✓ |
| Ventabrook: open item {'kind': 'convertible_note'} | present | [('convertible_note', 0, False)] | ✓ |
| Dellforge: disposition | MONITOR | MONITOR | ✓ |
| Dellforge: rule chain | [M-022] | [M-022] | ✓ |
| Dellforge: proposed mark | 27.8000 | 27.8000 | ✓ |
| Dellforge: flag X-111 present | X-111 | [X-111] | ✓ |
| Dellforge: flag M-999 absent | no M-999 | [X-111] | ✓ |
| Dellforge: realized_quarter | 1.5000 | 1.5000 | ✓ |
| Kolvani Health: disposition in | [CLEAR, MONITOR] | CLEAR | ✓ |
| Kolvani Health: chain contains M-022 | M-022 | [M-000, M-022] | ✓ |
| Kolvani Health: chain must not contain M-999 | no M-999 | [M-000, M-022] | ✓ |
| Kolvani Health: proposed mark | 0.0000 | 0.0000 | ✓ |
| Kolvani Health: flag M-999 absent | no M-999 | [] | ✓ |
| Kolvani Health: status | Acquired | Acquired | ✓ |
| Kolvani Health: realized_quarter | 0.8000 | 0.8000 | ✓ |
| Jadewell Payments: disposition | REVIEW | REVIEW | ✓ |
| Jadewell Payments: rule chain | [M-013] | [M-013] | ✓ |
| Jadewell Payments: proposed mark | 6.3200 | 6.3200 | ✓ |
| Jadewell Payments: flag X-110 present | X-110 | [X-105, X-110] | ✓ |
| Jadewell Payments: flag M-999 absent | no M-999 | [X-105, X-110] | ✓ |
| Quillshade: disposition | BLOCK | BLOCK | ✓ |
| Quillshade: rule chain | [M-999] | [M-999] | ✓ |
| Quillshade: proposed mark | 8.9000 | 8.9000 | ✓ |
| Quillshade: flag M-999 present | M-999 | [M-999] | ✓ |

## 04_company_name_variants

Company names as they arrive from a deal team: wrong case, doubled spaces, a corporate suffix, a "(formerly …)" rename, a one-letter typo. Each must resolve to the book (X-913) and drive the right rule. A fake "Aravine Labs" is added to the book so that "Aravin" sits between two candidates and must X-914 — neither Aravine nor Aravine Labs may be re-marked from that row. A second fake row "Kilnbrooks" makes "Kilnbrooke" sit at distance 1 from two book names — the ambiguity SPEC §2.3's own Damerau-Levenshtein rule produces — and must X-914 too. A genuinely unknown company still raises X-901.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-913 | X-913 | [X-901, X-913, X-914] | ✓ |
| validation must include X-914 | X-914 | [X-901, X-913, X-914] | ✓ |
| validation must include X-901 | X-901 | [X-901, X-913, X-914] | ✓ |
| validation must not include X-912 | no X-912 | [X-901, X-913, X-914] | ✓ |
| validation must not include X-909 | no X-909 | [X-901, X-913, X-914] | ✓ |
| validation must not include X-907 | no X-907 | [X-901, X-913, X-914] | ✓ |
| validation X-913 containing 'Solvantra' | ≥ 1 | 1 | ✓ |
| validation X-913 containing 'Ambercrest' | ≥ 1 | 1 | ✓ |
| validation X-913 containing 'Oxbowlane' | ≥ 1 | 1 | ✓ |
| validation X-913 containing 'Willowmere' | ≥ 1 | 1 | ✓ |
| validation X-914 containing 'Aravine Labs' | ≥ 1 | 1 | ✓ |
| validation X-914 containing 'Kilnbrooks' | ≥ 1 | 1 | ✓ |
| validation X-914 on Kilnbrooke | ≥ 1 | 1 | ✓ |
| validation X-901 on Nonesuch Ventures | ≥ 1 | 1 | ✓ |
| no validation X-901 on solvantra | 0 | 0 | ✓ |
| no validation X-901 on Ambercrest Inc. | 0 | 0 | ✓ |
| no validation X-901 on Willowmere Compte | 0 | 0 | ✓ |
| totals.events | 8 | 8 | ✓ |
| totals.positions | 102 | 102 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Lanternfell Space: disposition | CLEAR | CLEAR | ✓ |
| Lanternfell Space: rule chain | [M-030] | [M-030] | ✓ |
| Lanternfell Space: proposed mark | 26.1440 | 26.1440 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-050] | [M-050] | ✓ |
| Oxbowlane: proposed mark | 19.3500 | 19.3500 | ✓ |
| Willowmere Compute: disposition | MONITOR | MONITOR | ✓ |
| Willowmere Compute: rule chain | [M-070] | [M-070] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Aravine: rule chain | [M-000] | [M-000] | ✓ |
| Aravine: proposed mark | 6.9000 | 6.9000 | ✓ |
| Aravine: ownership_after | 0.1360 | 0.1360 | ✓ |
| Aravine Labs: disposition | CLEAR | CLEAR | ✓ |
| Aravine Labs: rule chain | [M-000] | [M-000] | ✓ |
| Aravine Labs: proposed mark | 2.0000 | 2.0000 | ✓ |
| Kilnbrook: rule chain | [M-000] | [M-000] | ✓ |
| Kilnbrook: proposed mark | 4.4000 | 4.4000 | ✓ |
| Kilnbrook: flag X-107 absent | no X-107 | [] | ✓ |
| Kilnbrook: note_at_cost | 0.0000 | 0.0000 | ✓ |
| Kilnbrooks: disposition | CLEAR | CLEAR | ✓ |
| Kilnbrooks: rule chain | [M-000] | [M-000] | ✓ |
| Kilnbrooks: proposed mark | 1.2000 | 1.2000 | ✓ |
| Kilnbrooks: note_at_cost | 0.0000 | 0.0000 | ✓ |
| Nonesuch Ventures: absent from the run | absent | absent | ✓ |

## 05_header_variants

Column headers as they drift between quarters: aliases from SPEC §2.2, case and spacing changes, a transposition typo, a dropped hyphen, the columns in a different order, an extra column the schema does not know, and an optional column (Notes) missing altogether. Every header must be matched by normalization (X-911), the extra column recorded (X-910), and the four clean events must drive exactly the rules they would in a clean file.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-911 | X-911 | [X-910, X-911] | ✓ |
| validation must include X-910 | X-910 | [X-910, X-911] | ✓ |
| validation must not include X-914 | no X-914 | [X-910, X-911] | ✓ |
| validation must not include X-909 | no X-909 | [X-910, X-911] | ✓ |
| validation must not include X-901 | no X-901 | [X-910, X-911] | ✓ |
| validation must not include X-902 | no X-902 | [X-910, X-911] | ✓ |
| validation must not include X-903 | no X-903 | [X-910, X-911] | ✓ |
| validation must not include X-904 | no X-904 | [X-910, X-911] | ✓ |
| validation X-911 containing 'Investmnet' | ≥ 1 | 1 | ✓ |
| validation X-911 containing 'Carrying Value' | ≥ 1 | 1 | ✓ |
| validation X-910 containing 'Source' | ≥ 1 | 1 | ✓ |
| totals.events | 4 | 4 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: ownership_after | 0.1100 | 0.1100 | ✓ |
| Solvantra: invested_after | 6.1000 | 6.1000 | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-060] | [M-060] | ✓ |
| Kilnbrook: proposed mark | 4.9000 | 4.9000 | ✓ |
| Kilnbrook: flag X-107 present | X-107 | [X-107] | ✓ |
| Kilnbrook: note_at_cost | 0.5000 | 0.5000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Willowmere Compute: disposition | MONITOR | MONITOR | ✓ |
| Willowmere Compute: rule chain | [M-070] | [M-070] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Willowmere Compute: flag X-109 present | X-109 | [X-109] | ✓ |
| Dellforge: disposition | CLEAR | CLEAR | ✓ |
| Dellforge: rule chain | [M-000] | [M-000] | ✓ |
| Dellforge: proposed mark | 27.8000 | 27.8000 | ✓ |
| Dellforge: ownership_after | 0.0410 | 0.0410 | ✓ |
| Dellforge: invested_after | 14.4000 | 14.4000 | ✓ |

## 06_value_formats

Numbers and dates as text: "$100.0M", "400,000,000" (dollars → X-916), "11%", "(0.11)", a bare Excel serial (46266 = 2026-09-01), dates as strings in six formats, and the blank tokens ("-", "—", "n/a", "N/A", "TBD"). Every coercion must be recorded (X-915) and the arithmetic must come out exactly as it does from clean cells. The dirty representations are written verbatim into the workbook — a string stays a string.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-915 | X-915 | [X-915, X-916] | ✓ |
| validation must include X-916 | X-916 | [X-915, X-916] | ✓ |
| validation must not include X-909 | no X-909 | [X-915, X-916] | ✓ |
| validation must not include X-901 | no X-901 | [X-915, X-916] | ✓ |
| validation must not include X-902 | no X-902 | [X-915, X-916] | ✓ |
| validation must not include X-903 | no X-903 | [X-915, X-916] | ✓ |
| validation must not include X-914 | no X-914 | [X-915, X-916] | ✓ |
| validation must not include X-904 | no X-904 | [X-915, X-916] | ✓ |
| validation X-915 containing '$100.0M' | ≥ 1 | 1 | ✓ |
| validation X-915 containing '11%' | ≥ 1 | 1 | ✓ |
| validation X-915 containing '(0.11)' | ≥ 1 | 1 | ✓ |
| validation X-915 containing '46266' | ≥ 1 | 1 | ✓ |
| validation X-915 containing '14-Jul-2026' | ≥ 1 | 1 | ✓ |
| validation X-916 on Ambercrest | ≥ 1 | 1 | ✓ |
| validation_blocking | False | False | ✓ |
| totals.events | 7 | 7 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: ownership_after | 0.1100 | 0.1100 | ✓ |
| Solvantra: invested_after | 6.1000 | 6.1000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: flag X-101 absent | no X-101 | [] | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Lanternfell Space: disposition | CLEAR | CLEAR | ✓ |
| Lanternfell Space: rule chain | [M-030] | [M-030] | ✓ |
| Lanternfell Space: proposed mark | 26.1440 | 26.1440 | ✓ |
| Lanternfell Space: flag X-104 absent | no X-104 | [] | ✓ |
| Lanternfell Space: realized_quarter | 11.1112 | 11.1112 | ✓ |
| Lanternfell Space: ownership_after | 0.0400 | 0.0400 | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-060] | [M-060] | ✓ |
| Kilnbrook: proposed mark | 4.9000 | 4.9000 | ✓ |
| Kilnbrook: flag X-107 present | X-107 | [X-107] | ✓ |
| Kilnbrook: note_at_cost | 0.5000 | 0.5000 | ✓ |
| Willowmere Compute: disposition | MONITOR | MONITOR | ✓ |
| Willowmere Compute: rule chain | [M-070] | [M-070] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Willowmere Compute: flag X-109 present | X-109 | [X-109] | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-050] | [M-050] | ✓ |
| Oxbowlane: proposed mark | 19.3500 | 19.3500 | ✓ |
| Oxbowlane: flag X-101 present | X-101 | [X-101] | ✓ |
| Coppermoss Energy: disposition | CLEAR | CLEAR | ✓ |
| Coppermoss Energy: rule chain | [M-021] | [M-021] | ✓ |
| Coppermoss Energy: proposed mark | 0.0000 | 0.0000 | ✓ |
| Coppermoss Energy: status | Shut Down | Shut Down | ✓ |
| Coppermoss Energy: realized_quarter | 0.1000 | 0.1000 | ✓ |
| Vellichor Systems: disposition | MONITOR | MONITOR | ✓ |
| Vellichor Systems: rule chain | [M-000] | [M-000] | ✓ |
| Vellichor Systems: proposed mark | 11.8000 | 11.8000 | ✓ |
| Vellichor Systems: flag X-301 present | X-301 | [X-301] | ✓ |
| Yewbranch Security: rule chain | [M-000] | [M-000] | ✓ |
| Yewbranch Security: proposed mark | 2.5000 | 2.5000 | ✓ |
| Yewbranch Security: flag X-301 absent | no X-301 | [X-403] | ✓ |
| Yewbranch Security: flag X-302 absent | no X-302 | [X-403] | ✓ |
| Lumetra: disposition | CLEAR | CLEAR | ✓ |
| Lumetra: rule chain | [M-000] | [M-000] | ✓ |
| Lumetra: proposed mark | 0.4000 | 0.4000 | ✓ |
| Lumetra: invested_after | 0.5000 | 0.5000 | ✓ |

## 07_units

Right numbers, wrong units: post-money and proceeds typed in dollars instead of $M, ownership typed in percentage points instead of a fraction — in the activity tab and in the Portfolio tab. Each must be recognised (X-916, REVIEW, non-blocking, carrying the assumption) and the marks must come out identical to the clean-unit file. Nothing here may block: after the unit correction the prior-mark reconciliation (X-904) ties.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-916 | X-916 | [X-916] | ✓ |
| validation must not include X-903 | no X-903 | [X-916] | ✓ |
| validation must not include X-909 | no X-909 | [X-916] | ✓ |
| validation must not include X-901 | no X-901 | [X-916] | ✓ |
| validation must not include X-902 | no X-902 | [X-916] | ✓ |
| validation must not include X-914 | no X-914 | [X-916] | ✓ |
| validation X-916 on Solvantra | ≥ 1 | 3 | ✓ |
| validation X-916 on Ambercrest | ≥ 1 | 2 | ✓ |
| validation X-916 on Lanternfell Space | ≥ 1 | 3 | ✓ |
| validation X-916 on Rivenmark | ≥ 1 | 3 | ✓ |
| validation X-916 on Gorseline | ≥ 1 | 1 | ✓ |
| validation_blocking | False | False | ✓ |
| totals.events | 4 | 4 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: ownership_after | 0.1100 | 0.1100 | ✓ |
| Solvantra: invested_after | 6.1000 | 6.1000 | ✓ |
| Solvantra: latest_post_money | 100.0000 | 100.0000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: flag X-101 absent | no X-101 | [] | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Lanternfell Space: disposition | CLEAR | CLEAR | ✓ |
| Lanternfell Space: rule chain | [M-030] | [M-030] | ✓ |
| Lanternfell Space: proposed mark | 26.1440 | 26.1440 | ✓ |
| Lanternfell Space: flag X-104 absent | no X-104 | [] | ✓ |
| Lanternfell Space: realized_quarter | 11.1112 | 11.1112 | ✓ |
| Lanternfell Space: ownership_after | 0.0400 | 0.0400 | ✓ |
| Willowmere Compute: disposition | MONITOR | MONITOR | ✓ |
| Willowmere Compute: rule chain | [M-070] | [M-070] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Willowmere Compute: flag X-109 present | X-109 | [X-109] | ✓ |
| Willowmere Compute: alternative mark term_sheet_indicated | 7.2600 | 7.2600 | ✓ |
| Rivenmark: disposition | CLEAR | CLEAR | ✓ |
| Rivenmark: rule chain | [M-000] | [M-000] | ✓ |
| Rivenmark: proposed mark | 2.9000 | 2.9000 | ✓ |
| Rivenmark: ownership_after | 0.1200 | 0.1200 | ✓ |
| Rivenmark: latest_post_money | 23.9000 | 23.9000 | ✓ |
| Gorseline: disposition | CLEAR | CLEAR | ✓ |
| Gorseline: rule chain | [M-000] | [M-000] | ✓ |
| Gorseline: proposed mark | 3.1000 | 3.1000 | ✓ |
| Gorseline: ownership_after | 0.1020 | 0.1020 | ✓ |

## 08_structure

A workbook that has been "tidied" by a human: two title rows (the first a merged cell) above the header on both tabs, a blank row after every third data row, a "Total" row summing the money columns, and a trailing source note. The reader must find the header on row 3, skip the decoration (X-917, once per sheet, with counts), read exactly 100 positions and 5 events, and never mistake "Total" or the note for a company.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-917 | X-917 | [X-917] | ✓ |
| validation must not include X-901 | no X-901 | [X-917] | ✓ |
| validation must not include X-909 | no X-909 | [X-917] | ✓ |
| validation must not include X-902 | no X-902 | [X-917] | ✓ |
| validation must not include X-903 | no X-903 | [X-917] | ✓ |
| validation must not include X-904 | no X-904 | [X-917] | ✓ |
| validation must not include X-914 | no X-914 | [X-917] | ✓ |
| validation X-917 containing 'Total' | ≥ 1 | 2 | ✓ |
| validation X-917 containing 'blank' | ≥ 1 | 2 | ✓ |
| no validation X-901 on Total | 0 | 0 | ✓ |
| validation_blocking | False | False | ✓ |
| totals.events | 5 | 5 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Total: absent from the run | absent | absent | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-060] | [M-060] | ✓ |
| Kilnbrook: proposed mark | 4.9000 | 4.9000 | ✓ |
| Kilnbrook: flag X-107 present | X-107 | [X-107] | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-050] | [M-050] | ✓ |
| Oxbowlane: proposed mark | 19.3500 | 19.3500 | ✓ |
| Willowmere Compute: disposition | MONITOR | MONITOR | ✓ |
| Willowmere Compute: rule chain | [M-070] | [M-070] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Zerocrest: rule chain | [M-000] | [M-000] | ✓ |
| Zerocrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Zerocrest: status | Shut Down | Shut Down | ✓ |

## 09_sheet_names

The activity tab named "Q3'26 Activity" and the portfolio tab named "Book": neither matches the policy regex or the configured name, both must be found by the relaxed rules (X-919 for the activity sheet) and the run must be identical to a clean file.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-919 | X-919 | [X-919] | ✓ |
| validation must not include X-914 | no X-914 | [X-919] | ✓ |
| validation must not include X-901 | no X-901 | [X-919] | ✓ |
| validation must not include X-909 | no X-909 | [X-919] | ✓ |
| validation must not include X-902 | no X-902 | [X-919] | ✓ |
| validation X-919 containing "Q3'26 Activity" | ≥ 1 | 1 | ✓ |
| totals.events | 2 | 2 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| manifest.quarter_label | Q3 2026 | Q3 2026 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |

## 09b_sheet_names_4q26

Activity tab "4Q26 Activity" (bank-style quarter label) and portfolio tab "positions" (lower case, a synonym).

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-919 | X-919 | [X-919] | ✓ |
| validation must not include X-914 | no X-914 | [X-919] | ✓ |
| validation must not include X-901 | no X-901 | [X-919] | ✓ |
| validation must not include X-909 | no X-909 | [X-919] | ✓ |
| validation must not include X-902 | no X-902 | [X-919] | ✓ |
| validation X-919 containing '4Q26 Activity' | ≥ 1 | 1 | ✓ |
| totals.events | 2 | 2 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| manifest.quarter_label | Q3 2026 | Q3 2026 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |

## 09c_sheet_names_events

Activity tab "Q3 2026 Events" — the folded name contains "events" — and portfolio tab "Holdings".

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-919 | X-919 | [X-919] | ✓ |
| validation must not include X-914 | no X-914 | [X-919] | ✓ |
| validation must not include X-901 | no X-901 | [X-919] | ✓ |
| validation must not include X-909 | no X-909 | [X-919] | ✓ |
| validation must not include X-902 | no X-902 | [X-919] | ✓ |
| validation X-919 containing 'Q3 2026 Events' | ≥ 1 | 1 | ✓ |
| totals.events | 2 | 2 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| manifest.quarter_label | Q3 2026 | Q3 2026 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |

## 09d_sheet_names_bare

A bare "Activity" tab (no quarter in the name: the label comes from the policy) and a portfolio tab whose name carries stray whitespace and case.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-919 | X-919 | [X-919] | ✓ |
| validation must not include X-914 | no X-914 | [X-919] | ✓ |
| validation must not include X-901 | no X-901 | [X-919] | ✓ |
| validation must not include X-909 | no X-909 | [X-919] | ✓ |
| validation must not include X-902 | no X-902 | [X-919] | ✓ |
| validation X-919 containing 'Activity' | ≥ 1 | 1 | ✓ |
| totals.events | 2 | 2 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| manifest.quarter_label | Q3 2026 | Q3 2026 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |

## 09e_sheet_names_ambiguous

Two activity-like tabs ("Q3-2026 Activity" and "Activity Q3 2026"), neither matching the policy regex exactly. The relaxed sheet discovery finds two candidates and must X-914 (BLOCK, naming both) rather than pick one. The file still opens: this is a validation block, not a crash.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-914 | X-914 | [X-914] | ✓ |
| validation X-914 containing 'Q3-2026 Activity' | ≥ 1 | 1 | ✓ |
| validation X-914 containing 'Activity Q3 2026' | ≥ 1 | 1 | ✓ |
| validation_blocking | True | [X-914:Q3-2026 Activity] | ✓ |

## 09f_sheet_names_activity_first

Activity tab "Activity Q3 2026" (word order reversed) and portfolio tab "Portfolio Tab".

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-919 | X-919 | [X-919] | ✓ |
| validation must not include X-914 | no X-914 | [X-919] | ✓ |
| validation must not include X-901 | no X-901 | [X-919] | ✓ |
| validation must not include X-909 | no X-909 | [X-919] | ✓ |
| validation must not include X-902 | no X-902 | [X-919] | ✓ |
| validation X-919 containing 'Activity Q3 2026' | ≥ 1 | 1 | ✓ |
| totals.events | 2 | 2 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| manifest.quarter_label | Q3 2026 | Q3 2026 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |

## 10_multi_event

Companies with more than one event in the quarter, applied chronologically: round then round, round then closed exit, note then round (the note converts and its open item and cost leg are extinguished), announced then closed (the announcement is superseded), shutdown then a stray later term sheet (suppressed, nothing leaks), secondary sale then round (the remainder is repriced by the round).

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must not include X-901 | no X-901 | [] | ✓ |
| validation must not include X-909 | no X-909 | [] | ✓ |
| validation must not include X-906 | no X-906 | [] | ✓ |
| validation must not include X-907 | no X-907 | [] | ✓ |
| validation must not include X-902 | no X-902 | [] | ✓ |
| validation must not include X-903 | no X-903 | [] | ✓ |
| totals.events | 12 | 12 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010, M-010] | [M-010, M-010] | ✓ |
| Solvantra: proposed mark | 10.5000 | 10.5000 | ✓ |
| Solvantra: flag X-106 absent | no X-106 | [] | ✓ |
| Solvantra: flag X-102 absent | no X-102 | [] | ✓ |
| Solvantra: ownership_after | 0.1000 | 0.1000 | ✓ |
| Solvantra: invested_after | 6.1000 | 6.1000 | ✓ |
| Solvantra: latest_post_money | 105.0000 | 105.0000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-010, M-020] | [M-010, M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: flag X-101 absent | no X-101 | [] | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 18.0000 | 18.0000 | ✓ |
| Ambercrest: invested_after | 6.6000 | 6.6000 | ✓ |
| Kilnbrook: rule chain | [M-060, M-010] | [M-060, M-010] | ✓ |
| Kilnbrook: proposed mark | 6.7500 | 6.7500 | ✓ |
| Kilnbrook: flag X-107 present | X-107 | [X-107] | ✓ |
| Kilnbrook: ownership_after | 0.0750 | 0.0750 | ✓ |
| Kilnbrook: invested_after | 2.5000 | 2.5000 | ✓ |
| Kilnbrook: note_at_cost | 0.0000 | 0.0000 | ✓ |
| Kilnbrook: equity_mark | 6.7500 | 6.7500 | ✓ |
| Kilnbrook: no open item convertible_note | no convertible_note | [] | ✓ |
| Oxbowlane: disposition | CLEAR | CLEAR | ✓ |
| Oxbowlane: rule chain | [M-000, M-020] | [M-000, M-020] | ✓ |
| Oxbowlane: proposed mark | 0.0000 | 0.0000 | ✓ |
| Oxbowlane: flag X-101 absent | no X-101 | [] | ✓ |
| Oxbowlane: status | Acquired | Acquired | ✓ |
| Oxbowlane: realized_quarter | 21.5000 | 21.5000 | ✓ |
| Oxbowlane: open items count | 0 | 0 | ✓ |
| Coppermoss Energy: disposition | CLEAR | CLEAR | ✓ |
| Coppermoss Energy: rule chain | [M-021, M-000] | [M-021, M-000] | ✓ |
| Coppermoss Energy: proposed mark | 0.0000 | 0.0000 | ✓ |
| Coppermoss Energy: flag X-109 absent | no X-109 | [] | ✓ |
| Coppermoss Energy: status | Shut Down | Shut Down | ✓ |
| Coppermoss Energy: open items count | 0 | 0 | ✓ |
| Lanternfell Space: disposition | CLEAR | CLEAR | ✓ |
| Lanternfell Space: rule chain | [M-030, M-010] | [M-030, M-010] | ✓ |
| Lanternfell Space: proposed mark | 30.4000 | 30.4000 | ✓ |
| Lanternfell Space: flag X-104 absent | no X-104 | [] | ✓ |
| Lanternfell Space: realized_quarter | 11.1112 | 11.1112 | ✓ |
| Lanternfell Space: ownership_after | 0.0380 | 0.0380 | ✓ |
| Lanternfell Space: latest_post_money | 800.0000 | 800.0000 | ✓ |

## 11_new_events

The eight new canonical types with checkable arithmetic, including the variants that change the flag: a secondary purchase above the round price (X-104 instead of X-121), a distribution and a note repayment on companies already Shut Down (allowed, no X-907), an option-pool expansion with no cash, a New Investment into a company the book does not have (position created, X-918, fund from Detail), a stock-consideration exit (M-024, X-112, not terminal), an HC-led round (X-117), an insider-led round (X-118), and a round priced in euros (X-920 — the engine is USD-only; the row blocks).

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-920 | X-920 | [X-902, X-918, X-920] | ✓ |
| validation must not include X-901 | no X-901 | [X-902, X-918, X-920] | ✓ |
| validation must not include X-909 | no X-909 | [X-902, X-918, X-920] | ✓ |
| validation must not include X-914 | no X-914 | [X-902, X-918, X-920] | ✓ |
| validation must not include X-912 | no X-912 | [X-902, X-918, X-920] | ✓ |
| validation must not include X-913 | no X-913 | [X-902, X-918, X-920] | ✓ |
| validation X-920 on Harrowgate Bio | ≥ 1 | 1 | ✓ |
| no validation X-907 on Everbrook Analytics | 0 | 0 | ✓ |
| no validation X-907 on Zerocrest | 0 | 0 | ✓ |
| no validation X-901 on Brightmoor Health | 0 | 0 | ✓ |
| X-918 raised (validation or flag) | X-918 | [X-918] | ✓ |
| totals.events | 16 | 16 | ✓ |
| totals.positions | 101 | 101 | ✓ |
| Gorseline: disposition | REVIEW | REVIEW | ✓ |
| Gorseline: rule chain | [M-031] | [M-031] | ✓ |
| Gorseline: proposed mark | 3.6966 | 3.6966 | ✓ |
| Gorseline: flag X-104 present | X-104 | [X-104] | ✓ |
| Gorseline: flag X-121 absent | no X-121 | [X-104] | ✓ |
| Gorseline: flag M-999 absent | no M-999 | [X-104] | ✓ |
| Gorseline: ownership_after | 0.1220 | 0.1220 | ✓ |
| Gorseline: invested_after | 2.8000 | 2.8000 | ✓ |
| Gorseline: alternative mark at_implied_price | 4.2700 | 4.2700 | ✓ |
| Dellforge: disposition | MONITOR | MONITOR | ✓ |
| Dellforge: rule chain | [M-022] | [M-022] | ✓ |
| Dellforge: proposed mark | 27.8000 | 27.8000 | ✓ |
| Dellforge: flag X-111 present | X-111 | [X-111] | ✓ |
| Dellforge: realized_quarter | 1.5000 | 1.5000 | ✓ |
| Everbrook Analytics: disposition in | [CLEAR, MONITOR] | CLEAR | ✓ |
| Everbrook Analytics: chain contains M-022 | M-022 | [M-000, M-022] | ✓ |
| Everbrook Analytics: chain must not contain M-999 | no M-999 | [M-000, M-022] | ✓ |
| Everbrook Analytics: proposed mark | 0.0000 | 0.0000 | ✓ |
| Everbrook Analytics: status | Shut Down | Shut Down | ✓ |
| Everbrook Analytics: realized_quarter | 0.2000 | 0.2000 | ✓ |
| Jadewell Payments: disposition | REVIEW | REVIEW | ✓ |
| Jadewell Payments: rule chain | [M-013] | [M-013] | ✓ |
| Jadewell Payments: proposed mark | 6.3200 | 6.3200 | ✓ |
| Jadewell Payments: flag X-110 present | X-110 | [X-105, X-110] | ✓ |
| Jadewell Payments: ownership_after | 0.0800 | 0.0800 | ✓ |
| Jadewell Payments: invested_after | 4.8000 | 4.8000 | ✓ |
| Saffronwell: disposition | REVIEW | REVIEW | ✓ |
| Saffronwell: rule chain | [M-013] | [M-013] | ✓ |
| Saffronwell: proposed mark | 1.0608 | 1.0608 | ✓ |
| Saffronwell: flag X-110 present | X-110 | [X-110] | ✓ |
| Saffronwell: ownership_after | 0.0680 | 0.0680 | ✓ |
| Saffronwell: invested_after | 2.9000 | 2.9000 | ✓ |
| Tidewell Health: disposition | MONITOR | MONITOR | ✓ |
| Tidewell Health: rule chain | [M-014] | [M-014] | ✓ |
| Tidewell Health: proposed mark | 2.0000 | 2.0000 | ✓ |
| Tidewell Health: flag X-120 present | X-120 | [X-120] | ✓ |
| Tidewell Health: flag X-918 absent | no X-918 | [X-120] | ✓ |
| Tidewell Health: invested_after | 1.9000 | 1.9000 | ✓ |
| Brightmoor Health: disposition in | [MONITOR, REVIEW] | REVIEW | ✓ |
| Brightmoor Health: rule chain | [M-014] | [M-014] | ✓ |
| Brightmoor Health: proposed mark | 1.2000 | 1.2000 | ✓ |
| Brightmoor Health: flag X-120 present | X-120 | [X-120, X-918] | ✓ |
| Brightmoor Health: flag M-999 absent | no M-999 | [X-120, X-918] | ✓ |
| Brightmoor Health: status | Active | Active | ✓ |
| Brightmoor Health: fund | Fund III | Fund III | ✓ |
| Brightmoor Health: sector | Healthcare | Healthcare | ✓ |
| Brightmoor Health: ownership_after | 0.1000 | 0.1000 | ✓ |
| Brightmoor Health: invested_after | 1.2000 | 1.2000 | ✓ |
| Inkmoor: disposition | REVIEW | REVIEW | ✓ |
| Inkmoor: rule chain | [M-051] | [M-051] | ✓ |
| Inkmoor: proposed mark | 2.9640 | 2.9640 | ✓ |
| Inkmoor: flag X-114 present | X-114 | [X-114] | ✓ |
| Rivenmark: disposition | REVIEW | REVIEW | ✓ |
| Rivenmark: rule chain | [M-061] | [M-061] | ✓ |
| Rivenmark: proposed mark | 2.9000 | 2.9000 | ✓ |
| Rivenmark: flag X-115 present | X-115 | [X-115] | ✓ |
| Rivenmark: realized_quarter | 0.4000 | 0.4000 | ✓ |
| Rivenmark: note_at_cost | 0.0000 | 0.0000 | ✓ |
| Zerocrest: disposition in | [CLEAR, MONITOR, REVIEW] | CLEAR | ✓ |
| Zerocrest: chain contains M-061 | M-061 | [M-000, M-061] | ✓ |
| Zerocrest: chain must not contain M-999 | no M-999 | [M-000, M-061] | ✓ |
| Zerocrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Zerocrest: status | Shut Down | Shut Down | ✓ |
| Zerocrest: realized_quarter | 0.0500 | 0.0500 | ✓ |
| Thornmill Systems: disposition | BLOCK | BLOCK | ✓ |
| Thornmill Systems: rule chain | [M-025] | [M-025] | ✓ |
| Thornmill Systems: proposed mark | 28.2000 | 28.2000 | ✓ |
| Thornmill Systems: flag X-116 present | X-116 | [X-116] | ✓ |
| Thornmill Systems: status | Active | Active | ✓ |
| Vexmoor: disposition | BLOCK | BLOCK | ✓ |
| Vexmoor: rule chain | [M-040] | [M-040] | ✓ |
| Vexmoor: proposed mark | 30.0000 | 30.0000 | ✓ |
| Vexmoor: flag X-101 present | X-101 | [X-101] | ✓ |
| Vexmoor: flag M-999 absent | no M-999 | [X-101] | ✓ |
| Vexmoor: listed | True | True | ✓ |
| Vexmoor: fv_level | 1 | 1 | ✓ |
| Covebright: disposition | BLOCK | BLOCK | ✓ |
| Covebright: rule chain | [M-024] | [M-024] | ✓ |
| Covebright: proposed mark | 19.6000 | 19.6000 | ✓ |
| Covebright: flag X-112 present | X-112 | [X-112] | ✓ |
| Covebright: flag M-999 absent | no M-999 | [X-112] | ✓ |
| Covebright: status | Active | Active | ✓ |
| Covebright: stage | Acquired (stock) | Acquired (stock) | ✓ |
| Covebright: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Covebright: latest_post_money | 350.0000 | 350.0000 | ✓ |
| Covebright: open item {'kind': 'acquirer_shares'} | present | [('acquirer_shares', 0, False)] | ✓ |
| Willowmere Compute: disposition | REVIEW | REVIEW | ✓ |
| Willowmere Compute: rule chain | [M-010] | [M-010] | ✓ |
| Willowmere Compute: proposed mark | 9.8000 | 9.8000 | ✓ |
| Willowmere Compute: flag X-117 present | X-117 | [X-117] | ✓ |
| Willowmere Compute: flag X-118 absent | no X-118 | [X-117] | ✓ |
| Willowmere Compute: invested_after | 8.0000 | 8.0000 | ✓ |
| Palefire Labs: disposition | MONITOR | MONITOR | ✓ |
| Palefire Labs: rule chain | [M-010] | [M-010] | ✓ |
| Palefire Labs: proposed mark | 10.3500 | 10.3500 | ✓ |
| Palefire Labs: flag X-118 present | X-118 | [X-118] | ✓ |
| Palefire Labs: flag X-117 absent | no X-117 | [X-118] | ✓ |
| Harrowgate Bio: disposition | BLOCK | BLOCK | ✓ |
| Harrowgate Bio: flag X-117 absent | no X-117 | [X-900] | ✓ |

## 12_listed_carry

The emitted Q4 book (base: snapshot:2026Q3) run under a 2026Q4 policy. Drayvenn listed in Q3 and has no Q4 event: a public position is worth its measurement-date close, not last quarter's number, so the carry side must apply M-041 with the stub quote (seeded to the market cap the book carries, $3,931M → 2.8% × 3,931 = 110.068), Level 1, no staleness flag. The two prior marks that deliberately depart from ownership × last round (Duskfern's note leg, Gryphonel's probability-weighted deal) are explained by the sidecar and must not block.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must not include X-901 | no X-901 | [X-904] | ✓ |
| validation must not include X-909 | no X-909 | [X-904] | ✓ |
| validation must not include X-902 | no X-902 | [X-904] | ✓ |
| validation must not include X-903 | no X-903 | [X-904] | ✓ |
| validation X-904 on Duskfern | ≥ 1 | 1 | ✓ |
| validation X-904 on Gryphonel | ≥ 1 | 1 | ✓ |
| validation_blocking | False | False | ✓ |
| totals.events | 1 | 1 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| manifest.quarter_label | Q4 2026 | Q4 2026 | ✓ |
| Drayvenn: disposition in | [CLEAR, MONITOR] | CLEAR | ✓ |
| Drayvenn: rule chain | [M-041] | [M-041] | ✓ |
| Drayvenn: proposed mark | 110.0680 | 110.0680 | ✓ |
| Drayvenn: flag X-113 absent | no X-113 | [] | ✓ |
| Drayvenn: flag X-201 absent | no X-201 | [] | ✓ |
| Drayvenn: flag X-202 absent | no X-202 | [] | ✓ |
| Drayvenn: flag M-999 absent | no M-999 | [] | ✓ |
| Drayvenn: stage | Public | Public | ✓ |
| Drayvenn: listed | True | True | ✓ |
| Drayvenn: fv_level | 1 | 1 | ✓ |
| Drayvenn: ownership_after | 0.0280 | 0.0280 | ✓ |
| Drayvenn: open item {'kind': 'ipo_lockup', 'age_quarters': 1} | present | [('ipo_lockup', 1, False)] | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Cindral: rule chain | [M-000] | [M-000] | ✓ |
| Cindral: proposed mark | 0.0000 | 0.0000 | ✓ |
| Cindral: status | Acquired | Acquired | ✓ |

## 12b_listed_carry_no_quote

Same Q4 book as 12_listed_carry, but the measurement-date quote for Drayvenn is removed from the market data. A listed position with no price must not be silently carried: the prior mark stays (110.068) and the position must BLOCK with X-113 ("supply the close").

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| manifest.quarter_label | Q4 2026 | Q4 2026 | ✓ |
| Drayvenn: disposition | BLOCK | BLOCK | ✓ |
| Drayvenn: proposed mark | 110.0680 | 110.0680 | ✓ |
| Drayvenn: flag X-113 present | X-113 | [X-113] | ✓ |
| Drayvenn: flag M-999 absent | no M-999 | [X-113] | ✓ |
| Drayvenn: listed | True | True | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |

## 13_numeric_edges

Numbers at the edge of meaning. Ownership after = 0 on a secondary (HC sold everything: mark 0, proceeds realized, nothing blocks). Ownership after = 150 (points cannot exceed 100: X-903 and the row blocks — the engine must not book 150 × post). Negative proceeds on an exit and a post-money of 0 on a priced round are data errors that must block the row, not produce a number. A deal value of 1e12 is dollars (X-916 → $1,000,000M) and the arithmetic follows.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-903 | X-903 | [X-903, X-916] | ✓ |
| validation must include X-916 | X-916 | [X-903, X-916] | ✓ |
| validation must not include X-901 | no X-901 | [X-903, X-916] | ✓ |
| validation must not include X-909 | no X-909 | [X-903, X-916] | ✓ |
| validation must not include X-914 | no X-914 | [X-903, X-916] | ✓ |
| validation X-903 on Solvantra | ≥ 1 | 1 | ✓ |
| validation * on Ambercrest | ≥ 1 | 1 | ✓ |
| validation * on Kilnbrook | ≥ 1 | 1 | ✓ |
| validation X-916 on Oxbowlane | ≥ 1 | 1 | ✓ |
| no validation X-903 on Lanternfell Space | 0 | 0 | ✓ |
| no validation * on Lanternfell Space | 0 | 0 | ✓ |
| validation_blocking | True | [X-903:Ambercrest, X-903:Kilnbrook, X-903:Solvantra] | ✓ |
| totals.events | 5 | 5 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Lanternfell Space: disposition | CLEAR | CLEAR | ✓ |
| Lanternfell Space: rule chain | [M-030] | [M-030] | ✓ |
| Lanternfell Space: proposed mark | 0.0000 | 0.0000 | ✓ |
| Lanternfell Space: flag X-104 absent | no X-104 | [] | ✓ |
| Lanternfell Space: flag X-101 absent | no X-101 | [] | ✓ |
| Lanternfell Space: realized_quarter | 37.2552 | 37.2552 | ✓ |
| Lanternfell Space: ownership_after | 0.0000 | 0.0000 | ✓ |
| Solvantra: disposition | BLOCK | BLOCK | ✓ |
| Solvantra: flag X-102 absent | no X-102 | [X-900] | ✓ |
| Ambercrest: disposition | BLOCK | BLOCK | ✓ |
| Kilnbrook: disposition | BLOCK | BLOCK | ✓ |
| Kilnbrook: flag X-102 absent | no X-102 | [X-900] | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-050] | [M-050] | ✓ |
| Oxbowlane: proposed mark | 38700.0000 | 38700.0000 | ✓ |
| Oxbowlane: flag X-101 present | X-101 | [X-101] | ✓ |

## 13b_text_in_number_cell

Prose in a number cell ("approx fifty" in Post-Money / Deal Value). SPEC §2.3 says an uncoercible value is an X-902-style BLOCK naming the cell; §2.5 lists it as a hard IngestError. Either is accepted here — what is not accepted is silently reading it as blank and marking the term sheet as if the value were simply missing. If the file ingests, the row must block and the issue must name the company; if it raises, the message must name the cell or the company.

| Check | Expected | Actual | |
|---|---|---|:-:|
| no_crash | no exception | no exception | ✓ |
| validation * on Willowmere Compute containing 'approx fifty' | ≥ 1 | 1 | ✓ |
| validation_blocking | True | [X-902:Willowmere Compute] | ✓ |
| Willowmere Compute: disposition | BLOCK | BLOCK | ✓ |

## 14_missing_required

Rows missing the one field their rule cannot do without: a priced round with no post-money, an IPO with no ownership after, a closed exit with no deal value, a note whose Detail carries no parseable cap. The first three are X-902 (BLOCK) and the position must block with its prior mark intact — the engine must not crash on float(None) and must not book a number it could not compute. The capless note is not a data error: M-060 applies, the note leg is carried at cost, and the missing cap is an X-101 REVIEW for a human to read the terms.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-902 | X-902 | [X-902] | ✓ |
| validation must not include X-901 | no X-901 | [X-902] | ✓ |
| validation must not include X-909 | no X-909 | [X-902] | ✓ |
| validation must not include X-914 | no X-914 | [X-902] | ✓ |
| validation X-902 on Solvantra | ≥ 1 | 1 | ✓ |
| validation X-902 on Vinecroft | ≥ 1 | 1 | ✓ |
| validation X-902 on Ambercrest | ≥ 1 | 1 | ✓ |
| no validation X-902 on Kilnbrook | 0 | 0 | ✓ |
| validation_blocking | True | [X-902:Ambercrest, X-902:Solvantra, X-902:Vinecroft] | ✓ |
| totals.events | 4 | 4 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | BLOCK | BLOCK | ✓ |
| Solvantra: proposed mark | 8.9000 | 8.9000 | ✓ |
| Solvantra: ownership_after | 0.1180 | 0.1180 | ✓ |
| Vinecroft: disposition | BLOCK | BLOCK | ✓ |
| Vinecroft: proposed mark | 22.3000 | 22.3000 | ✓ |
| Vinecroft: ownership_after | 0.0160 | 0.0160 | ✓ |
| Ambercrest: disposition | BLOCK | BLOCK | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-060] | [M-060] | ✓ |
| Kilnbrook: proposed mark | 4.9000 | 4.9000 | ✓ |
| Kilnbrook: flag X-107 present | X-107 | [X-101, X-107] | ✓ |
| Kilnbrook: flag X-101 present | X-101 | [X-101, X-107] | ✓ |
| Kilnbrook: note_at_cost | 0.5000 | 0.5000 | ✓ |
| Kilnbrook: open item {'kind': 'convertible_note'} | present | [('convertible_note', 0, False)] | ✓ |

## 15_terminal_activity

Activity on companies that were already Acquired or Shut Down at the prior close. Cash that arrives after an exit is normal: a Distribution on Kolvani Health (Acquired) and a Note Repaid on Everbrook Analytics (Shut Down) must be applied to realized proceeds with no X-907. Anything that pretends the company is still live — a priced round on Kolvani, a term sheet on Hearthwick, a secondary sale on Zerocrest — is X-907 (BLOCK) and must not touch the zero mark.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-907 | X-907 | [X-907] | ✓ |
| validation must not include X-901 | no X-901 | [X-907] | ✓ |
| validation must not include X-909 | no X-909 | [X-907] | ✓ |
| validation must not include X-914 | no X-914 | [X-907] | ✓ |
| validation X-907 on Kolvani Health count | 1 | 1 | ✓ |
| validation X-907 on Hearthwick count | 1 | 1 | ✓ |
| validation X-907 on Zerocrest count | 1 | 1 | ✓ |
| validation X-907 count | 3 | 3 | ✓ |
| no validation X-907 on Everbrook Analytics | 0 | 0 | ✓ |
| validation_blocking | True | [X-907:Hearthwick, X-907:Kolvani Health, X-907:Zerocrest] | ✓ |
| totals.events | 5 | 5 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Kolvani Health: chain contains M-022 | M-022 | [M-000, M-022] | ✓ |
| Kolvani Health: chain must not contain M-010 | no M-010 | [M-000, M-022] | ✓ |
| Kolvani Health: chain must not contain M-999 | no M-999 | [M-000, M-022] | ✓ |
| Kolvani Health: proposed mark | 0.0000 | 0.0000 | ✓ |
| Kolvani Health: status | Acquired | Acquired | ✓ |
| Kolvani Health: realized_quarter | 0.8000 | 0.8000 | ✓ |
| Kolvani Health: ownership_after | 0.0710 | 0.0710 | ✓ |
| Everbrook Analytics: chain contains M-061 | M-061 | [M-000, M-061] | ✓ |
| Everbrook Analytics: chain must not contain M-999 | no M-999 | [M-000, M-061] | ✓ |
| Everbrook Analytics: proposed mark | 0.0000 | 0.0000 | ✓ |
| Everbrook Analytics: status | Shut Down | Shut Down | ✓ |
| Everbrook Analytics: realized_quarter | 0.1000 | 0.1000 | ✓ |
| Hearthwick: chain must not contain M-070 | no M-070 | [M-000] | ✓ |
| Hearthwick: proposed mark | 0.0000 | 0.0000 | ✓ |
| Hearthwick: status | Acquired | Acquired | ✓ |
| Hearthwick: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Hearthwick: open items count | 0 | 0 | ✓ |
| Zerocrest: chain must not contain M-030 | no M-030 | [M-000] | ✓ |
| Zerocrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Zerocrest: status | Shut Down | Shut Down | ✓ |
| Zerocrest: realized_quarter | 0.0000 | 0.0000 | ✓ |

## 16_duplicates_and_dates

Rows a copy-paste produces: an exact duplicate of a round (X-906, and the mark must not be wrong because of it), an exit dated before the window opens (X-905), a note dated in 2030 (X-905), a date typed as "14-Aug-2026" text (X-915), and a day-first/month-first ambiguity "09/03/2026" that must be read month-first (3 September, inside the window) with an X-915 that says so.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-906 | X-906 | [X-905, X-906, X-915] | ✓ |
| validation must include X-905 | X-905 | [X-905, X-906, X-915] | ✓ |
| validation must include X-915 | X-915 | [X-905, X-906, X-915] | ✓ |
| validation must not include X-901 | no X-901 | [X-905, X-906, X-915] | ✓ |
| validation must not include X-909 | no X-909 | [X-905, X-906, X-915] | ✓ |
| validation must not include X-914 | no X-914 | [X-905, X-906, X-915] | ✓ |
| validation X-906 on Solvantra | ≥ 1 | 1 | ✓ |
| validation X-905 on Ambercrest | ≥ 1 | 1 | ✓ |
| validation X-905 on Kilnbrook containing '2030' | ≥ 1 | 1 | ✓ |
| validation X-915 on Willowmere Compute containing '14-Aug-2026' | ≥ 1 | 1 | ✓ |
| validation X-915 on Oxbowlane containing 'ambig' | ≥ 1 | 1 | ✓ |
| no validation X-905 on Oxbowlane | 0 | 0 | ✓ |
| totals.events | 6 | 6 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: chain contains M-010 | M-010 | [M-010, M-011] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: flag M-999 absent | no M-999 | [X-106] | ✓ |
| Solvantra: ownership_after | 0.1100 | 0.1100 | ✓ |
| Ambercrest: chain contains M-020 | M-020 | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Willowmere Compute: disposition | MONITOR | MONITOR | ✓ |
| Willowmere Compute: rule chain | [M-070] | [M-070] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-050] | [M-050] | ✓ |
| Oxbowlane: proposed mark | 19.3500 | 19.3500 | ✓ |

## 16b_unparseable_date

A Date cell that is prose ("sometime in August"). SPEC §2.3 says a date that does not parse blocks naming the cell; §2.5 lists it as a hard IngestError. Either is accepted; what is not accepted is a guessed date or a silent skip. If it raises, the message must name the cell or the company and must not be a traceback.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_error_names_the_cell | [sometime in August, Coppermoss, Date, A2] | sheet 'Q3 2026 Activity' row 2: 'Date' is not a date: 'sometime in August' is not a date in any accepted form (YYYY-MM-DD, MM/DD/YYYY, M/D/YY, DD-Mon-YYYY, Mon  | ✓ |

## 17_notes_language

One row per X-105 note-screen term (the thirteen the policy already lists plus the nine SPEC §3 adds: warrant, pay-to-play, cram / cram-down, lock-up, related party, going concern, covenant, default), each on a Term Sheet Signed so the mark is unchanged and the only new signal is the REVIEW that guarantees a human reads the sentence. Two controls: "lock-up" in an IPO note must NOT fire (it is the normal condition of a listing), and a clean note must not fire at all.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must not include X-901 | no X-901 | [] | ✓ |
| validation must not include X-909 | no X-909 | [] | ✓ |
| validation must not include X-914 | no X-914 | [] | ✓ |
| validation must not include X-902 | no X-902 | [] | ✓ |
| totals.events | 24 | 24 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Lumetra: disposition | REVIEW | REVIEW | ✓ |
| Lumetra: rule chain | [M-070] | [M-070] | ✓ |
| Lumetra: proposed mark | 0.4000 | 0.4000 | ✓ |
| Lumetra: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Lumetra: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Rivenmark: disposition | REVIEW | REVIEW | ✓ |
| Rivenmark: rule chain | [M-070] | [M-070] | ✓ |
| Rivenmark: proposed mark | 2.9000 | 2.9000 | ✓ |
| Rivenmark: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Rivenmark: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Solvantra: disposition | REVIEW | REVIEW | ✓ |
| Solvantra: rule chain | [M-070] | [M-070] | ✓ |
| Solvantra: proposed mark | 8.9000 | 8.9000 | ✓ |
| Solvantra: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Solvantra: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Vexmoor: disposition | REVIEW | REVIEW | ✓ |
| Vexmoor: rule chain | [M-070] | [M-070] | ✓ |
| Vexmoor: proposed mark | 22.7000 | 22.7000 | ✓ |
| Vexmoor: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Vexmoor: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Thistledown Energy: disposition | REVIEW | REVIEW | ✓ |
| Thistledown Energy: rule chain | [M-070] | [M-070] | ✓ |
| Thistledown Energy: proposed mark | 1.2000 | 1.2000 | ✓ |
| Thistledown Energy: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Thistledown Energy: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Ambercrest: disposition | REVIEW | REVIEW | ✓ |
| Ambercrest: rule chain | [M-070] | [M-070] | ✓ |
| Ambercrest: proposed mark | 10.6000 | 10.6000 | ✓ |
| Ambercrest: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Ambercrest: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Covebright: disposition | REVIEW | REVIEW | ✓ |
| Covebright: rule chain | [M-070] | [M-070] | ✓ |
| Covebright: proposed mark | 14.6000 | 14.6000 | ✓ |
| Covebright: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Covebright: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Gorseline: disposition | REVIEW | REVIEW | ✓ |
| Gorseline: rule chain | [M-070] | [M-070] | ✓ |
| Gorseline: proposed mark | 3.1000 | 3.1000 | ✓ |
| Gorseline: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Gorseline: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Inkmoor: disposition | REVIEW | REVIEW | ✓ |
| Inkmoor: rule chain | [M-070] | [M-070] | ✓ |
| Inkmoor: proposed mark | 3.0000 | 3.0000 | ✓ |
| Inkmoor: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Inkmoor: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Jadewell Payments: disposition | REVIEW | REVIEW | ✓ |
| Jadewell Payments: rule chain | [M-070] | [M-070] | ✓ |
| Jadewell Payments: proposed mark | 5.6000 | 5.6000 | ✓ |
| Jadewell Payments: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Jadewell Payments: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-070] | [M-070] | ✓ |
| Kilnbrook: proposed mark | 4.4000 | 4.4000 | ✓ |
| Kilnbrook: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Kilnbrook: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Loamfield Robotics: disposition | REVIEW | REVIEW | ✓ |
| Loamfield Robotics: rule chain | [M-070] | [M-070] | ✓ |
| Loamfield Robotics: proposed mark | 1.1000 | 1.1000 | ✓ |
| Loamfield Robotics: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Loamfield Robotics: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Palefire Labs: disposition | REVIEW | REVIEW | ✓ |
| Palefire Labs: rule chain | [M-070] | [M-070] | ✓ |
| Palefire Labs: proposed mark | 6.5000 | 6.5000 | ✓ |
| Palefire Labs: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Palefire Labs: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Quillshade: disposition | REVIEW | REVIEW | ✓ |
| Quillshade: rule chain | [M-070] | [M-070] | ✓ |
| Quillshade: proposed mark | 8.9000 | 8.9000 | ✓ |
| Quillshade: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Quillshade: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Tidewell Health: disposition | REVIEW | REVIEW | ✓ |
| Tidewell Health: rule chain | [M-070] | [M-070] | ✓ |
| Tidewell Health: proposed mark | 1.2000 | 1.2000 | ✓ |
| Tidewell Health: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Tidewell Health: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Willowmere Compute: disposition | REVIEW | REVIEW | ✓ |
| Willowmere Compute: rule chain | [M-070] | [M-070] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Willowmere Compute: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Willowmere Compute: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Coppermoss Energy: disposition | REVIEW | REVIEW | ✓ |
| Coppermoss Energy: rule chain | [M-070] | [M-070] | ✓ |
| Coppermoss Energy: proposed mark | 2.6000 | 2.6000 | ✓ |
| Coppermoss Energy: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Coppermoss Energy: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Dellforge: disposition | REVIEW | REVIEW | ✓ |
| Dellforge: rule chain | [M-070] | [M-070] | ✓ |
| Dellforge: proposed mark | 27.8000 | 27.8000 | ✓ |
| Dellforge: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Dellforge: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Gablewood: disposition | REVIEW | REVIEW | ✓ |
| Gablewood: rule chain | [M-070] | [M-070] | ✓ |
| Gablewood: proposed mark | 0.6000 | 0.6000 | ✓ |
| Gablewood: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Gablewood: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Harrowgate Bio: disposition | REVIEW | REVIEW | ✓ |
| Harrowgate Bio: rule chain | [M-070] | [M-070] | ✓ |
| Harrowgate Bio: proposed mark | 6.1000 | 6.1000 | ✓ |
| Harrowgate Bio: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Harrowgate Bio: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Lanternfell Space: disposition | REVIEW | REVIEW | ✓ |
| Lanternfell Space: rule chain | [M-070] | [M-070] | ✓ |
| Lanternfell Space: proposed mark | 37.3000 | 37.3000 | ✓ |
| Lanternfell Space: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Lanternfell Space: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Oxbowlane: disposition | REVIEW | REVIEW | ✓ |
| Oxbowlane: rule chain | [M-070] | [M-070] | ✓ |
| Oxbowlane: proposed mark | 13.0000 | 13.0000 | ✓ |
| Oxbowlane: flag X-105 present | X-105 | [X-105, X-109] | ✓ |
| Oxbowlane: flag X-109 present | X-109 | [X-105, X-109] | ✓ |
| Vinecroft: disposition | BLOCK | BLOCK | ✓ |
| Vinecroft: rule chain | [M-040] | [M-040] | ✓ |
| Vinecroft: proposed mark | 35.0000 | 35.0000 | ✓ |
| Vinecroft: flag X-101 present | X-101 | [X-101] | ✓ |
| Vinecroft: flag X-105 absent | no X-105 | [X-101] | ✓ |
| Ventabrook: disposition | MONITOR | MONITOR | ✓ |
| Ventabrook: rule chain | [M-070] | [M-070] | ✓ |
| Ventabrook: proposed mark | 2.3000 | 2.3000 | ✓ |
| Ventabrook: flag X-109 present | X-109 | [X-109] | ✓ |
| Ventabrook: flag X-105 absent | no X-105 | [X-109] | ✓ |

## 18_quarter_rollforward

The emitted Q4 book run under policy 2026Q4 with the open_items_carry.yaml sidecar. Open items carried from Q3 age by one quarter: Halcyra's term sheet (limit 1) escalates (E-07 REVIEW), Emberfold's note (limit 3) and Drayvenn's lock-up (expires 2027-03-19) do not. Gryphonel's announced deal closes (M-020 at 3.6% × $133M = 4.788 realized, every open item resolved) and Duskfern's bridge converts in a Series B (M-010: 9.0% × $150M = 13.5, the note leg and its open item gone). The run must then emit the Q1 2027 book — the year-end rollover of the quarter label is parsed, never hardcoded.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must not include X-901 | no X-901 | [X-904] | ✓ |
| validation must not include X-909 | no X-909 | [X-904] | ✓ |
| validation must not include X-902 | no X-902 | [X-904] | ✓ |
| validation must not include X-903 | no X-903 | [X-904] | ✓ |
| validation must not include X-907 | no X-907 | [X-904] | ✓ |
| validation must not include X-914 | no X-914 | [X-904] | ✓ |
| validation X-904 on Duskfern | ≥ 1 | 1 | ✓ |
| validation X-904 on Gryphonel | ≥ 1 | 1 | ✓ |
| validation_blocking | False | False | ✓ |
| totals.events | 2 | 2 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| manifest.quarter_label | Q4 2026 | Q4 2026 | ✓ |
| Gryphonel: disposition | CLEAR | CLEAR | ✓ |
| Gryphonel: rule chain | [M-020] | [M-020] | ✓ |
| Gryphonel: proposed mark | 0.0000 | 0.0000 | ✓ |
| Gryphonel: flag E-07 absent | no E-07 | [] | ✓ |
| Gryphonel: flag X-101 absent | no X-101 | [] | ✓ |
| Gryphonel: status | Acquired | Acquired | ✓ |
| Gryphonel: realized_quarter | 4.7880 | 4.7880 | ✓ |
| Gryphonel: open items count | 0 | 0 | ✓ |
| Duskfern: disposition | REVIEW | REVIEW | ✓ |
| Duskfern: rule chain | [M-010] | [M-010] | ✓ |
| Duskfern: proposed mark | 13.5000 | 13.5000 | ✓ |
| Duskfern: flag E-07 absent | no E-07 | [X-304] | ✓ |
| Duskfern: flag X-107 absent | no X-107 | [X-304] | ✓ |
| Duskfern: flag X-102 absent | no X-102 | [X-304] | ✓ |
| Duskfern: ownership_after | 0.0900 | 0.0900 | ✓ |
| Duskfern: note_at_cost | 0.0000 | 0.0000 | ✓ |
| Duskfern: no open item convertible_note | no convertible_note | [] | ✓ |
| Halcyra: disposition | BLOCK | BLOCK | ✓ |
| Halcyra: rule chain | [M-000] | [M-000] | ✓ |
| Halcyra: proposed mark | 2.7000 | 2.7000 | ✓ |
| Halcyra: flag E-07 present | E-07 | [E-07, X-202] | ✓ |
| Halcyra: open item {'kind': 'term_sheet', 'age_quarters': 1, 'escalated': True} | present | [('term_sheet', 1, True)] | ✓ |
| Emberfold: rule chain | [M-000] | [M-000] | ✓ |
| Emberfold: proposed mark | 1.8000 | 1.8000 | ✓ |
| Emberfold: flag E-07 absent | no E-07 | [X-401] | ✓ |
| Emberfold: open item {'kind': 'convertible_note', 'age_quarters': 1, 'escalated': False} | present | [('convertible_note', 1, False)] | ✓ |
| Drayvenn: flag E-07 absent | no E-07 | [] | ✓ |
| Drayvenn: listed | True | True | ✓ |
| Drayvenn: fv_level | 1 | 1 | ✓ |
| Drayvenn: open item {'kind': 'ipo_lockup', 'age_quarters': 1, 'escalated': False} | present | [('ipo_lockup', 1, False)] | ✓ |
| Marrowick Bio: disposition | CLEAR | CLEAR | ✓ |
| Marrowick Bio: rule chain | [M-000] | [M-000] | ✓ |
| Marrowick Bio: proposed mark | 8.7720 | 8.7720 | ✓ |
| Marrowick Bio: ownership_after | 0.0170 | 0.0170 | ✓ |
| Pellagrin: rule chain | [M-000] | [M-000] | ✓ |
| Pellagrin: proposed mark | 13.9277 | 13.9277 | ✓ |
| Pellagrin: flag X-202 present | X-202 | [X-202] | ✓ |
| Pellagrin: flag X-106 absent | no X-106 | [X-202] | ✓ |
| Cindral: rule chain | [M-000] | [M-000] | ✓ |
| Cindral: proposed mark | 0.0000 | 0.0000 | ✓ |
| Cindral: status | Acquired | Acquired | ✓ |
| snapshot: next quarter label | Q1 2027 | Q1 2027 | ✓ |
| snapshot: activity sheet | Q1 2027 Activity | [Portfolio, Q1 2027 Activity, Field Definitions, Open Items, Snapshot Notes] | ✓ |
| snapshot: portfolio rows | 100 | 100 | ✓ |
| snapshot: sidecar written | open_items_carry.yaml | present | ✓ |

## 19_big_book

1,000 synthetic companies (seeded, coherent: prior mark = ownership × post, so X-904 ties) and 120 events cycling the eight original types on distinct companies. Must finish in under 15 seconds and produce a manifest. Every company without an event is CLEAR by construction, so the disposition totals are exact: 30 BLOCK (15 IPOs + 15 announced deals), 15 REVIEW (funded notes), 15 MONITOR (term sheets), 940 CLEAR.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| max_seconds | < 15s | 0.3600 | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must not include X-901 | no X-901 | [] | ✓ |
| validation must not include X-909 | no X-909 | [] | ✓ |
| validation must not include X-902 | no X-902 | [] | ✓ |
| validation must not include X-903 | no X-903 | [] | ✓ |
| validation must not include X-904 | no X-904 | [] | ✓ |
| validation must not include X-906 | no X-906 | [] | ✓ |
| validation must not include X-914 | no X-914 | [] | ✓ |
| validation_blocking | False | False | ✓ |
| totals.events | 120 | 120 | ✓ |
| totals.positions | 1000 | 1000 | ✓ |
| totals.dispositions | {'BLOCK': 30, 'REVIEW': 15, 'MONITOR': 15, 'CLEAR': 940} | {'BLOCK': 30, 'REVIEW': 15, 'MONITOR': 15, 'CLEAR': 940} | ✓ |
| manifest.quarter_label | Q3 2026 | Q3 2026 | ✓ |
| manifest.policy_version | 2026Q3-0.1 | 2026Q3-0.1 | ✓ |
| Synth-0701: disposition | CLEAR | CLEAR | ✓ |
| Synth-0701: rule chain | [M-010] | [M-010] | ✓ |
| Synth-0701: proposed mark | 10.2465 | 10.2465 | ✓ |
| Synth-0045: disposition | REVIEW | REVIEW | ✓ |
| Synth-0045: rule chain | [M-060] | [M-060] | ✓ |
| Synth-0045: proposed mark | 12.5823 | 12.5823 | ✓ |
| Synth-0045: flag X-107 present | X-107 | [X-107] | ✓ |
| Synth-0045: note_at_cost | 0.3000 | 0.3000 | ✓ |
| Synth-0812: disposition | BLOCK | BLOCK | ✓ |
| Synth-0812: rule chain | [M-040] | [M-040] | ✓ |
| Synth-0812: proposed mark | 63.0928 | 63.0928 | ✓ |
| Synth-0812: fv_level | 1 | 1 | ✓ |
| Synth-0926: disposition | CLEAR | CLEAR | ✓ |
| Synth-0926: rule chain | [M-020] | [M-020] | ✓ |
| Synth-0926: proposed mark | 0.0000 | 0.0000 | ✓ |
| Synth-0926: status | Acquired | Acquired | ✓ |
| Synth-0926: realized_quarter | 58.5905 | 58.5905 | ✓ |
| Synth-0538: disposition | BLOCK | BLOCK | ✓ |
| Synth-0538: rule chain | [M-050] | [M-050] | ✓ |
| Synth-0538: proposed mark | 31.9670 | 31.9670 | ✓ |
| Synth-0125: disposition | CLEAR | CLEAR | ✓ |
| Synth-0125: rule chain | [M-021] | [M-021] | ✓ |
| Synth-0125: proposed mark | 0.0000 | 0.0000 | ✓ |
| Synth-0125: status | Shut Down | Shut Down | ✓ |
| Synth-0529: disposition | CLEAR | CLEAR | ✓ |
| Synth-0529: rule chain | [M-030] | [M-030] | ✓ |
| Synth-0529: proposed mark | 9.0754 | 9.0754 | ✓ |
| Synth-0529: flag X-104 absent | no X-104 | [] | ✓ |
| Synth-0529: realized_quarter | 9.0754 | 9.0754 | ✓ |
| Synth-0207: disposition | MONITOR | MONITOR | ✓ |
| Synth-0207: rule chain | [M-070] | [M-070] | ✓ |
| Synth-0207: proposed mark | 30.6017 | 30.6017 | ✓ |
| Synth-0207: flag X-109 present | X-109 | [X-109] | ✓ |
| Synth-0001: disposition | CLEAR | CLEAR | ✓ |
| Synth-0001: rule chain | [M-000] | [M-000] | ✓ |
| Synth-1000: disposition | CLEAR | CLEAR | ✓ |
| Synth-1000: rule chain | [M-000] | [M-000] | ✓ |

## 20_garbage_csv

A CSV renamed to .xlsx. Not a workbook: must raise IngestError saying what was found (not a zip / not an xlsx / CSV) and what was expected — never a BadZipFile traceback.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | False | False | ✓ |
| error_contains | [not a workbook, not an xlsx, not a valid, csv, zip, xlsx] | 20_garbage_csv.xlsx is not a workbook: found text that looks like CSV; expected an .xlsx file (an Excel 2007+ zip container with a Portfolio tab and a quarterly | ✓ |
| error_is_not_a_traceback | message names the problem | 20_garbage_csv.xlsx is not a workbook: found text that looks like CSV; expected  | ✓ |

## 20b_garbage_no_portfolio

A workbook with a cover sheet and an activity tab but no Portfolio tab by any name. Must raise IngestError naming the missing Portfolio sheet and listing the sheets present.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | False | False | ✓ |
| error_contains | [Portfolio] | portfolio sheet 'Portfolio' not found; sheets: ['Summary', 'Q3 2026 Activity']. Expected a tab named 'Portfolio' (or portfolio / book / positions / holdings). | ✓ |
| error_is_not_a_traceback | message names the problem | portfolio sheet 'Portfolio' not found; sheets: ['Summary', 'Q3 2026 Activity'].  | ✓ |

## 20c_garbage_headers_only

Both tabs carry only their header row. Zero activity rows is a legal empty quarter, but zero portfolio rows is not a book: must raise IngestError naming the empty Portfolio tab.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | False | False | ✓ |
| error_contains | [zero, no portfolio rows, no rows, empty, 0 rows, no positions, no data] | sheet 'Portfolio' has a header but no portfolio rows; the book cannot be empty. | ✓ |
| error_is_not_a_traceback | message names the problem | sheet 'Portfolio' has a header but no portfolio rows; the book cannot be empty. | ✓ |

## 20d_garbage_empty

A zero-byte file with an .xlsx extension. Must raise IngestError saying the file is empty / not a workbook — never a traceback.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | False | False | ✓ |
| error_contains | [empty, 0 bytes, not a workbook, zip, xlsx, not a valid] | 20d_garbage_empty.xlsx is not a workbook: found an empty file; expected an .xlsx file (an Excel 2007+ zip container with a Portfolio tab and a quarterly Activit | ✓ |
| error_is_not_a_traceback | message names the problem | 20d_garbage_empty.xlsx is not a workbook: found an empty file; expected an .xlsx | ✓ |

## 21_refused_and_applied

One company, one quarter, one row the ingest layer refused and one it accepted. The refused row must be recorded (M-000 "recorded but not applied", X-900 BLOCK) without disturbing the accepted one, in either order. Solvantra: a term sheet with a negative indicated value (X-903) then a clean Series B — mark 0.11 × 100 = 11.0, invested 5.1 + 1.0 = 6.1, no term-sheet open item. Lanternfell Space: a clean Series D (0.05 × 800 = 40.0) then a secondary whose ownership-after is 150 points (X-903) — nothing sold, nothing realized, ownership stays 0.05. Kilnbrook: a note with a negative HC investment (X-903) then a clean Series B — 0.075 × 90 = 6.75, no note leg, invested unchanged at 2.0, no X-107. Ambercrest: a clean Series C (0.045 × 300 = 13.5, invested 6.6) then a closed acquisition with a negative deal value (X-903) — the exit is not booked: still Active, nothing realized, no X-101. Every one of the four is BLOCK because of the refused row alone.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-903 | X-903 | [X-903] | ✓ |
| validation must not include X-901 | no X-901 | [X-903] | ✓ |
| validation must not include X-909 | no X-909 | [X-903] | ✓ |
| validation must not include X-914 | no X-914 | [X-903] | ✓ |
| validation must not include X-902 | no X-902 | [X-903] | ✓ |
| validation must not include X-907 | no X-907 | [X-903] | ✓ |
| validation X-903 on Solvantra count | 1 | 1 | ✓ |
| validation X-903 on Lanternfell Space count | 1 | 1 | ✓ |
| validation X-903 on Kilnbrook count | 1 | 1 | ✓ |
| validation X-903 on Ambercrest count | 1 | 1 | ✓ |
| validation_blocking | True | [X-903:Ambercrest, X-903:Kilnbrook, X-903:Lanternfell Space, X-903:Solvantra] | ✓ |
| totals.events | 8 | 8 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | BLOCK | BLOCK | ✓ |
| Solvantra: rule chain | [M-000, M-010] | [M-000, M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: flag X-900 present | X-900 | [X-900] | ✓ |
| Solvantra: flag X-109 absent | no X-109 | [X-900] | ✓ |
| Solvantra: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Solvantra: flag X-102 absent | no X-102 | [X-900] | ✓ |
| Solvantra: flag X-106 absent | no X-106 | [X-900] | ✓ |
| Solvantra: ownership_after | 0.1100 | 0.1100 | ✓ |
| Solvantra: invested_after | 6.1000 | 6.1000 | ✓ |
| Solvantra: latest_post_money | 100.0000 | 100.0000 | ✓ |
| Solvantra: open items count | 0 | 0 | ✓ |
| Lanternfell Space: disposition | BLOCK | BLOCK | ✓ |
| Lanternfell Space: rule chain | [M-010, M-000] | [M-010, M-000] | ✓ |
| Lanternfell Space: proposed mark | 40.0000 | 40.0000 | ✓ |
| Lanternfell Space: flag X-900 present | X-900 | [X-900] | ✓ |
| Lanternfell Space: flag X-104 absent | no X-104 | [X-900] | ✓ |
| Lanternfell Space: flag X-101 absent | no X-101 | [X-900] | ✓ |
| Lanternfell Space: flag X-103 absent | no X-103 | [X-900] | ✓ |
| Lanternfell Space: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Lanternfell Space: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Lanternfell Space: ownership_after | 0.0500 | 0.0500 | ✓ |
| Lanternfell Space: latest_post_money | 800.0000 | 800.0000 | ✓ |
| Kilnbrook: disposition | BLOCK | BLOCK | ✓ |
| Kilnbrook: rule chain | [M-000, M-010] | [M-000, M-010] | ✓ |
| Kilnbrook: proposed mark | 6.7500 | 6.7500 | ✓ |
| Kilnbrook: flag X-900 present | X-900 | [X-900] | ✓ |
| Kilnbrook: flag X-107 absent | no X-107 | [X-900] | ✓ |
| Kilnbrook: flag X-108 absent | no X-108 | [X-900] | ✓ |
| Kilnbrook: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Kilnbrook: ownership_after | 0.0750 | 0.0750 | ✓ |
| Kilnbrook: invested_after | 2.0000 | 2.0000 | ✓ |
| Kilnbrook: note_at_cost | 0.0000 | 0.0000 | ✓ |
| Kilnbrook: equity_mark | 6.7500 | 6.7500 | ✓ |
| Kilnbrook: open items count | 0 | 0 | ✓ |
| Ambercrest: disposition | BLOCK | BLOCK | ✓ |
| Ambercrest: rule chain | [M-010, M-000] | [M-010, M-000] | ✓ |
| Ambercrest: proposed mark | 13.5000 | 13.5000 | ✓ |
| Ambercrest: flag X-900 present | X-900 | [X-900] | ✓ |
| Ambercrest: flag X-101 absent | no X-101 | [X-900] | ✓ |
| Ambercrest: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Ambercrest: status | Active | Active | ✓ |
| Ambercrest: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Ambercrest: ownership_after | 0.0450 | 0.0450 | ✓ |
| Ambercrest: invested_after | 6.6000 | 6.6000 | ✓ |

## 22_listed_refused

Positions the book already carries as Public (Stage = Public; the stub seeds their quote to the market cap the book carries, so ownership × cap is checkable). Vexmoor: a priced round with no post-money (X-902) is refused, so the carry side must still apply M-041 at the quote — 0.057 × 398.1 = 22.6917, Level 1 — and the position is BLOCK on X-900 alone (no X-113, no staleness flag). Thornmill Systems: a secondary with negative proceeds (X-903) is refused AND the quote has been removed — chain M-000 (refused) then M-000 (no quote), prior mark 28.2 carried, both X-900 and X-113. Vinecroft: a clean Distribution of 0.5 is applied — but a listed position is worth its close whatever else happened in the quarter, so M-041 must still re-mark it to 0.016 × 1390.7 = 22.2512 (not the 22.3 prior mark), realized 0.5, Level 1, MONITOR.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-902 | X-902 | [X-902, X-903] | ✓ |
| validation must include X-903 | X-903 | [X-902, X-903] | ✓ |
| validation must not include X-901 | no X-901 | [X-902, X-903] | ✓ |
| validation must not include X-909 | no X-909 | [X-902, X-903] | ✓ |
| validation must not include X-914 | no X-914 | [X-902, X-903] | ✓ |
| validation must not include X-907 | no X-907 | [X-902, X-903] | ✓ |
| validation must not include X-904 | no X-904 | [X-902, X-903] | ✓ |
| validation X-902 on Vexmoor | ≥ 1 | 1 | ✓ |
| validation X-903 on Thornmill Systems | ≥ 1 | 1 | ✓ |
| no validation * on Vinecroft | 0 | 0 | ✓ |
| validation_blocking | True | [X-902:Vexmoor, X-903:Thornmill Systems] | ✓ |
| totals.events | 3 | 3 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Vexmoor: disposition | BLOCK | BLOCK | ✓ |
| Vexmoor: rule chain | [M-000, M-041] | [M-000, M-041] | ✓ |
| Vexmoor: proposed mark | 22.6917 | 22.6917 | ✓ |
| Vexmoor: flag X-900 present | X-900 | [X-900] | ✓ |
| Vexmoor: flag X-113 absent | no X-113 | [X-900] | ✓ |
| Vexmoor: flag X-201 absent | no X-201 | [X-900] | ✓ |
| Vexmoor: flag X-202 absent | no X-202 | [X-900] | ✓ |
| Vexmoor: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Vexmoor: flag X-102 absent | no X-102 | [X-900] | ✓ |
| Vexmoor: stage | Public | Public | ✓ |
| Vexmoor: listed | True | True | ✓ |
| Vexmoor: fv_level | 1 | 1 | ✓ |
| Vexmoor: ownership_after | 0.0570 | 0.0570 | ✓ |
| Vexmoor: latest_post_money | 398.1000 | 398.1000 | ✓ |
| Thornmill Systems: disposition | BLOCK | BLOCK | ✓ |
| Thornmill Systems: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Thornmill Systems: proposed mark | 28.2000 | 28.2000 | ✓ |
| Thornmill Systems: flag X-900 present | X-900 | [X-113, X-900] | ✓ |
| Thornmill Systems: flag X-113 present | X-113 | [X-113, X-900] | ✓ |
| Thornmill Systems: flag X-104 absent | no X-104 | [X-113, X-900] | ✓ |
| Thornmill Systems: flag X-101 absent | no X-101 | [X-113, X-900] | ✓ |
| Thornmill Systems: flag X-201 absent | no X-201 | [X-113, X-900] | ✓ |
| Thornmill Systems: listed | True | True | ✓ |
| Thornmill Systems: fv_level | 1 | 1 | ✓ |
| Thornmill Systems: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Thornmill Systems: ownership_after | 0.0130 | 0.0130 | ✓ |
| Vinecroft: disposition | MONITOR | MONITOR | ✓ |
| Vinecroft: rule chain | [M-022, M-041] | [M-022, M-041] | ✓ |
| Vinecroft: proposed mark | 22.2512 | 22.2512 | ✓ |
| Vinecroft: flag X-111 present | X-111 | [X-111] | ✓ |
| Vinecroft: flag X-900 absent | no X-900 | [X-111] | ✓ |
| Vinecroft: flag X-113 absent | no X-113 | [X-111] | ✓ |
| Vinecroft: flag X-201 absent | no X-201 | [X-111] | ✓ |
| Vinecroft: flag X-202 absent | no X-202 | [X-111] | ✓ |
| Vinecroft: listed | True | True | ✓ |
| Vinecroft: fv_level | 1 | 1 | ✓ |
| Vinecroft: realized_quarter | 0.5000 | 0.5000 | ✓ |
| Vinecroft: ownership_after | 0.0160 | 0.0160 | ✓ |

## 23_new_investment_refused

New Investment rows for companies the Portfolio tab does not have, where the row itself is bad. The engine synthesises the position (X-918) and then must refuse the row: the position exists at zero, is BLOCK on X-900, and nothing is booked from a cell that could not be trusted. Brightmoor Health: ownership after 150 points (X-903). Nightjar Robotics: entry post-money in euros (X-920). Fennel Dynamics: a negative post-money (X-903 — the money-domain checks must run for a company that is not in the book, not just for book companies). Corvid Analytics: a post-money of 0 (X-903; otherwise M-014 would enter the position at 0 × 0.10 = 0 and call it a mark). Heron Payments is the control: a clean first check, 0.10 × 20 = 2.0, invested 2.0, X-918 REVIEW, fund from Detail.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-918 | X-918 | [X-903, X-918, X-920] | ✓ |
| validation must include X-903 | X-903 | [X-903, X-918, X-920] | ✓ |
| validation must include X-920 | X-920 | [X-903, X-918, X-920] | ✓ |
| validation must not include X-901 | no X-901 | [X-903, X-918, X-920] | ✓ |
| validation must not include X-909 | no X-909 | [X-903, X-918, X-920] | ✓ |
| validation must not include X-914 | no X-914 | [X-903, X-918, X-920] | ✓ |
| validation must not include X-907 | no X-907 | [X-903, X-918, X-920] | ✓ |
| validation X-918 count | 5 | 5 | ✓ |
| validation X-903 on Brightmoor Health | ≥ 1 | 1 | ✓ |
| validation X-920 on Nightjar Robotics | ≥ 1 | 1 | ✓ |
| validation X-903 on Fennel Dynamics | ≥ 1 | 1 | ✓ |
| validation X-903 on Corvid Analytics | ≥ 1 | 1 | ✓ |
| no validation * on Heron Payments | 0 | 0 | ✓ |
| validation_blocking | True | [X-903:Brightmoor Health, X-903:Corvid Analytics, X-903:Fennel Dynamics, X-920:Nightjar Robotics] | ✓ |
| totals.events | 5 | 5 | ✓ |
| totals.positions | 105 | 105 | ✓ |
| Brightmoor Health: disposition | BLOCK | BLOCK | ✓ |
| Brightmoor Health: chain contains M-000 | M-000 | [M-000, M-000] | ✓ |
| Brightmoor Health: chain must not contain M-014 | no M-014 | [M-000, M-000] | ✓ |
| Brightmoor Health: chain must not contain M-999 | no M-999 | [M-000, M-000] | ✓ |
| Brightmoor Health: proposed mark | 0.0000 | 0.0000 | ✓ |
| Brightmoor Health: flag X-900 present | X-900 | [X-900] | ✓ |
| Brightmoor Health: flag X-120 absent | no X-120 | [X-900] | ✓ |
| Brightmoor Health: fund | Fund III | Fund III | ✓ |
| Brightmoor Health: sector | Healthcare | Healthcare | ✓ |
| Brightmoor Health: ownership_after | 0.0000 | 0.0000 | ✓ |
| Brightmoor Health: invested_after | 0.0000 | 0.0000 | ✓ |
| Nightjar Robotics: disposition | BLOCK | BLOCK | ✓ |
| Nightjar Robotics: chain must not contain M-014 | no M-014 | [M-000, M-000] | ✓ |
| Nightjar Robotics: chain must not contain M-999 | no M-999 | [M-000, M-000] | ✓ |
| Nightjar Robotics: proposed mark | 0.0000 | 0.0000 | ✓ |
| Nightjar Robotics: flag X-900 present | X-900 | [X-900] | ✓ |
| Nightjar Robotics: flag X-120 absent | no X-120 | [X-900] | ✓ |
| Nightjar Robotics: fund | Fund II | Fund II | ✓ |
| Nightjar Robotics: ownership_after | 0.0000 | 0.0000 | ✓ |
| Nightjar Robotics: invested_after | 0.0000 | 0.0000 | ✓ |
| Fennel Dynamics: disposition | BLOCK | BLOCK | ✓ |
| Fennel Dynamics: chain must not contain M-014 | no M-014 | [M-000, M-000] | ✓ |
| Fennel Dynamics: chain must not contain M-999 | no M-999 | [M-000, M-000] | ✓ |
| Fennel Dynamics: proposed mark | 0.0000 | 0.0000 | ✓ |
| Fennel Dynamics: flag X-900 present | X-900 | [X-900] | ✓ |
| Fennel Dynamics: flag X-120 absent | no X-120 | [X-900] | ✓ |
| Fennel Dynamics: ownership_after | 0.0000 | 0.0000 | ✓ |
| Fennel Dynamics: invested_after | 0.0000 | 0.0000 | ✓ |
| Corvid Analytics: disposition | BLOCK | BLOCK | ✓ |
| Corvid Analytics: chain must not contain M-014 | no M-014 | [M-000, M-000] | ✓ |
| Corvid Analytics: chain must not contain M-999 | no M-999 | [M-000, M-000] | ✓ |
| Corvid Analytics: proposed mark | 0.0000 | 0.0000 | ✓ |
| Corvid Analytics: flag X-900 present | X-900 | [X-900] | ✓ |
| Corvid Analytics: flag X-120 absent | no X-120 | [X-900] | ✓ |
| Corvid Analytics: ownership_after | 0.0000 | 0.0000 | ✓ |
| Corvid Analytics: invested_after | 0.0000 | 0.0000 | ✓ |
| Heron Payments: disposition | REVIEW | REVIEW | ✓ |
| Heron Payments: rule chain | [M-014] | [M-014] | ✓ |
| Heron Payments: proposed mark | 2.0000 | 2.0000 | ✓ |
| Heron Payments: flag X-120 present | X-120 | [X-120, X-918] | ✓ |
| Heron Payments: flag X-918 present | X-918 | [X-120, X-918] | ✓ |
| Heron Payments: flag X-900 absent | no X-900 | [X-120, X-918] | ✓ |
| Heron Payments: flag M-999 absent | no M-999 | [X-120, X-918] | ✓ |
| Heron Payments: status | Active | Active | ✓ |
| Heron Payments: fund | Fund III | Fund III | ✓ |
| Heron Payments: sector | Fintech | Fintech | ✓ |
| Heron Payments: ownership_after | 0.1000 | 0.1000 | ✓ |
| Heron Payments: invested_after | 2.0000 | 2.0000 | ✓ |
| Heron Payments: latest_post_money | 20.0000 | 20.0000 | ✓ |

## 24_terminal_refused

Refused rows on companies that were already Acquired or Shut Down at the prior close. Cash after an exit is allowed (no X-907), but a cash row the ingest layer cannot trust must still be refused on the terminal branch — recorded, X-900 BLOCK, nothing booked — and a terminal position keeps its BLOCK flags. Kolvani Health (Acquired): a clean escrow release of 0.8 is applied, then a Distribution of -0.3 (X-903) is refused — realized 0.8, not 0.5, mark 0, BLOCK. Everbrook Analytics (Shut Down): a Note Repaid with proceeds in euros (X-920) — refused, realized 0, BLOCK. Zerocrest (Shut Down): a Distribution whose proceeds cell is text "tbc" (X-902) — refused. Hearthwick (Acquired): a priced round with no post-money — X-907 and X-902 at run level; the row is not on the allowed list and never reaches the position, whose mark stays 0.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-903 | X-903 | [X-902, X-903, X-907, X-920] | ✓ |
| validation must include X-920 | X-920 | [X-902, X-903, X-907, X-920] | ✓ |
| validation must include X-907 | X-907 | [X-902, X-903, X-907, X-920] | ✓ |
| validation must include X-902 | X-902 | [X-902, X-903, X-907, X-920] | ✓ |
| validation must not include X-901 | no X-901 | [X-902, X-903, X-907, X-920] | ✓ |
| validation must not include X-909 | no X-909 | [X-902, X-903, X-907, X-920] | ✓ |
| validation must not include X-914 | no X-914 | [X-902, X-903, X-907, X-920] | ✓ |
| validation X-903 on Kolvani Health count | 1 | 1 | ✓ |
| validation X-920 on Everbrook Analytics | ≥ 1 | 1 | ✓ |
| validation X-902 on Zerocrest | ≥ 1 | 1 | ✓ |
| validation X-907 on Hearthwick count | 1 | 1 | ✓ |
| validation X-902 on Hearthwick | ≥ 1 | 1 | ✓ |
| validation X-907 count | 1 | 1 | ✓ |
| no validation X-907 on Kolvani Health | 0 | 0 | ✓ |
| no validation X-907 on Everbrook Analytics | 0 | 0 | ✓ |
| no validation X-907 on Zerocrest | 0 | 0 | ✓ |
| validation_blocking | True | [X-902:Hearthwick, X-902:Zerocrest, X-903:Kolvani Health, X-907:Hearthwick, X-920:Everbrook Analytics] | ✓ |
| totals.events | 5 | 5 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Kolvani Health: disposition | BLOCK | BLOCK | ✓ |
| Kolvani Health: rule chain | [M-000, M-022, M-000] | [M-000, M-022, M-000] | ✓ |
| Kolvani Health: proposed mark | 0.0000 | 0.0000 | ✓ |
| Kolvani Health: flag X-900 present | X-900 | [X-900] | ✓ |
| Kolvani Health: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Kolvani Health: flag X-111 absent | no X-111 | [X-900] | ✓ |
| Kolvani Health: status | Acquired | Acquired | ✓ |
| Kolvani Health: realized_quarter | 0.8000 | 0.8000 | ✓ |
| Kolvani Health: ownership_after | 0.0710 | 0.0710 | ✓ |
| Everbrook Analytics: disposition | BLOCK | BLOCK | ✓ |
| Everbrook Analytics: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Everbrook Analytics: proposed mark | 0.0000 | 0.0000 | ✓ |
| Everbrook Analytics: flag X-900 present | X-900 | [X-900] | ✓ |
| Everbrook Analytics: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Everbrook Analytics: flag X-115 absent | no X-115 | [X-900] | ✓ |
| Everbrook Analytics: status | Shut Down | Shut Down | ✓ |
| Everbrook Analytics: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Zerocrest: disposition | BLOCK | BLOCK | ✓ |
| Zerocrest: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Zerocrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Zerocrest: flag X-900 present | X-900 | [X-900] | ✓ |
| Zerocrest: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Zerocrest: flag X-111 absent | no X-111 | [X-900] | ✓ |
| Zerocrest: status | Shut Down | Shut Down | ✓ |
| Zerocrest: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Hearthwick: rule chain | [M-000] | [M-000] | ✓ |
| Hearthwick: chain must not contain M-010 | no M-010 | [M-000] | ✓ |
| Hearthwick: proposed mark | 0.0000 | 0.0000 | ✓ |
| Hearthwick: flag X-900 absent | no X-900 | [] | ✓ |
| Hearthwick: flag M-999 absent | no M-999 | [] | ✓ |
| Hearthwick: status | Acquired | Acquired | ✓ |
| Hearthwick: realized_quarter | 0.0000 | 0.0000 | ✓ |

## 25_unknown_type_with_currency

Rows that are wrong in two ways at once: an event type the engine has no rule for AND a non-USD currency (X-920, blocking). The currency block must not hide the unknown event — the row still reaches M-999 so the position blocks on M-999 and the adjudication proposal is raised; X-900 is not used for it. Solvantra: "SPAC Merger" with a euro value cell (X-909 + X-920). Oxbowlane: bare "Tender Offer" (ambiguous sold/bought → X-914) with sterling in the Notes (X-920). Willowmere Compute: bare "LOI" (X-914) with CHF in Detail. Kilnbrook is the contrast: a known type (priced round) with euros in the Notes only — that row IS refused (X-900), M-010 never runs, prior mark 4.4 carried — the chain reads M-000 (refused) then M-000 (carry). Every position keeps its prior mark.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-909 | X-909 | [X-909, X-914, X-920] | ✓ |
| validation must include X-914 | X-914 | [X-909, X-914, X-920] | ✓ |
| validation must include X-920 | X-920 | [X-909, X-914, X-920] | ✓ |
| validation must not include X-901 | no X-901 | [X-909, X-914, X-920] | ✓ |
| validation must not include X-907 | no X-907 | [X-909, X-914, X-920] | ✓ |
| validation must not include X-902 | no X-902 | [X-909, X-914, X-920] | ✓ |
| validation must not include X-903 | no X-903 | [X-909, X-914, X-920] | ✓ |
| validation X-909 on Solvantra | ≥ 1 | 1 | ✓ |
| validation X-920 on Solvantra | ≥ 1 | 1 | ✓ |
| validation X-914 on Oxbowlane containing 'Secondary' | ≥ 1 | 1 | ✓ |
| validation X-920 on Oxbowlane containing '£' | ≥ 1 | 1 | ✓ |
| validation X-914 on Willowmere Compute | ≥ 1 | 1 | ✓ |
| validation X-920 on Willowmere Compute containing 'CHF' | ≥ 1 | 1 | ✓ |
| validation X-920 on Kilnbrook containing '€' | ≥ 1 | 1 | ✓ |
| no validation X-909 on Oxbowlane | 0 | 0 | ✓ |
| no validation X-909 on Willowmere Compute | 0 | 0 | ✓ |
| validation_blocking | True | [X-909:Solvantra, X-914:Oxbowlane, X-914:Willowmere Compute, X-920:Kilnbrook, X-920:Oxbowlane, X-920:Solvantra, X-920:Willowmere Compute] | ✓ |
| totals.events | 4 | 4 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | BLOCK | BLOCK | ✓ |
| Solvantra: rule chain | [M-999] | [M-999] | ✓ |
| Solvantra: proposed mark | 8.9000 | 8.9000 | ✓ |
| Solvantra: flag M-999 present | M-999 | [M-999] | ✓ |
| Solvantra: flag X-900 absent | no X-900 | [M-999] | ✓ |
| Solvantra: ownership_after | 0.1180 | 0.1180 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-999] | [M-999] | ✓ |
| Oxbowlane: proposed mark | 13.0000 | 13.0000 | ✓ |
| Oxbowlane: flag M-999 present | M-999 | [M-999] | ✓ |
| Oxbowlane: flag X-900 absent | no X-900 | [M-999] | ✓ |
| Oxbowlane: flag X-104 absent | no X-104 | [M-999] | ✓ |
| Oxbowlane: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Oxbowlane: ownership_after | 0.0430 | 0.0430 | ✓ |
| Willowmere Compute: disposition | BLOCK | BLOCK | ✓ |
| Willowmere Compute: rule chain | [M-999] | [M-999] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Willowmere Compute: flag M-999 present | M-999 | [M-999] | ✓ |
| Willowmere Compute: flag X-900 absent | no X-900 | [M-999] | ✓ |
| Willowmere Compute: flag X-109 absent | no X-109 | [M-999] | ✓ |
| Willowmere Compute: open items count | 0 | 0 | ✓ |
| Kilnbrook: disposition | BLOCK | BLOCK | ✓ |
| Kilnbrook: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Kilnbrook: proposed mark | 4.4000 | 4.4000 | ✓ |
| Kilnbrook: flag X-900 present | X-900 | [X-105, X-900] | ✓ |
| Kilnbrook: flag M-999 absent | no M-999 | [X-105, X-900] | ✓ |
| Kilnbrook: ownership_after | 0.0690 | 0.0690 | ✓ |
| Kilnbrook: latest_post_money | 63.6000 | 63.6000 | ✓ |

## 26_announced_then_refused_close

An announced acquisition followed in the same quarter by a closing (or termination) row that the ingest layer refused. A refused row is not evidence of anything — it must not supersede the announcement, and it must not close the position. Oxbowlane: announced at $500M, then a close with no deal value (X-902) — M-050 applies, 0.043 × 500 × 0.90 = 19.35, the pending_acquisition item stays open, the close is recorded and refused (X-900), the 21.5 of proceeds on the refused row is NOT realized, status stays Active. Inkmoor: announced at $60M then a termination with a negative value (X-903) — M-050 applies, 0.12 × 60 × 0.90 = 6.48, no M-051 / X-114, item stays open. Ambercrest is the control — announced then a clean close: M-000 (skipped) then M-020, realized 0.042 × 400 = 16.8, Acquired, CLEAR.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-902 | X-902 | [X-902, X-903] | ✓ |
| validation must include X-903 | X-903 | [X-902, X-903] | ✓ |
| validation must not include X-901 | no X-901 | [X-902, X-903] | ✓ |
| validation must not include X-909 | no X-909 | [X-902, X-903] | ✓ |
| validation must not include X-914 | no X-914 | [X-902, X-903] | ✓ |
| validation must not include X-907 | no X-907 | [X-902, X-903] | ✓ |
| validation X-902 on Oxbowlane | ≥ 1 | 1 | ✓ |
| validation X-903 on Inkmoor | ≥ 1 | 1 | ✓ |
| no validation * on Ambercrest | 0 | 0 | ✓ |
| validation_blocking | True | [X-902:Oxbowlane, X-903:Inkmoor] | ✓ |
| totals.events | 6 | 6 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-050, M-000] | [M-050, M-000] | ✓ |
| Oxbowlane: proposed mark | 19.3500 | 19.3500 | ✓ |
| Oxbowlane: flag X-101 present | X-101 | [X-101, X-900] | ✓ |
| Oxbowlane: flag X-900 present | X-900 | [X-101, X-900] | ✓ |
| Oxbowlane: flag M-999 absent | no M-999 | [X-101, X-900] | ✓ |
| Oxbowlane: status | Active | Active | ✓ |
| Oxbowlane: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Oxbowlane: ownership_after | 0.0430 | 0.0430 | ✓ |
| Oxbowlane: open item {'kind': 'pending_acquisition'} | present | [('pending_acquisition', 0, False)] | ✓ |
| Oxbowlane: open items count | 1 | 1 | ✓ |
| Oxbowlane: alternative mark at_full_deal_value | 21.5000 | 21.5000 | ✓ |
| Oxbowlane: alternative mark hold_prior | 13.0000 | 13.0000 | ✓ |
| Inkmoor: disposition | BLOCK | BLOCK | ✓ |
| Inkmoor: rule chain | [M-050, M-000] | [M-050, M-000] | ✓ |
| Inkmoor: proposed mark | 6.4800 | 6.4800 | ✓ |
| Inkmoor: flag X-101 present | X-101 | [X-101, X-900] | ✓ |
| Inkmoor: flag X-900 present | X-900 | [X-101, X-900] | ✓ |
| Inkmoor: flag X-114 absent | no X-114 | [X-101, X-900] | ✓ |
| Inkmoor: flag M-999 absent | no M-999 | [X-101, X-900] | ✓ |
| Inkmoor: status | Active | Active | ✓ |
| Inkmoor: ownership_after | 0.1200 | 0.1200 | ✓ |
| Inkmoor: open item {'kind': 'pending_acquisition'} | present | [('pending_acquisition', 0, False)] | ✓ |
| Inkmoor: open items count | 1 | 1 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-000, M-020] | [M-000, M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: flag X-101 absent | no X-101 | [] | ✓ |
| Ambercrest: flag X-900 absent | no X-900 | [] | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Ambercrest: open items count | 0 | 0 | ✓ |

## 27_portfolio_edges

The Portfolio tab arriving dirty, one bad cell per company, with no activity for any of them. A book row that fails a blocking check must block ITS position — a run-level issue with a CLEAR position carrying a number nobody can reconcile is the failure mode this corpus exists to catch. Solvantra: Prior Mark "n/a" (a blank token → 0.0, X-904 against 0.118 × 75.5 = 8.909) — carried at the 0.0 the book says, BLOCK. Vexmoor: Ownership 0 with a prior mark of 22.7 (X-903 and X-904) — carried at 22.7, ownership 0, BLOCK. Covebright: Latest Round 2027-01-15, after the measurement date (X-921: the prior-close book cannot carry a round that has not happened) — carried at 14.6, no staleness flag, BLOCK. Rivenmark pasted twice (X-906 on BOTH rows: the engine cannot know which is the position) — 101 positions, both rows BLOCK. Ambercrest: Status "active " (folded, X-915) — Active, CLEAR. Palefire Labs: Latest Round exactly on the prior close (2026-06-30) — allowed, CLEAR.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-904 | X-904 | [X-903, X-904, X-906, X-908, X-915, X-921] | ✓ |
| validation must include X-903 | X-903 | [X-903, X-904, X-906, X-908, X-915, X-921] | ✓ |
| validation must include X-906 | X-906 | [X-903, X-904, X-906, X-908, X-915, X-921] | ✓ |
| validation must include X-915 | X-915 | [X-903, X-904, X-906, X-908, X-915, X-921] | ✓ |
| validation must include X-921 | X-921 | [X-903, X-904, X-906, X-908, X-915, X-921] | ✓ |
| validation must not include X-901 | no X-901 | [X-903, X-904, X-906, X-908, X-915, X-921] | ✓ |
| validation must not include X-909 | no X-909 | [X-903, X-904, X-906, X-908, X-915, X-921] | ✓ |
| validation must not include X-914 | no X-914 | [X-903, X-904, X-906, X-908, X-915, X-921] | ✓ |
| validation must not include X-902 | no X-902 | [X-903, X-904, X-906, X-908, X-915, X-921] | ✓ |
| validation X-904 on Solvantra | ≥ 1 | 1 | ✓ |
| validation X-903 on Vexmoor | ≥ 1 | 1 | ✓ |
| validation X-904 on Vexmoor | ≥ 1 | 1 | ✓ |
| validation X-921 on Covebright containing '2027-01-15' | ≥ 1 | 1 | ✓ |
| validation X-906 on Rivenmark count | 2 | 2 | ✓ |
| validation X-915 on Ambercrest containing 'Active' | ≥ 1 | 1 | ✓ |
| no validation * on Ambercrest | 0 | 0 | ✓ |
| no validation * on Palefire Labs | 0 | 0 | ✓ |
| validation_blocking | True | [X-903:Vexmoor, X-904:Solvantra, X-904:Vexmoor, X-906:Rivenmark, X-921:Covebright] | ✓ |
| totals.events | 0 | 0 | ✓ |
| totals.positions | 101 | 101 | ✓ |
| Solvantra: disposition | BLOCK | BLOCK | ✓ |
| Solvantra: rule chain | [M-000] | [M-000] | ✓ |
| Solvantra: proposed mark | 0.0000 | 0.0000 | ✓ |
| Solvantra: flag X-900 present | X-900 | [X-900] | ✓ |
| Solvantra: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Solvantra: ownership_after | 0.1180 | 0.1180 | ✓ |
| Solvantra: latest_post_money | 75.5000 | 75.5000 | ✓ |
| Vexmoor: disposition | BLOCK | BLOCK | ✓ |
| Vexmoor: rule chain | [M-000] | [M-000] | ✓ |
| Vexmoor: proposed mark | 22.7000 | 22.7000 | ✓ |
| Vexmoor: flag X-900 present | X-900 | [X-900] | ✓ |
| Vexmoor: ownership_after | 0.0000 | 0.0000 | ✓ |
| Covebright: disposition | BLOCK | BLOCK | ✓ |
| Covebright: rule chain | [M-000] | [M-000] | ✓ |
| Covebright: proposed mark | 14.6000 | 14.6000 | ✓ |
| Covebright: flag X-900 present | X-900 | [X-900] | ✓ |
| Covebright: flag X-201 absent | no X-201 | [X-900] | ✓ |
| Covebright: flag X-202 absent | no X-202 | [X-900] | ✓ |
| Rivenmark: disposition | BLOCK | BLOCK | ✓ |
| Rivenmark: rule chain | [M-000] | [M-000] | ✓ |
| Rivenmark: proposed mark | 2.9000 | 2.9000 | ✓ |
| Rivenmark: flag X-900 present | X-900 | [X-900] | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-000] | [M-000] | ✓ |
| Ambercrest: proposed mark | 10.6000 | 10.6000 | ✓ |
| Ambercrest: flag X-900 absent | no X-900 | [] | ✓ |
| Ambercrest: status | Active | Active | ✓ |
| Palefire Labs: disposition | CLEAR | CLEAR | ✓ |
| Palefire Labs: rule chain | [M-000] | [M-000] | ✓ |
| Palefire Labs: proposed mark | 6.5000 | 6.5000 | ✓ |
| Palefire Labs: flag X-900 absent | no X-900 | [] | ✓ |
| Palefire Labs: flag X-201 absent | no X-201 | [] | ✓ |

## 27b_portfolio_unknown_status

A Status the engine does not know ("Exited" — is that Acquired? Shut Down? still carrying proceeds?) cannot be marked, so the reader refuses the whole file with a message that names the row, the company and the value (SPEC §2.5: a hard failure must say what was found). Case and whitespace variants ("active ", "SHUT DOWN") are folded and recorded (27); a new word is not.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | False | False | ✓ |
| error_contains | [Exited] | row 63: unknown Status 'Exited' for Kilnbrook | ✓ |
| error_is_not_a_traceback | message names the problem | row 63: unknown Status 'Exited' for Kilnbrook | ✓ |

## 28_date_edges

Event dates at and beyond the edges of the quarter. On the prior close itself (2026-06-30, Solvantra's round): outside the window by one day, X-905 REVIEW, but a round missed at the last close is still the best evidence of value — applied, 0.11 × 100 = 11.0, CLEAR. On the window end itself (2026-09-30, Ambercrest's exit): inside, no X-905, applied, realized 0.042 × 400 = 16.8. Within the grace period before the window (Lanternfell, 2026-04-15, 77 days before 1 July): X-905 REVIEW, applied, 0.05 × 800 = 40.0. After the measurement date (Kilnbrook 2026-10-05, Oxbowlane 2030-01-01): a transaction that has not happened at the measurement date is not evidence at the measurement date — X-905 BLOCK, the row is refused, prior mark carried, X-900. Older than the grace period (Willowmere 2026-03-15, Coppermoss 1900-01-01 — a real Excel date of serial 1): the row belongs to a quarter that has already been closed, or is not a date at all — X-905 BLOCK, refused, carried (chain: M-000 refused, M-000 carry). The grace period (tolerances.late_event_grace_days) is policy.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-905 | X-905 | [X-905] | ✓ |
| validation must not include X-901 | no X-901 | [X-905] | ✓ |
| validation must not include X-909 | no X-909 | [X-905] | ✓ |
| validation must not include X-914 | no X-914 | [X-905] | ✓ |
| validation must not include X-902 | no X-902 | [X-905] | ✓ |
| validation must not include X-903 | no X-903 | [X-905] | ✓ |
| validation must not include X-906 | no X-906 | [X-905] | ✓ |
| validation X-905 on Solvantra count | 1 | 1 | ✓ |
| validation X-905 on Lanternfell Space count | 1 | 1 | ✓ |
| validation X-905 on Kilnbrook count | 1 | 1 | ✓ |
| validation X-905 on Oxbowlane containing '2030' | ≥ 1 | 1 | ✓ |
| validation X-905 on Willowmere Compute | ≥ 1 | 1 | ✓ |
| validation X-905 on Coppermoss Energy containing '1900' | ≥ 1 | 1 | ✓ |
| no validation X-905 on Ambercrest | 0 | 0 | ✓ |
| no validation * on Ambercrest | 0 | 0 | ✓ |
| validation_blocking | True | [X-905:Coppermoss Energy, X-905:Kilnbrook, X-905:Oxbowlane, X-905:Willowmere Compute] | ✓ |
| totals.events | 7 | 7 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: flag X-900 absent | no X-900 | [] | ✓ |
| Solvantra: ownership_after | 0.1100 | 0.1100 | ✓ |
| Solvantra: invested_after | 6.1000 | 6.1000 | ✓ |
| Ambercrest: disposition | CLEAR | CLEAR | ✓ |
| Ambercrest: rule chain | [M-020] | [M-020] | ✓ |
| Ambercrest: proposed mark | 0.0000 | 0.0000 | ✓ |
| Ambercrest: flag X-900 absent | no X-900 | [] | ✓ |
| Ambercrest: flag X-101 absent | no X-101 | [] | ✓ |
| Ambercrest: status | Acquired | Acquired | ✓ |
| Ambercrest: realized_quarter | 16.8000 | 16.8000 | ✓ |
| Lanternfell Space: disposition | CLEAR | CLEAR | ✓ |
| Lanternfell Space: rule chain | [M-010] | [M-010] | ✓ |
| Lanternfell Space: proposed mark | 40.0000 | 40.0000 | ✓ |
| Lanternfell Space: flag X-900 absent | no X-900 | [] | ✓ |
| Lanternfell Space: flag X-103 absent | no X-103 | [] | ✓ |
| Lanternfell Space: ownership_after | 0.0500 | 0.0500 | ✓ |
| Kilnbrook: disposition | BLOCK | BLOCK | ✓ |
| Kilnbrook: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Kilnbrook: proposed mark | 4.4000 | 4.4000 | ✓ |
| Kilnbrook: flag X-900 present | X-900 | [X-900] | ✓ |
| Kilnbrook: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Kilnbrook: ownership_after | 0.0690 | 0.0690 | ✓ |
| Kilnbrook: latest_post_money | 63.6000 | 63.6000 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Oxbowlane: proposed mark | 13.0000 | 13.0000 | ✓ |
| Oxbowlane: flag X-900 present | X-900 | [X-900] | ✓ |
| Oxbowlane: flag X-109 absent | no X-109 | [X-900] | ✓ |
| Oxbowlane: open items count | 0 | 0 | ✓ |
| Willowmere Compute: disposition | BLOCK | BLOCK | ✓ |
| Willowmere Compute: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Willowmere Compute: proposed mark | 4.7000 | 4.7000 | ✓ |
| Willowmere Compute: flag X-900 present | X-900 | [X-900] | ✓ |
| Willowmere Compute: flag X-109 absent | no X-109 | [X-900] | ✓ |
| Willowmere Compute: open items count | 0 | 0 | ✓ |
| Coppermoss Energy: disposition | BLOCK | BLOCK | ✓ |
| Coppermoss Energy: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Coppermoss Energy: proposed mark | 2.6000 | 2.6000 | ✓ |
| Coppermoss Energy: flag X-900 present | X-900 | [X-900] | ✓ |
| Coppermoss Energy: flag X-104 absent | no X-104 | [X-900] | ✓ |
| Coppermoss Energy: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Coppermoss Energy: ownership_after | 0.1010 | 0.1010 | ✓ |

## 28b_date_serial_1900

A Date cell holding the bare integer 1 — the Excel serial for 1 January 1900, what a formula that lost its reference collapses to. It is outside the serial range the reader accepts (20000..80000, SPEC §2.3), so it is not a date in any accepted form and the file is refused with a message naming the sheet, the row, the column and the range (SPEC §2.5) — never a silent blank and never a 1900 event.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | False | False | ✓ |
| error_contains | [serial] | sheet 'Q3 2026 Activity' row 3: 'Date' is not a date: 1 is outside the Excel serial range 20000..80000 | ✓ |
| error_is_not_a_traceback | message names the problem | sheet 'Q3 2026 Activity' row 3: 'Date' is not a date: 1 is outside the Excel ser | ✓ |

## 29_big_book_500

A second big book with a different seed: 500 synthetic companies, 64 events (8 per original type on distinct companies). Runtime sanity — under 10 seconds — and exact disposition totals: 16 BLOCK (8 IPOs + 8 announced deals), 8 REVIEW (funded notes), 8 MONITOR (term sheets), 468 CLEAR. Spot checks are computed by hand from the synthesiser's own rows (post, ownership, the event's value / ownership-after / proceeds), never from engine output.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| max_seconds | < 10s | 0.1800 | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must not include X-901 | no X-901 | [] | ✓ |
| validation must not include X-909 | no X-909 | [] | ✓ |
| validation must not include X-902 | no X-902 | [] | ✓ |
| validation must not include X-903 | no X-903 | [] | ✓ |
| validation must not include X-904 | no X-904 | [] | ✓ |
| validation must not include X-906 | no X-906 | [] | ✓ |
| validation must not include X-914 | no X-914 | [] | ✓ |
| validation must not include X-905 | no X-905 | [] | ✓ |
| validation_blocking | False | False | ✓ |
| totals.events | 64 | 64 | ✓ |
| totals.positions | 500 | 500 | ✓ |
| totals.dispositions | {'BLOCK': 16, 'REVIEW': 8, 'MONITOR': 8, 'CLEAR': 468} | {'BLOCK': 16, 'REVIEW': 8, 'MONITOR': 8, 'CLEAR': 468} | ✓ |
| manifest.quarter_label | Q3 2026 | Q3 2026 | ✓ |
| manifest.policy_version | 2026Q3-0.1 | 2026Q3-0.1 | ✓ |
| Synth-0283: disposition | CLEAR | CLEAR | ✓ |
| Synth-0283: rule chain | [M-010] | [M-010] | ✓ |
| Synth-0283: proposed mark | 5.6097 | 5.6097 | ✓ |
| Synth-0283: ownership_after | 0.0542 | 0.0542 | ✓ |
| Synth-0039: disposition | REVIEW | REVIEW | ✓ |
| Synth-0039: rule chain | [M-060] | [M-060] | ✓ |
| Synth-0039: proposed mark | 22.0476 | 22.0476 | ✓ |
| Synth-0039: flag X-107 present | X-107 | [X-107] | ✓ |
| Synth-0039: note_at_cost | 0.3000 | 0.3000 | ✓ |
| Synth-0179: disposition | BLOCK | BLOCK | ✓ |
| Synth-0179: rule chain | [M-040] | [M-040] | ✓ |
| Synth-0179: proposed mark | 14.9339 | 14.9339 | ✓ |
| Synth-0179: listed | True | True | ✓ |
| Synth-0179: fv_level | 1 | 1 | ✓ |
| Synth-0310: disposition | CLEAR | CLEAR | ✓ |
| Synth-0310: rule chain | [M-020] | [M-020] | ✓ |
| Synth-0310: proposed mark | 0.0000 | 0.0000 | ✓ |
| Synth-0310: flag X-101 absent | no X-101 | [] | ✓ |
| Synth-0310: status | Acquired | Acquired | ✓ |
| Synth-0310: realized_quarter | 27.2355 | 27.2355 | ✓ |
| Synth-0437: disposition | BLOCK | BLOCK | ✓ |
| Synth-0437: rule chain | [M-050] | [M-050] | ✓ |
| Synth-0437: proposed mark | 68.2062 | 68.2062 | ✓ |
| Synth-0314: disposition | CLEAR | CLEAR | ✓ |
| Synth-0314: rule chain | [M-021] | [M-021] | ✓ |
| Synth-0314: proposed mark | 0.0000 | 0.0000 | ✓ |
| Synth-0314: status | Shut Down | Shut Down | ✓ |
| Synth-0149: disposition | CLEAR | CLEAR | ✓ |
| Synth-0149: rule chain | [M-030] | [M-030] | ✓ |
| Synth-0149: proposed mark | 3.1492 | 3.1492 | ✓ |
| Synth-0149: flag X-104 absent | no X-104 | [] | ✓ |
| Synth-0149: realized_quarter | 3.1492 | 3.1492 | ✓ |
| Synth-0149: ownership_after | 0.0106 | 0.0106 | ✓ |
| Synth-0045: disposition | MONITOR | MONITOR | ✓ |
| Synth-0045: rule chain | [M-070] | [M-070] | ✓ |
| Synth-0045: proposed mark | 12.2822 | 12.2822 | ✓ |
| Synth-0045: flag X-109 present | X-109 | [X-109] | ✓ |
| Synth-0001: disposition | CLEAR | CLEAR | ✓ |
| Synth-0001: rule chain | [M-000] | [M-000] | ✓ |
| Synth-0500: disposition | CLEAR | CLEAR | ✓ |
| Synth-0500: rule chain | [M-000] | [M-000] | ✓ |

## 30_long_notes

Cells that are far longer than a human would write — a board memo pasted into Notes. Solvantra: a clean Series B with a ~10,500-character note carrying no screen term — applied, 0.11 × 100 = 11.0, CLEAR, no X-105. Kilnbrook: a Series B whose ~10,000-character note buries "escrow" in its last sentence — applied, 0.075 × 90 = 6.75, X-105 REVIEW names the term. Oxbowlane: a term sheet whose long note ends with a euro figure — X-920 finds it wherever it is, the row is refused (M-000 recorded, M-000 carry), X-900. Lanternfell Space: a Series D whose Detail is ~2,000 characters starting "Series D" — the mark is 0.05 × 800 = 40.0 and the Stage the position carries forward is "Series D", not the memo. Nothing here may be slow: the whole run stays under 10 seconds.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| max_seconds | < 10s | 0.0600 | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-920 | X-920 | [X-920] | ✓ |
| validation must not include X-901 | no X-901 | [X-920] | ✓ |
| validation must not include X-909 | no X-909 | [X-920] | ✓ |
| validation must not include X-914 | no X-914 | [X-920] | ✓ |
| validation must not include X-902 | no X-902 | [X-920] | ✓ |
| validation must not include X-903 | no X-903 | [X-920] | ✓ |
| validation X-920 on Oxbowlane | ≥ 1 | 1 | ✓ |
| no validation * on Solvantra | 0 | 0 | ✓ |
| no validation * on Kilnbrook | 0 | 0 | ✓ |
| no validation * on Lanternfell Space | 0 | 0 | ✓ |
| validation_blocking | True | [X-920:Oxbowlane] | ✓ |
| totals.events | 4 | 4 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Solvantra: disposition | CLEAR | CLEAR | ✓ |
| Solvantra: rule chain | [M-010] | [M-010] | ✓ |
| Solvantra: proposed mark | 11.0000 | 11.0000 | ✓ |
| Solvantra: flag X-105 absent | no X-105 | [] | ✓ |
| Solvantra: flag X-900 absent | no X-900 | [] | ✓ |
| Solvantra: invested_after | 6.1000 | 6.1000 | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-010] | [M-010] | ✓ |
| Kilnbrook: proposed mark | 6.7500 | 6.7500 | ✓ |
| Kilnbrook: flag X-105 present | X-105 | [X-105] | ✓ |
| Kilnbrook: flag X-900 absent | no X-900 | [X-105] | ✓ |
| Kilnbrook: ownership_after | 0.0750 | 0.0750 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Oxbowlane: proposed mark | 13.0000 | 13.0000 | ✓ |
| Oxbowlane: flag X-900 present | X-900 | [X-900] | ✓ |
| Oxbowlane: flag X-109 absent | no X-109 | [X-900] | ✓ |
| Oxbowlane: open items count | 0 | 0 | ✓ |
| Lanternfell Space: disposition | CLEAR | CLEAR | ✓ |
| Lanternfell Space: rule chain | [M-010] | [M-010] | ✓ |
| Lanternfell Space: proposed mark | 40.0000 | 40.0000 | ✓ |
| Lanternfell Space: flag X-900 absent | no X-900 | [] | ✓ |
| Lanternfell Space: flag X-103 absent | no X-103 | [] | ✓ |
| Lanternfell Space: stage | Series D | Series D | ✓ |
| Lanternfell Space: ownership_after | 0.0500 | 0.0500 | ✓ |

## 31_custom_rule_missing_field

Declarative rules promoted from adjudication (E-08), run against rows that do not carry what the formula needs. M-120 "SPAC Merger" = ownership_after × deal_value × close_probability. Kilnbrook is the control: 0.08 × 400 × 0.90 = 28.8, REVIEW on M-120. Solvantra's SPAC row has no value cell — the formula's deal_value is None: the row must be refused before the rule runs (X-902 naming the field), prior mark 8.9 carried (M-000 refused, M-000 carry), BLOCK on X-900 — never a DSLError out of the engine. M-121 "Earn-out True-up" = prior_mark × proceeds / hc_investment: Oxbowlane's row has proceeds but hc_investment 0 — a division by zero the validator cannot see; the rule itself must refuse to evaluate, leave the mark at 13.0 and BLOCK on M-121, and the proceeds on that row are not realized. Willowmere Compute: the same rule with hc_investment 0.5 and proceeds 1.0 → 4.7 × 1.0 / 0.5 = 9.4, realized 1.0, REVIEW.

| Check | Expected | Actual | |
|---|---|---|:-:|
| ingest_ok | True | True | ✓ |
| no_crash | no exception | no exception | ✓ |
| validation must include X-902 | X-902 | [X-902] | ✓ |
| validation must not include X-901 | no X-901 | [X-902] | ✓ |
| validation must not include X-909 | no X-909 | [X-902] | ✓ |
| validation must not include X-914 | no X-914 | [X-902] | ✓ |
| validation must not include X-903 | no X-903 | [X-902] | ✓ |
| validation X-902 on Solvantra containing 'deal_value' | ≥ 1 | 1 | ✓ |
| no validation * on Kilnbrook | 0 | 0 | ✓ |
| no validation * on Willowmere Compute | 0 | 0 | ✓ |
| no validation X-909 | 0 | 0 | ✓ |
| validation_blocking | True | [X-902:Solvantra] | ✓ |
| totals.events | 4 | 4 | ✓ |
| totals.positions | 100 | 100 | ✓ |
| Kilnbrook: disposition | REVIEW | REVIEW | ✓ |
| Kilnbrook: rule chain | [M-120] | [M-120] | ✓ |
| Kilnbrook: proposed mark | 28.8000 | 28.8000 | ✓ |
| Kilnbrook: flag M-120 present | M-120 | [M-120] | ✓ |
| Kilnbrook: flag M-999 absent | no M-999 | [M-120] | ✓ |
| Kilnbrook: flag X-900 absent | no X-900 | [M-120] | ✓ |
| Kilnbrook: ownership_after | 0.0800 | 0.0800 | ✓ |
| Solvantra: disposition | BLOCK | BLOCK | ✓ |
| Solvantra: rule chain | [M-000, M-000] | [M-000, M-000] | ✓ |
| Solvantra: proposed mark | 8.9000 | 8.9000 | ✓ |
| Solvantra: flag X-900 present | X-900 | [X-900] | ✓ |
| Solvantra: flag M-120 absent | no M-120 | [X-900] | ✓ |
| Solvantra: flag M-999 absent | no M-999 | [X-900] | ✓ |
| Solvantra: ownership_after | 0.1180 | 0.1180 | ✓ |
| Oxbowlane: disposition | BLOCK | BLOCK | ✓ |
| Oxbowlane: rule chain | [M-121] | [M-121] | ✓ |
| Oxbowlane: proposed mark | 13.0000 | 13.0000 | ✓ |
| Oxbowlane: flag M-121 present | M-121 | [M-121, X-105] | ✓ |
| Oxbowlane: flag M-999 absent | no M-999 | [M-121, X-105] | ✓ |
| Oxbowlane: flag X-900 absent | no X-900 | [M-121, X-105] | ✓ |
| Oxbowlane: realized_quarter | 0.0000 | 0.0000 | ✓ |
| Willowmere Compute: disposition | REVIEW | REVIEW | ✓ |
| Willowmere Compute: rule chain | [M-121] | [M-121] | ✓ |
| Willowmere Compute: proposed mark | 9.4000 | 9.4000 | ✓ |
| Willowmere Compute: flag M-121 present | M-121 | [M-121, X-105] | ✓ |
| Willowmere Compute: flag M-999 absent | no M-999 | [M-121, X-105] | ✓ |
| Willowmere Compute: realized_quarter | 1.0000 | 1.0000 | ✓ |
| Willowmere Compute: invested_after | 6.5000 | 6.5000 | ✓ |
