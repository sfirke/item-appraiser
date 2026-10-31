import pytest

from item_appraiser.models import Appraisal, Condition, ResaleDemand
from item_appraiser.policy import appraisal_buy_value, appraisal_loan_value, buy_value, loan_value


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
