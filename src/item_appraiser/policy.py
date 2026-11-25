"""Value policy: how an appraisal turns into buy and loan values.

These are policy choices, not estimates, so they live in plain code rather than
in any appraiser. Changing them re-prices every stored appraisal for free.

Values for devices priced by age depend on the date: they fall as the device
gets older, without re-appraising anything.
"""

from datetime import date

from item_appraiser.models import Appraisal, Condition, ResaleDemand

CONDITION_MULTIPLIERS = {
    Condition.NEW: 1.0,
    Condition.LIKE_NEW: 0.8,
    Condition.USED: 0.6,
}

# Kinds of item that sell for far less secondhand than their new price suggests,
# such as large furniture and china. Unused ones keep their full value.
WEAK_RESALE_MULTIPLIERS = {
    Condition.NEW: 1.0,
    Condition.LIKE_NEW: 0.4,
    Condition.USED: 0.25,
}

# Phones, tablets, laptops and smartwatches lose value with age, not wear. A used
# one sells for about AGE_VALUE_AT_RELEASE x AGE_VALUE_PER_YEAR ** age of its new
# price: fitted to what 55 models released from 2014 to 2025 sold for secondhand
# in 2026 (see the README). The age factor rescales that curve to the "used"
# multiplier, so a device keeps the ordinary condition multipliers until the curve
# drops below them (at about 20 months old) and loses 17% a year from then on.
AGE_VALUE_AT_RELEASE = 0.82
AGE_VALUE_PER_YEAR = 0.83
# A working device is always worth something. Nothing in the fitted data is old
# enough to have reached a floor, so this share of the new price is a guess; it
# takes over at about 15 years old.
AGE_VALUE_FLOOR = 0.05
# Only the release year is known, so a model is taken to have come out mid-year.
RELEASE_POINT_IN_YEAR = 0.5

# A loan is worth half of the item's value up to this threshold plus a quarter of
# any value above it, like tax brackets, so loan value never drops as value rises.
# The lower rate on the top slice reflects that expensive items are more rentable
# and less likely to be bought outright.
LOAN_THRESHOLD_USD = 50.0
LOAN_FRACTION_AT_OR_BELOW = 0.5
LOAN_FRACTION_ABOVE = 0.25


def age_in_years(release_year: int, as_of: date | None = None) -> float:
    """Years since a model released in `release_year` came out; never negative."""
    as_of = as_of or date.today()
    year_start = date(as_of.year, 1, 1)
    year_length = (date(as_of.year + 1, 1, 1) - year_start).days
    now = as_of.year + (as_of - year_start).days / year_length
    return max(now - (release_year + RELEASE_POINT_IN_YEAR), 0.0)


def age_factor(release_year: int, as_of: date | None = None) -> float:
    """What age does to a device's value, on top of its condition multiplier; at most 1."""
    curve = AGE_VALUE_AT_RELEASE * AGE_VALUE_PER_YEAR ** age_in_years(release_year, as_of)
    return min(curve / CONDITION_MULTIPLIERS[Condition.USED], 1.0)


def buy_value(
    new_price_usd: float,
    condition: Condition,
    resale_demand: ResaleDemand = ResaleDemand.TYPICAL,
    release_year: int | None = None,
    as_of: date | None = None,
) -> float:
    """What the item would cost to buy in its current condition.

    With a `release_year` the item is a device priced by age: its value is the
    condition multiplier times the age factor on `as_of` (default today), never
    less than the floor, and resale demand plays no part.
    """
    if release_year is not None:
        multiplier = max(
            CONDITION_MULTIPLIERS[condition] * age_factor(release_year, as_of), AGE_VALUE_FLOOR
        )
        return round(new_price_usd * multiplier, 2)
    multipliers = (
        WEAK_RESALE_MULTIPLIERS if resale_demand == ResaleDemand.WEAK else CONDITION_MULTIPLIERS
    )
    return round(new_price_usd * multipliers[condition], 2)


def loan_value(buy_value_usd: float) -> float:
    """What borrowing the item once is worth to the borrower."""
    below = min(buy_value_usd, LOAN_THRESHOLD_USD)
    above = max(buy_value_usd - LOAN_THRESHOLD_USD, 0)
    return round(below * LOAN_FRACTION_AT_OR_BELOW + above * LOAN_FRACTION_ABOVE, 2)


def appraisal_buy_value(appraisal: Appraisal, as_of: date | None = None) -> float:
    return buy_value(
        appraisal.new_price_usd,
        appraisal.condition,
        appraisal.resale_demand,
        appraisal.release_year,
        as_of,
    )


def appraisal_loan_value(appraisal: Appraisal, as_of: date | None = None) -> float:
    return loan_value(appraisal_buy_value(appraisal, as_of))
