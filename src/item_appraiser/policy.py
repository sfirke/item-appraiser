"""Value policy: how an appraisal turns into buy and loan values.

These are policy choices, not estimates, so they live in plain code rather than
in any appraiser. Changing them re-prices every stored appraisal for free.
"""

from item_appraiser.models import Appraisal, Condition

CONDITION_MULTIPLIERS = {
    Condition.NEW: 1.0,
    Condition.LIKE_NEW: 0.8,
    Condition.USED: 0.6,
}

# A loan is worth half of the item's value up to this threshold plus a quarter of
# any value above it, like tax brackets, so loan value never drops as value rises.
# The lower rate on the top slice reflects that expensive items are more rentable
# and less likely to be bought outright.
LOAN_THRESHOLD_USD = 75.0
LOAN_FRACTION_AT_OR_BELOW = 0.5
LOAN_FRACTION_ABOVE = 0.25


def buy_value(new_price_usd: float, condition: Condition) -> float:
    """What the item would cost to buy in its current condition."""
    return round(new_price_usd * CONDITION_MULTIPLIERS[condition], 2)


def loan_value(buy_value_usd: float) -> float:
    """What borrowing the item once is worth to the borrower."""
    below = min(buy_value_usd, LOAN_THRESHOLD_USD)
    above = max(buy_value_usd - LOAN_THRESHOLD_USD, 0)
    return round(below * LOAN_FRACTION_AT_OR_BELOW + above * LOAN_FRACTION_ABOVE, 2)


def appraisal_buy_value(appraisal: Appraisal) -> float:
    return buy_value(appraisal.new_price_usd, appraisal.condition)


def appraisal_loan_value(appraisal: Appraisal) -> float:
    return loan_value(appraisal_buy_value(appraisal))
