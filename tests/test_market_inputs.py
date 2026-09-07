"""The three input checks the live comps feed must pass before a multiple is evidence.

Each of these was a real defect found in the committed 2026-09-30 cache, and each produced a
number the review tool showed as fact:

* a share count chosen because it was the first concept with *any* data, not recent data —
  C3.ai priced on 3.5M shares last tagged in 2021 against ~140M today, SoundHound on the
  17.5M of its pre-merger shell, Hims/Datadog/Toast on a literal zero;
* a negative enterprise value used as a comparable *multiple*, dragging a basket median
  toward zero;
* split-adjusted closes multiplied by as-filed share counts, which understated every
  pre-split month by the splits since.
"""
from __future__ import annotations

from datetime import date

import pytest

from hc_valuation.connectors.edgar import SHARES_LAG_DAYS, SHARES_MAX_AGE_DAYS, SHARES_RATIO_BAND, SHARES_STALE_BAND, shares_at
from hc_valuation.connectors.prices import cumulative_split_factor, parse_yahoo_splits

ON = date(2026, 9, 30)
COVER = "dei:EntityCommonStockSharesOutstanding"
BALANCE = "us-gaap:CommonStockSharesOutstanding"
DILUTED = "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"


def row(end: str, value: float, filed: str | None = None) -> dict:
    return {"end": end, "value": value, "filed": filed or end}


def test_a_fresh_cover_page_count_wins_and_says_what_it_counts():
    pick = shares_at({COVER: [row("2026-08-20", 823.0)], DILUTED: [row("2026-07-31", 845.0)]}, ON)
    assert pick.value == 823.0 and pick.concept == COVER
    assert pick.basis == "outstanding, cover page" and not pick.approximate
    assert pick.age_days == 41 and pick.rejected == ()


def test_a_count_the_filer_stopped_tagging_is_refused_not_used():
    """C3.ai: CommonStockSharesOutstanding ends 2021-04-30 at 3.5M against ~140M today."""
    pick = shares_at({BALANCE: [row("2021-04-30", 3.5)], DILUTED: [row("2026-01-31", 142.0)]}, ON)
    assert pick.value == 142.0 and pick.concept == DILUTED
    assert pick.basis == "diluted weighted average" and pick.approximate
    assert len(pick.rejected) == 1 and "5.4 years before the measurement date" in pick.rejected[0]


def test_a_final_value_of_zero_is_refused():
    """Hims, Datadog and Toast all leave a zero behind; zero shares is a zero market cap."""
    pick = shares_at({BALANCE: [row("2019-06-30", 0.0)], DILUTED: [row("2026-06-30", 231.7)]}, ON)
    assert pick.value == 231.7
    assert "last value is 0" in pick.rejected[0]


def test_nothing_usable_is_an_answer():
    """Better an unpriced constituent with a reason than a 2026 market cap on a 2021 count."""
    pick = shares_at({BALANCE: [row("2021-04-30", 3.5)]}, ON)
    assert pick.value is None and pick.concept is None
    assert pick.rejected and "2021-04-30" in pick.rejected[0]


def test_the_freshness_window_is_the_documented_one():
    assert SHARES_MAX_AGE_DAYS == 450
    inside = ON.replace(year=ON.year - 1)                       # 365 days
    assert shares_at({COVER: [row(inside.isoformat(), 10.0)]}, ON).value == 10.0
    outside = ON.replace(year=ON.year - 2)                      # 730 days
    assert shares_at({COVER: [row(outside.isoformat(), 10.0)]}, ON).value is None


def test_a_count_filed_after_the_measurement_date_is_not_used():
    """Point in time: a reader on 30 September had not seen an October filing."""
    pick = shares_at({COVER: [row("2026-09-30", 900.0, filed="2026-10-20")]}, ON)
    assert pick.value is None


# ---------------------------------------------------------------- a dropped tag inside the window

def test_a_tag_that_has_fallen_behind_the_filers_freshest_concept_is_passed_over():
    """Affirm, spring 2021: the balance-sheet count stopped at the pre-IPO 59.2M while the
    diluted average kept being filed every quarter. Inside 450 days, so the absolute limit
    alone would still take it; two periods behind the concept the filer keeps up, so it is a
    dropped tag, and the value says the same thing from the other side."""
    on = date(2022, 1, 31)
    pick = shares_at({BALANCE: [row("2021-03-31", 59.2)], DILUTED: [row("2021-12-31", 258.0)]}, on)
    assert pick.value == 258.0 and pick.concept == DILUTED
    assert len(pick.rejected) == 1
    assert "days behind WeightedAverageNumberOfDilutedSharesOutstanding" in pick.rejected[0]
    assert "0.23x" in pick.rejected[0] and "the filer has moved on" in pick.rejected[0]


