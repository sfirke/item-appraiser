import pytest

from item_appraiser import climate, prompt
from item_appraiser.climate import (
    FACTORS,
    GIVEAWAY_DISPLACEMENT,
    LOAN_FRACTION,
    PRICE_YEAR_ADJUSTMENT,
    giveaway_kg_co2e,
    loan_kg_co2e,
    new_item_kg_co2e,
)
from item_appraiser.models import Appraisal, Condition, FootprintCategory


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
