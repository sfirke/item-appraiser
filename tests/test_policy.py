import pytest

from item_appraiser.models import Appraisal, Condition
from item_appraiser.policy import appraisal_buy_value, appraisal_loan_value, buy_value, loan_value


@pytest.mark.parametrize(
    ("condition", "expected"),
    [(Condition.NEW, 100), (Condition.LIKE_NEW, 80), (Condition.USED, 60)],
)
def test_buy_value_applies_condition_multiplier(condition, expected):
    assert buy_value(100, condition) == expected


@pytest.mark.parametrize(
    ("buy", "expected"),
    [(10, 5), (75, 37.5), (76, 19), (270, 67.5)],
)
def test_loan_value_is_half_up_to_75_then_a_quarter(buy, expected):
    assert loan_value(buy) == expected


def test_appraisal_values_chain_through_policy():
    appraisal = Appraisal(new_price_usd=170, condition=Condition.USED)
    assert appraisal_buy_value(appraisal) == 102
    assert appraisal_loan_value(appraisal) == 25.5


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
