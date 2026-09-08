"""Pure normalizer contract (training/SPEC.md §1.1, §1.2, §2.1–§2.4).

Every example in the spec is here, and the refusals are tested as carefully as the
acceptances: a match the normalizer is not entitled to make must come back as an
`ambiguous` correction (X-914) or as no match at all, never as a guess.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from hc_valuation.engine.inputs import EventType
from hc_valuation.ingest import normalize as nz
from hc_valuation.ingest.schema import (
    ACTIVITY_COLUMNS, ACTIVITY_HEADER_ALIASES, PORTFOLIO_COLUMNS, PORTFOLIO_HEADER_ALIASES,
)


@pytest.fixture(scope="module")
def ncfg(cfg):
    return cfg.normalization


# ---------------------------------------------------------------- folding and distance

@pytest.mark.parametrize("raw,folded", [
    ("  Priced   Equity Round ", "priced equity round"),
    ("Acquisition(Closed)", "acquisition (closed)"),
    ("Acquisition – Closed", "acquisition - closed"),
    ("IPO.", "ipo"),
    ("“Series A”", "series a"),
])
def test_fold(raw, folded):
    assert nz.fold(raw) == folded


@pytest.mark.parametrize("a,b,d", [
    ("equtiy", "equity", 1), ("shutdwon", "shutdown", 1), ("aquisition", "acquisition", 1),
    ("convertable", "convertible", 1), ("secondry", "secondary", 1), ("ca", "abc", 3),
    ("", "abc", 3), ("same", "same", 0), ("acquisition", "acquired", 6),
])
def test_damerau_levenshtein(a, b, d):
    assert nz.damerau_levenshtein(a, b) == d


# ---------------------------------------------------------------- event types: synonyms (§1.1)

@pytest.mark.parametrize("raw,canon", [
    ("Series B", EventType.PRICED_ROUND), ("seed", EventType.PRICED_ROUND), ("Round", EventType.PRICED_ROUND),
    ("Series A (recap)", EventType.PRICED_ROUND), ("Up round", EventType.PRICED_ROUND),
    ("Bridge", EventType.CONVERTIBLE_NOTE), ("SAFE", EventType.CONVERTIBLE_NOTE), ("Post-money SAFE", EventType.CONVERTIBLE_NOTE),
    ("Initial Public Offering", EventType.IPO), ("Went public", EventType.IPO), ("IPO (Nasdaq)", EventType.IPO),
    ("Direct listing", EventType.DIRECT_LISTING),
    ("Exit", EventType.ACQ_CLOSED), ("Acquired", EventType.ACQ_CLOSED), ("M&A closed", EventType.ACQ_CLOSED),
    ("Acquisition – Closed", EventType.ACQ_CLOSED), ("Acquisition: Closed", EventType.ACQ_CLOSED),
    ("acqui-hire", EventType.ACQ_CLOSED), ("Trade sale", EventType.ACQ_CLOSED),
    ("Definitive agreement", EventType.ACQ_ANNOUNCED), ("Pending acquisition", EventType.ACQ_ANNOUNCED),
    ("LOI signed (acquisition)", EventType.ACQ_ANNOUNCED),
    ("Deal fell through", EventType.ACQ_TERMINATED), ("Deal cancelled", EventType.ACQ_TERMINATED),
    ("Wind down", EventType.SHUTDOWN), ("Ceased operations", EventType.SHUTDOWN), ("Chapter 7", EventType.SHUTDOWN),
    ("ABC", EventType.SHUTDOWN), ("Bankruptcy (Chapter 7)", EventType.SHUTDOWN),
    ("Chapter 11", EventType.BANKRUPTCY_CH11), ("Reorganisation", EventType.BANKRUPTCY_CH11),
    ("Secondary", EventType.SECONDARY), ("Tender offer (sold)", EventType.SECONDARY), ("Sale of shares", EventType.SECONDARY),
    ("Bought shares", EventType.SECONDARY_PURCHASE), ("Tender offer (bought)", EventType.SECONDARY_PURCHASE),
    ("Term sheet", EventType.TERM_SHEET), ("LOI (financing)", EventType.TERM_SHEET), ("TS signed", EventType.TERM_SHEET),
    ("Dividend", EventType.DISTRIBUTION), ("Escrow release", EventType.DISTRIBUTION), ("Earn-out", EventType.DISTRIBUTION),
    ("Warrant exercise", EventType.OWNERSHIP_ADJUSTMENT), ("Cap table restatement", EventType.OWNERSHIP_ADJUSTMENT),
    ("True-up", EventType.OWNERSHIP_ADJUSTMENT),
    ("First check", EventType.NEW_INVESTMENT), ("New portfolio company", EventType.NEW_INVESTMENT),
    ("Note repayment", EventType.NOTE_REPAID), ("Loan repaid", EventType.NOTE_REPAID),
])
def test_synonyms_resolve_and_are_recorded(raw, canon, ncfg):
    value, corr = nz.normalize_event_type(raw, ncfg)
    assert value == canon.value
    assert corr is not None and corr.kind == "event_type" and corr.method in ("synonym", "fold")
    assert corr.original == raw and corr.resolved == canon.value


@pytest.mark.parametrize("canon", [e.value for e in EventType])
def test_canonical_names_pass_through_untouched(canon, ncfg):
    assert nz.normalize_event_type(canon, ncfg) == (canon, None)


def test_case_only_difference_is_recorded_as_fold(ncfg):
    value, corr = nz.normalize_event_type("acquisition (closed)", ncfg)
    assert value == EventType.ACQ_CLOSED.value and corr.method == "fold"


def test_trailing_space_is_recorded_not_silent(ncfg):
    value, corr = nz.normalize_event_type("IPO ", ncfg)
    assert value == "IPO" and corr is not None and corr.method == "whitespace"


def test_closed_qualifier_is_kept_but_exchange_qualifier_is_dropped(ncfg):
    assert nz.normalize_event_type("Acquisition (Closed)", ncfg)[0] == EventType.ACQ_CLOSED.value
    value, corr = nz.normalize_event_type("IPO (NYSE)", ncfg)
    assert value == "IPO" and "dropped" in corr.detail


# ---------------------------------------------------------------- event types: typos (§1.2)

@pytest.mark.parametrize("raw,canon,d", [
    ("Aquisition (Closed)", EventType.ACQ_CLOSED, 1),
    ("Priced Equtiy Round", EventType.PRICED_ROUND, 1),
    ("Convertable Note", EventType.CONVERTIBLE_NOTE, 1),
    ("Shutdwon", EventType.SHUTDOWN, 1),
    ("Secondry Sale", EventType.SECONDARY, 1),
    ("Term Sheet Signd", EventType.TERM_SHEET, 1),
    ("Priced Equity Rund", EventType.PRICED_ROUND, 1),
    ("Acquisiton (Anounced)", EventType.ACQ_ANNOUNCED, 2),
])
def test_typos_within_two_edits_resolve_with_distance(raw, canon, d, ncfg):
    value, corr = nz.normalize_event_type(raw, ncfg)
    assert value == canon.value
    assert corr.kind == "event_type" and corr.method == f"distance={d}"


@pytest.mark.parametrize("raw,candidates", [
    ("Acquisition", ("Acquisition (Closed)", "Acquisition (Announced)")),
    ("Sale", ("Secondary Sale", "Acquisition (Closed)")),
    ("loi", ("Acquisition (Announced)", "Term Sheet Signed")),
    ("LOI", ("Acquisition (Announced)", "Term Sheet Signed")),
    ("Tender offer", ("Secondary Sale", "Secondary Purchase")),
    ("Bankruptcy", ("Shutdown", "Bankruptcy (Chapter 11)")),
    ("Merger", ("Acquisition (Closed)", "Acquisition (Announced)")),
])
def test_bare_ambiguous_words_block_and_name_both_candidates(raw, candidates, ncfg):
    value, corr = nz.normalize_event_type(raw, ncfg)
    assert value == raw                      # raw text kept for M-999
    assert corr is not None and corr.kind == "ambiguous"
    for c in candidates:
        assert c in corr.detail


@pytest.mark.parametrize("raw", ["IPOO", "Sfae", "Notee", "Exitt"])
def test_short_tokens_are_never_typo_matched(raw, ncfg):
    """< min_length_for_fuzzy: a one-letter edit on a four-letter word is a different word."""
    value, corr = nz.normalize_event_type(raw, ncfg)
    assert value == raw
    assert corr is not None and corr.kind == "ambiguous" and "too short" in corr.detail


def test_three_edits_away_is_not_matched(ncfg):
    assert nz.normalize_event_type("Prized Eqity Rounds", ncfg) == ("Prized Eqity Rounds", None)


def test_unknown_type_passes_through_for_x909(ncfg):
    assert nz.normalize_event_type("SPAC Merger", ncfg) == ("SPAC Merger", None)
    assert nz.normalize_event_type(None, ncfg) == ("", None)
    assert nz.normalize_event_type("   ", ncfg) == ("", None)


def test_synonym_table_has_no_collisions():
    """Every folded synonym maps to exactly one canonical (checked at import; asserted here)."""
    seen: dict[str, str] = {}
    for spelling, canon in nz.EVENT_INDEX.items():
        assert seen.setdefault(spelling, canon) == canon
    assert set(nz.EVENT_INDEX.values()) == {e.value for e in EventType}


# ---------------------------------------------------------------- headers (§2.2)

_PORT = (list(PORTFOLIO_COLUMNS), PORTFOLIO_HEADER_ALIASES)
_ACT = (list(ACTIVITY_COLUMNS), ACTIVITY_HEADER_ALIASES)


@pytest.mark.parametrize("raw,canon,method,tab", [
    ("Company", "Company", None, _PORT),
    ("company", "Company", "fold", _PORT),
    ("  Prior Mark ($M) ", "Prior Mark ($M)", None, _PORT),
    ("Portfolio Company", "Company", "alias", _PORT),
    ("Carrying Value", "Prior Mark ($M)", "alias", _PORT),
    ("FD %", "Ownership (FD %)", "alias", _PORT),
    ("Post-Money", "Latest Post-Money ($M)", "alias", _PORT),
    ("Latest Post Money ($M)", "Latest Post-Money ($M)", "distance=1", _PORT),
    ("Ownership (FD%)", "Ownership (FD %)", "distance=1", _PORT),
    ("Prior Mark $M", "Prior Mark ($M)", "distance=2", _PORT),
    ("Post-Money", "Post-Money / Deal Value ($M)", "alias", _ACT),
    ("Post Money / Deal Value ($M)", "Post-Money / Deal Value ($M)", "distance=1", _ACT),
    ("Event Type", "Event", "alias", _ACT),
    ("Distributions", "Proceeds to HC ($M)", "alias", _ACT),
    ("Distributions", "Realized ($M)", "alias", _PORT),
    ("Comments", "Notes", "alias", _ACT),
])
def test_header_resolution(raw, canon, method, tab, ncfg):
    known, aliases = tab
    value, corr = nz.normalize_header(raw, known, aliases, ncfg)
    assert value == canon
    if method is None:
        assert corr is None
    else:
        assert corr.kind == "header" and corr.method == method and corr.resolved == canon


def test_unknown_header_is_unknown_not_guessed(ncfg):
    assert nz.normalize_header("Board Seat", *_PORT, ncfg) == (None, None)
    assert nz.normalize_header("Lead Investor", *_ACT, ncfg) == (None, None)
    assert nz.normalize_header(None, *_ACT, ncfg) == (None, None)


def test_short_header_typo_is_refused(ncfg):
    value, corr = nz.normalize_header("Dat", *_ACT, ncfg)
    assert value is None and corr.kind == "ambiguous" and "too short" in corr.detail


def test_find_header_row_skips_title_rows(ncfg):
    rows = [
        ("HC Portfolio — Q3 2026", None, None, None),
        (None, None, None, None),
        ("Company", "Sector", "Fund", "Stage"),
        ("Alpha", "SaaS", "Fund I", "Seed"),
    ]
    found = nz.find_header_row(rows, *_PORT, ncfg)
    assert found is not None
    row, idx, raw, corrs = found
    assert row == 3 and idx == {"Company": 0, "Sector": 1, "Fund": 2, "Stage": 3} and corrs == []


def test_find_header_row_needs_three_known_columns(ncfg):
    rows = [("Company", "Notes", "x"), ("Company", "Stage", "y")]
    assert nz.find_header_row(rows, *_PORT, ncfg) is None


def test_duplicate_column_is_ambiguous(ncfg):
    rows = [("Company", "Name", "Sector", "Fund")]
    _, idx, _, corrs = nz.find_header_row(rows, *_PORT, ncfg)
    assert idx["Company"] == 0
    assert any(c.kind == "ambiguous" and "twice" in c.detail for c in corrs)


def test_closest_header_names_the_nearest_raw_header():
    assert nz.closest_header("Prior Mark ($M)", ["Company", "Prior Mrk", "Cash"]) == "Prior Mrk"


# ---------------------------------------------------------------- sheets (§2.1)

def test_find_sheet_exact_folded_and_fallback():
    assert nz.find_sheet(["Portfolio", "x"], "Portfolio")[:2] == ("Portfolio", None)
    name, corr, _ = nz.find_sheet([" portfolio ", "x"], "Portfolio")
    assert name == " portfolio " and corr.kind == "sheet" and corr.method == "fold"
    name, corr, _ = nz.find_sheet(["Holdings", "x"], "Portfolio")
    assert name == "Holdings" and corr.method == "fallback"
    name, corr, hits = nz.find_sheet(["Book", "Positions"], "Portfolio")
    assert name is None and sorted(hits) == ["Book", "Positions"]


@pytest.mark.parametrize("sheet,label", [
    ("Q4 2026 Activity", "Q4 2026"), ("Q4-2026 Activity", "Q4 2026"), ("Q4'26 Activity", "Q4 2026"),
    ("4Q26 Activity", "Q4 2026"), ("Activity Q4 2026", "Q4 2026"), ("2026 Q4 Activity", "Q4 2026"),
    ("Q4 2026 Events", "Q4 2026"), ("Q1 2027 Activity", "Q1 2027"),
    ("Activity", None), ("Events", None), ("Q4 Activity", None),
])
def test_relaxed_sheet_forms_are_candidates_and_labels_parse(sheet, label):
    assert nz.relaxed_activity_candidates([sheet, "Portfolio", "Field Definitions"]) == [sheet]
    assert nz.parse_quarter_label(sheet) == label


# ---------------------------------------------------------------- companies (§2.3)

BOOK = ["Nimbrel", "Dovelane Systems", "Aravine", "Aravine Labs", "Marrowick Bio", "Tarnwick Aerospace"]


@pytest.mark.parametrize("raw,name,method", [
    ("Nimbrel", "Nimbrel", None),
    ("  Nimbrel ", "Nimbrel", "whitespace"),
    ("nimbrel", "Nimbrel", "fold"),
    ("NIMBREL INC.", "Nimbrel", "suffix"),
    ("Dovelane Systems, Inc.", "Dovelane Systems", "suffix"),
    ("Marrowick Bio Ltd", "Marrowick Bio", "suffix"),
    ("Nimbrel LLC", "Nimbrel", "suffix"),
    ("Nimbrel (formerly Skylark)", "Nimbrel", "formerly"),
    ("Skylark (formerly Nimbrel)", "Nimbrel", "formerly"),
    ("Skylark, formerly Nimbrel", "Nimbrel", "formerly"),
    ("Nimbrel → Skylark", "Nimbrel", "formerly"),
    ("Dovelane Sytems", "Dovelane Systems", "distance=1"),
    ("Tarnwick Aerospce", "Tarnwick Aerospace", "distance=1"),
    ("Dovelane  Systems", "Dovelane Systems", "whitespace"),
])
def test_company_matching(raw, name, method, ncfg):
    value, corr = nz.match_company(raw, BOOK, ncfg)
    assert value == name
    if method is None:
        assert corr is None
    else:
        assert corr.kind == "company" and corr.method == method and corr.resolved == name


def test_short_company_typo_is_refused_naming_the_candidate(ncfg):
    value, corr = nz.match_company("Aravin", BOOK, ncfg)          # 6 chars < 8
    assert value == "Aravin" and corr.kind == "ambiguous" and "Aravine" in corr.detail


def test_two_edits_on_a_company_is_not_matched(ncfg):
    assert nz.match_company("Dovelane Sytem", BOOK, ncfg) == ("Dovelane Sytem", None)


def test_company_tie_is_ambiguous(ncfg):
    book = ["Aravine Labs", "Aravine Lab", "Nimbrel"]
    value, corr = nz.match_company("Aravine Labz", book, ncfg)
    assert value == "Aravine Labz" and corr.kind == "ambiguous"
    assert "Aravine Labs" in corr.detail and "Aravine Lab" in corr.detail


def test_formerly_with_both_sides_in_book_is_ambiguous(ncfg):
    value, corr = nz.match_company("Nimbrel (formerly Aravine)", BOOK, ncfg)
    assert corr.kind == "ambiguous" and "Nimbrel" in corr.detail and "Aravine" in corr.detail


def test_unknown_company_passes_through_for_x901(ncfg):
    assert nz.match_company("Ghost", BOOK, ncfg) == ("Ghost", None)


def test_infer_fund():
    assert nz.infer_fund("", "First check from Fund III") == "Fund III"
    assert nz.infer_fund("fund ii lead", "") == "Fund II"
    assert nz.infer_fund("no vehicle named", "") == "Unassigned"


# ---------------------------------------------------------------- numbers (§2.3)

@pytest.mark.parametrize("raw,value", [
    (28.2, 28.2), (12, 12.0), ("28.2", 28.2), ("$28.2M", 28.2), ("$28.2 M", 28.2), ("28.2m", 28.2),
    ("$28,200,000", 28200000.0), ("(1.2)", -1.2), ("1.2%", 0.012), ("5.5 %", 0.055), (" 12 ", 12.0),
    ("-3.5", -3.5), ("$-1.2", -1.2), ("1.5k", 0.0015), ("2bn", 2000.0), ("1e12", 1e12),
])
def test_coerce_number(raw, value):
    got, corr = nz.coerce_number(raw)
    assert got == pytest.approx(value)
    assert (corr is None) == isinstance(raw, (int, float))
    if corr is not None:
        assert corr.kind == "value" and corr.original == raw


@pytest.mark.parametrize("raw", ["", "-", "—", "n/a", "N/A", "na", "tbd", "TBD", "?", "none", "null", None])
def test_blank_tokens_are_none_silently(raw):
    assert nz.coerce_number(raw) == (None, None)


@pytest.mark.parametrize("raw", ["abc", "twelve", "1.2.3", "(1.2", True, datetime(2026, 1, 1)])
def test_non_numeric_is_unparseable_not_none(raw):
    got, corr = nz.coerce_number(raw)
    assert got is None and corr.kind == "unparseable"


@pytest.mark.parametrize("raw,hit", [("€28.2M", "€"), ("£5", "£"), ("¥100", "¥"), ("EUR 5", "EUR"), ("5 GBP", "GBP"),
                                     ("CHF 2.1", "CHF"), ("12 JPY", "JPY"), ("CAD 3", "CAD"), ("AUD 4", "AUD")])
def test_currency_in_value_cell_is_x920_kind(raw, hit):
    got, corr = nz.coerce_number(raw)
    assert got is None and corr.kind == "currency" and corr.detail == hit


def test_dollar_and_usd_are_fine():
    assert nz.currency_hit("$28.7M round, USD") is None
    assert nz.currency_hit("Cadence of audits; cash in escrow") is None   # 'CAD' only as a whole word
    assert nz.currency_hit("Round denominated in EUR") == "EUR"


def test_musd_unit_suspicion(ncfg):
    value, corrs = nz.coerce_musd("$28,200,000", ncfg)
    assert value == pytest.approx(28.2)
    assert [c.kind for c in corrs] == ["value", "unit"] and "dollars" in corrs[1].detail
    value, corrs = nz.coerce_musd(1837.9, ncfg)
    assert value == 1837.9 and corrs == []
    value, corrs = nz.coerce_musd(250000.0, ncfg)
    assert value == pytest.approx(0.25) and corrs[0].kind == "unit"


def test_percent_points_heuristic(ncfg):
    assert nz.coerce_percent(0.055, ncfg) == (0.055, [])
    value, corrs = nz.coerce_percent(5.5, ncfg)
    assert value == pytest.approx(0.055) and corrs[0].kind == "unit" and "percentage points" in corrs[0].detail
    value, corrs = nz.coerce_percent("7.9%", ncfg)             # the sign already converted it
    assert value == pytest.approx(0.079) and [c.kind for c in corrs] == ["value"]
    value, corrs = nz.coerce_percent(150, ncfg)
    assert value == 150 and corrs[0].kind == "percent_block"
    value, corrs = nz.coerce_percent(2.07, ncfg, points_heuristic=False)   # ARR growth of 207%
    assert value == 2.07 and corrs == []
    value, corrs = nz.coerce_percent(150, ncfg, points_heuristic=False)
    assert corrs[0].kind == "percent_block"


# ---------------------------------------------------------------- dates (§2.3)

@pytest.mark.parametrize("raw,expected,method", [
    (datetime(2026, 8, 15, 10, 0), date(2026, 8, 15), None),
    (date(2026, 8, 15), date(2026, 8, 15), None),
    (46249, date(2026, 8, 15), "excel-serial"),
    (46249.0, date(2026, 8, 15), "excel-serial"),
    ("2026-08-15", date(2026, 8, 15), "iso"),
    ("08/15/2026", date(2026, 8, 15), "m/d/yyyy"),
    ("8/15/26", date(2026, 8, 15), "m/d/yy"),
    ("15-Aug-2026", date(2026, 8, 15), "dd-Mon-yyyy"),
    ("Aug 15, 2026", date(2026, 8, 15), "Mon d, yyyy"),
    ("2026/08/15", date(2026, 8, 15), "yyyy/mm/dd"),
    ("25/12/2026", date(2026, 12, 25), "day-first"),
])
def test_coerce_date_forms(raw, expected, method):
    got, corr = nz.coerce_date(raw)
    assert got == expected
    if method is None:
        assert corr is None
    else:
        assert corr.kind == "value" and corr.method == method and corr.resolved == expected.isoformat()


def test_ambiguous_day_month_is_month_first_and_recorded():
    got, corr = nz.coerce_date("03/04/2026")
    assert got == date(2026, 3, 4)
    assert "ambiguous" in corr.detail and "2026-04-03" in corr.detail


def test_unambiguous_slash_date_has_no_ambiguity_note():
    got, corr = nz.coerce_date("08/15/2026")
    assert got == date(2026, 8, 15) and corr.detail == ""


@pytest.mark.parametrize("raw", ["foo", "2026-13-01", "32/01/2026", 1234, 99999, True])
def test_unparseable_date_raises(raw):
    with pytest.raises(nz.DateParseError):
        nz.coerce_date(raw)


def test_blank_date_is_none():
    assert nz.coerce_date(None) == (None, None)
    assert nz.coerce_date("-") == (None, None)


# ---------------------------------------------------------------- structure (§2.4)

def test_row_classifiers():
    assert nz.row_is_blank((None, "", None))
    assert not nz.row_is_blank((None, 0, None))
    assert nz.row_is_total(("Total", 1, 2)) and nz.row_is_total((None, "Grand Total", 3)) and nz.row_is_total(("SUM", None))
    assert not nz.row_is_total(("Totally Ltd", 1))
    assert nz.row_is_note(("Source: CFO pack, unaudited.", None, None))
    assert not nz.row_is_note(("Alpha", "SaaS", None))
    assert not nz.row_is_note((datetime(2026, 1, 1), None))


# ---------------------------------------------------------------- a unit is not a typo

@pytest.mark.parametrize("header, canon", [
    ("Invested ($K)", "Invested ($M)"),
    ("Latest Post-Money ($K)", "Latest Post-Money ($M)"),
    ("Prior Mark ($B)", "Prior Mark ($M)"),
])
def test_a_unit_difference_refuses_the_header_rather_than_reading_it_as_a_typo(header, canon, ncfg):
    """`Invested ($K)` sits one edit from `Invested ($M)`, so typo tolerance used to resolve it —
    and because ownership x post-money scales together, X-904 still reconciled and the whole book
    came back a thousand times too large, reading Ready. A wrong number, quietly, is the failure
    this codebase least tolerates, so a differing unit refuses the column instead."""
    got, corr = nz.normalize_header(header, [canon], {}, ncfg)
    assert got is None, f"{header} must not resolve to {canon}"
    assert corr is not None and corr.kind == "ambiguous" and corr.method == "unit"


def test_the_same_unit_written_two_ways_still_resolves(ncfg):
    """The guard compares units, it does not demand identical punctuation: `$M` and `($M)` are one
    unit, and a real typo alongside a matching unit still corrects as before."""
    assert nz.normalize_header("Prior Mark $M", ["Prior Mark ($M)"], {}, ncfg)[0] == "Prior Mark ($M)"
    assert nz.normalize_header("Invsted ($M)", ["Invested ($M)"], {}, ncfg)[0] == "Invested ($M)"
    assert nz.normalize_header("Runway (mo)", ["Runway (mo)"], {}, ncfg)[0] == "Runway (mo)"
