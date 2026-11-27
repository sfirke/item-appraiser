from datetime import date

import pytest

from item_appraiser import climate, prompt
from item_appraiser.climate import (
    FACTORS,
    GIVEAWAY_DISPLACEMENT,
    LOAN_FRACTION,
    PRICE_YEAR_ADJUSTMENT,
    REMAINING_LIFE_FLOOR,
    giveaway_kg_co2e,
    loan_kg_co2e,
    new_item_kg_co2e,
    remaining_life,
)
from item_appraiser.models import Appraisal, Condition, FootprintCategory
from item_appraiser.policy import age_factor


def test_every_category_has_one_kind_of_factor_and_a_source():
    assert set(FACTORS) == set(FootprintCategory)
    for category, factor in FACTORS.items():
        assert (factor.kg_per_usd is None) != (factor.kg_per_item is None), category
        assert factor.source and factor.description, category


def test_spend_factors_are_plausible_kg_per_dollar():
    # USEEIO consumer-goods factors sit well under 1 kg CO2e per dollar.
    for category, factor in FACTORS.items():
        if factor.kg_per_usd is not None:
            assert 0.01 < factor.kg_per_usd < 1, category
            assert "NAICS" in factor.source, category


def test_a_factor_needs_exactly_one_rate():
    with pytest.raises(ValueError):
        climate.Factor("x", "y")
    with pytest.raises(ValueError):
        climate.Factor("x", "y", kg_per_usd=0.1, kg_per_item=1)


def test_spend_based_footprint_converts_price_to_the_factor_year():
    kg = new_item_kg_co2e(100, FootprintCategory.POWER_TOOLS)
    assert kg == round(100 * PRICE_YEAR_ADJUSTMENT * 0.113, 1)
    assert 9 < kg < 12  # a $100 drill; published tool-library estimates run 10-28 kg


def test_per_item_footprint_counts_units_and_ignores_price():
    assert new_item_kg_co2e(1000, FootprintCategory.LAPTOP) == 182
    assert new_item_kg_co2e(50, FootprintCategory.LAPTOP, quantity=2) == 364
    assert new_item_kg_co2e(25, FootprintCategory.NOT_A_PRODUCT) == 0


def test_giveaway_applies_displacement_and_remaining_life():
    assert giveaway_kg_co2e(100, Condition.NEW) == 100 * GIVEAWAY_DISPLACEMENT
    assert giveaway_kg_co2e(100, Condition.LIKE_NEW) == 45
    assert giveaway_kg_co2e(100, Condition.USED) == 37.5


def test_loan_is_a_fixed_fraction_regardless_of_condition():
    assert loan_kg_co2e(100) == 100 * LOAN_FRACTION


def test_appraisal_without_a_category_has_no_climate_figures():
    appraisal = Appraisal(100, Condition.USED)
    assert appraisal.new_item_kg_co2e is None
    assert appraisal.giveaway_kg_co2e is None
    assert appraisal.loan_kg_co2e is None


def test_appraisal_derives_climate_figures_from_the_policy():
    appraisal = Appraisal(
        200, Condition.USED, footprint_category=FootprintCategory.BICYCLES, quantity=1
    )
    new_kg = round(200 * PRICE_YEAR_ADJUSTMENT * 0.229, 1)
    assert appraisal.new_item_kg_co2e == new_kg
    assert appraisal.giveaway_kg_co2e == round(new_kg * 0.5 * 0.75, 1)
    assert appraisal.loan_kg_co2e == round(new_kg * 0.25, 1)


def test_footprint_prompt_lists_every_category_with_its_description():
    text = prompt.footprint_prompt()
    for category, factor in FACTORS.items():
        assert f'"{category}": {factor.description}' in text


NOV_2026 = date(2026, 11, 25)
PIXEL_3A_KG = FACTORS[FootprintCategory.SMARTPHONE].kg_per_item


def test_a_device_without_a_release_year_has_its_full_remaining_life():
    assert remaining_life(Condition.USED) == 0.75
    assert remaining_life(Condition.USED, release_year=2026, as_of=NOV_2026) == 0.75


def test_remaining_life_of_a_device_falls_with_age_like_its_value():
    life = remaining_life(Condition.USED, release_year=2019, as_of=NOV_2026)
    assert life == pytest.approx(0.75 * age_factor(2019, NOV_2026))
    assert 0.25 < life < 0.3  # a 7-year-old phone has about a year of use left
    assert remaining_life(Condition.USED, release_year=2023, as_of=NOV_2026) > life


def test_remaining_life_never_drops_below_the_floor():
    assert remaining_life(Condition.USED, release_year=1995, as_of=NOV_2026) == (
        REMAINING_LIFE_FLOOR
    )


def test_an_old_phone_avoids_far_less_when_given_away():
    current = giveaway_kg_co2e(PIXEL_3A_KG, Condition.USED)
    old = giveaway_kg_co2e(PIXEL_3A_KG, Condition.USED, release_year=2019, as_of=NOV_2026)
    assert current == 29.6
    assert old == round(PIXEL_3A_KG * 0.5 * 0.75 * age_factor(2019, NOV_2026), 1)
    assert old < current / 2


def test_a_loan_of_an_old_device_is_reduced_by_age_but_not_condition():
    old = loan_kg_co2e(PIXEL_3A_KG, release_year=2019, as_of=NOV_2026)
    assert old == round(PIXEL_3A_KG * 0.25 * age_factor(2019, NOV_2026), 1)
    assert old < giveaway_kg_co2e(PIXEL_3A_KG, Condition.USED, release_year=2019, as_of=NOV_2026)


def test_appraisal_climate_figures_use_its_release_year_and_date():
    phone = Appraisal(
        399,
        Condition.USED,
        footprint_category=FootprintCategory.SMARTPHONE,
        release_year=2019,
    )
    assert climate.appraisal_giveaway_kg_co2e(phone, NOV_2026) == giveaway_kg_co2e(
        PIXEL_3A_KG, Condition.USED, 2019, NOV_2026
    )
    assert climate.appraisal_loan_kg_co2e(phone, NOV_2026) == loan_kg_co2e(
        PIXEL_3A_KG, 2019, NOV_2026
    )
    # The new-item footprint doesn't depend on age: making a new one costs the same.
    assert phone.new_item_kg_co2e == PIXEL_3A_KG
