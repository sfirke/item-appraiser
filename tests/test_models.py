import json
from datetime import UTC, datetime

import pytest

import item_appraiser
from item_appraiser import Appraisal, Condition, Confidence, Listing, ResaleDemand


def test_listing_accepts_a_list_of_urls_and_stays_hashable():
    listing = Listing(name="Drill", image_urls=["https://example.com/a.jpg"])
    assert listing.image_urls == ("https://example.com/a.jpg",)
    assert hash(listing) == hash(Listing(name="Drill", image_urls=("https://example.com/a.jpg",)))


def test_listing_rejects_a_single_url_string():
    with pytest.raises(TypeError):
        Listing(name="Drill", image_urls="https://example.com/a.jpg")


def test_appraisal_derives_buy_and_loan_values_from_the_policy():
    appraisal = Appraisal(200, Condition.USED)
    assert appraisal.buy_value_usd == 120
    assert appraisal.loan_value_usd == 25 + 70 * 0.25
    weak = Appraisal(200, Condition.USED, ResaleDemand.WEAK)
    assert weak.buy_value_usd == 50


def test_to_dict_is_json_ready_and_includes_derived_values():
    appraisal = Appraisal(
        new_price_usd=40,
        condition=Condition.LIKE_NEW,
        confidence=Confidence.HIGH,
        estimated_at=datetime(2026, 11, 4, tzinfo=UTC),
        quantity=2,
        unit_new_price_usd=20,
    )
    data = json.loads(json.dumps(appraisal.to_dict()))
    assert data["condition"] == "like new"
    assert data["resale_demand"] == "typical"
    assert data["confidence"] == "high"
    assert data["estimated_at"] == "2026-11-04T00:00:00+00:00"
    assert data["buy_value_usd"] == 32
    assert data["loan_value_usd"] == 16


def test_public_api_is_importable_from_the_package_root():
    for name in item_appraiser.__all__:
        assert hasattr(item_appraiser, name)
