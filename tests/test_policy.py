from datetime import date

import pytest

from item_appraiser.models import Appraisal, Condition, ResaleDemand
from item_appraiser.policy import (
    age_factor,
    age_in_years,
    appraisal_buy_value,
    appraisal_loan_value,
    buy_value,
    loan_value,
)


@pytest.mark.parametrize(
    ("condition", "expected"),
    [(Condition.NEW, 100), (Condition.LIKE_NEW, 80), (Condition.USED, 60)],
)
def test_buy_value_applies_condition_multiplier(condition, expected):
    assert buy_value(100, condition) == expected


@pytest.mark.parametrize(
    ("condition", "expected"),
    [(Condition.NEW, 100), (Condition.LIKE_NEW, 40), (Condition.USED, 25)],
)
def test_weak_resale_demand_lowers_used_values_only(condition, expected):
    assert buy_value(100, condition, ResaleDemand.WEAK) == expected
    assert appraisal_buy_value(Appraisal(100, condition, ResaleDemand.WEAK)) == expected


@pytest.mark.parametrize(
    ("buy", "expected"),
    [(0, 0), (10, 5), (50, 25), (76, 31.5), (270, 80)],
)
def test_loan_value_is_half_of_first_50_plus_a_quarter_of_the_rest(buy, expected):
    assert loan_value(buy) == expected


def test_loan_value_never_decreases_as_buy_value_rises():
    values = [loan_value(cents / 100) for cents in range(0, 50_000, 25)]
    assert values == sorted(values)


def test_appraisal_values_chain_through_policy():
    appraisal = Appraisal(new_price_usd=170, condition=Condition.USED)
    assert appraisal_buy_value(appraisal) == 102
    assert appraisal_loan_value(appraisal) == 38


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("new", Condition.NEW),
        ("Like New", Condition.LIKE_NEW),
        ("like_new", Condition.LIKE_NEW),
        ("", Condition.USED),
        (None, Condition.USED),
        ("fair", Condition.USED),
    ],
)
def test_condition_parse(text, expected):
    assert Condition.parse(text) == expected


NOV_2026 = date(2026, 11, 25)


def test_age_counts_from_the_middle_of_the_release_year_and_never_goes_negative():
    assert age_in_years(2019, date(2026, 7, 2)) == pytest.approx(7.0, abs=0.01)
    assert age_in_years(2027, NOV_2026) == 0


@pytest.mark.parametrize(
    ("release_year", "expected"),
    # 399 x 0.82 x 0.83 ** age, at ages 7.4 and 5.4.
    [(2019, 82.43), (2021, 119.65)],
)
def test_a_used_device_follows_the_age_curve(release_year, expected):
    assert buy_value(399, Condition.USED, release_year=release_year, as_of=NOV_2026) == expected


def test_a_recent_device_keeps_the_ordinary_condition_multipliers():
    for condition, expected in [
        (Condition.NEW, 100),
        (Condition.LIKE_NEW, 80),
        (Condition.USED, 60),
    ]:
        assert buy_value(100, condition, release_year=2026, as_of=NOV_2026) == expected
    assert age_factor(2026, NOV_2026) == 1


def test_condition_still_scales_an_older_device():
    used = buy_value(1000, Condition.USED, release_year=2020, as_of=NOV_2026)
    like_new = buy_value(1000, Condition.LIKE_NEW, release_year=2020, as_of=NOV_2026)
    new = buy_value(1000, Condition.NEW, release_year=2020, as_of=NOV_2026)
    assert like_new == pytest.approx(used * 0.8 / 0.6, abs=0.01)
    assert new == pytest.approx(used / 0.6, abs=0.01)
    assert new < 1000


def test_a_device_loses_value_as_time_passes_without_reappraising():
    appraisal = Appraisal(500, Condition.USED, release_year=2022)
    values = [appraisal_buy_value(appraisal, date(year, 6, 1)) for year in range(2024, 2032)]
    assert values == sorted(values, reverse=True)
    assert len(set(values)) == len(values)
    assert appraisal_loan_value(appraisal, NOV_2026) == loan_value(
        appraisal_buy_value(appraisal, NOV_2026)
    )


def test_a_very_old_device_bottoms_out_at_the_floor():
    assert buy_value(1000, Condition.USED, release_year=1995, as_of=NOV_2026) == 50
    assert buy_value(1000, Condition.USED, release_year=2005, as_of=NOV_2026) == 50


def test_release_year_overrides_weak_resale_demand():
    assert buy_value(
        399, Condition.USED, ResaleDemand.WEAK, release_year=2019, as_of=NOV_2026
    ) == buy_value(399, Condition.USED, release_year=2019, as_of=NOV_2026)