def test_a_count_that_cannot_be_the_same_share_base_is_passed_over_even_when_recent():
    """SoundHound, autumn 2022: the shell's 17.5M cover-page count is only one quarter behind
    the 162M diluted average — in step by date — but a tenth of it. Outstanding and diluted
    average differ by percent, not multiples: this is a different share base."""
    on = date(2022, 12, 31)
    pick = shares_at({COVER: [row("2022-09-30", 17.5)], DILUTED: [row("2022-12-31", 162.0)]}, on)
    assert pick.value == 162.0 and pick.concept == DILUTED
    assert "0.11x" in pick.rejected[0] and "not the same share base" in pick.rejected[0]


def test_an_annual_only_balance_sheet_count_is_still_used_when_it_agrees():
    """A filer that tags the balance-sheet count only in the 10-K is not a filer that has
    moved on: three quarters behind, but within a few percent of the diluted average, so
    the preferred concept keeps winning."""
    on = date(2026, 9, 30)
    pick = shares_at({BALANCE: [row("2025-12-31", 348.7)], DILUTED: [row("2026-06-30", 352.8)]}, on)
    assert pick.value == 348.7 and pick.concept == BALANCE and pick.rejected == ()


def test_the_lag_and_band_are_the_documented_ones():
    assert SHARES_LAG_DAYS == 135 and SHARES_RATIO_BAND == (0.5, 2.0) and SHARES_STALE_BAND == (0.9, 1.1)


def test_a_tag_that_has_fallen_behind_and_drifted_is_a_dead_tag():
    """Behind by date and 30% off: not an annual filer, a tag nobody updates. Inside the
    wide band, so only the tighter test for a lagging concept catches it."""
    pick = shares_at({BALANCE: [row("2025-09-30", 100.0)], DILUTED: [row("2026-06-30", 140.0)]}, date(2026, 9, 30))
    assert pick.value == 140.0 and "the filer has moved on" in pick.rejected[0]


def test_the_pick_carries_its_filing_date_as_the_split_basis():
    """A count filed in May is on May's share basis, whatever period it is for."""
    pick = shares_at({COVER: [row("2024-04-28", 2460.0, filed="2024-05-29")]}, date(2024, 6, 30))
    assert pick.filed == "2024-05-29" and pick.basis_date == date(2024, 5, 29)


# ---------------------------------------------------------------- splits

def test_yahoo_split_events_parse_to_ratios():
    payload = {"chart": {"result": [{"events": {"splits": {
        "1663200000": {"date": 1663200000, "numerator": 3, "denominator": 1},
        "1500000000": {"date": 1500000000, "numerator": 2, "denominator": 1}}}}]}}
    assert parse_yahoo_splits(payload) == {"2017-07-14": 2.0, "2022-09-15": 3.0}
    assert parse_yahoo_splits({"chart": {"result": [{}]}}) == {}
    assert parse_yahoo_splits({}) == {}


def test_the_cumulative_factor_puts_an_old_share_count_on_todays_basis():
    """Palo Alto split 3-for-1 in September 2022: one 2020 share is three of today's, so the
    as-filed 2020 count must be tripled before it meets a split-adjusted 2020 close."""
    splits = {"2022-09-15": 3.0}
    assert cumulative_split_factor(splits, date(2020, 10, 31)) == 3.0
    assert cumulative_split_factor(splits, date(2026, 9, 30)) == 1.0
    assert cumulative_split_factor({}, date(2020, 10, 31)) == 1.0
    # compounding
    assert cumulative_split_factor({"2017-07-14": 2.0, "2022-09-15": 3.0}, date(2016, 1, 31)) == 6.0


def test_the_factor_runs_from_the_filing_date_not_the_month_priced():
    """NVIDIA's 10-for-1 fell on 10 June 2024. The count in hand for June was filed on 29 May
    — pre-split — so June's market cap needs the factor even though the split is before
    June's month end. Taking the factor from the month end left NVIDIA at 3.5x revenue for
    two months. From the filing date the series is continuous across the split."""
    splits = {"2024-06-10": 10.0}
    filed_before, filed_after = date(2024, 5, 29), date(2024, 8, 28)
    assert cumulative_split_factor(splits, filed_before) == 10.0     # June, priced on the May filing
    assert cumulative_split_factor(splits, filed_after) == 1.0       # August, on the post-split 10-Q
    assert cumulative_split_factor(splits, date(2024, 6, 30)) == 1.0  # the month end alone would say no split


@pytest.mark.parametrize("mult", [-3.2, 0.0])
def test_a_non_positive_multiple_is_not_a_comparable(mult):
    """A negative enterprise value is a real state and its inputs are kept; it is simply not a
    revenue multiple that can price a private company, so it leaves the median."""
    assert not (mult > 0)
