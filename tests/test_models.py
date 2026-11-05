import json
from datetime import UTC, datetime

import pytest

import item_appraiser
from item_appraiser import (
    Appraisal,
    Condition,
    Confidence,
    FootprintCategory,
    Impact,
    Listing,
    ResaleDemand,
)


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
    assert data["model_fingerprint"] is None  # set only by providers that report one


def test_from_dict_round_trips_to_dict():
    appraisal = Appraisal(
        new_price_usd=37.5,
        condition=Condition.USED,
        resale_demand=ResaleDemand.WEAK,
        confidence=Confidence.MEDIUM,
        assumption="Priced as three resin gnomes.",
        model_version="claude-sonnet-5-5/p4+img+qty",
        estimated_at=datetime(2026, 11, 4, tzinfo=UTC),
        quantity=3,
        unit_new_price_usd=12.5,
        fingerprint="abc",
    )
    stored = json.loads(json.dumps(appraisal.to_dict()))
    assert Appraisal.from_dict(stored) == appraisal

    climate = Appraisal(
        100,
        Condition.NEW,
        footprint_category=FootprintCategory.TOYS_AND_GAMES,
        impacts=frozenset({Impact.MONEY, Impact.CLIMATE}),
    )
    stored = json.loads(json.dumps(climate.to_dict()))
    assert "giveaway_kg_co2e" in stored
    rebuilt = Appraisal.from_dict(stored)
    assert rebuilt == climate
    assert rebuilt.giveaway_kg_co2e == climate.giveaway_kg_co2e


def test_model_fingerprint_round_trips_through_storage():
    appraisal = Appraisal(10, Condition.USED, fingerprint="abc", model_fingerprint="fp_a")
    assert Appraisal.from_dict(json.loads(json.dumps(appraisal.to_dict()))) == appraisal


def test_from_dict_ignores_derived_and_unknown_keys_and_fills_defaults():
    appraisal = Appraisal.from_dict(
        {"new_price_usd": 100, "condition": "like new", "buy_value_usd": 1, "extra": "x"}
    )
    assert appraisal == Appraisal(100, Condition.LIKE_NEW)
    assert appraisal.buy_value_usd == 80
    assert Appraisal.from_dict(
        {"new_price_usd": 1, "condition": "new", "resale_demand": None, "confidence": None}
    ) == Appraisal(1, Condition.NEW)


def test_to_dict_fields_are_stable():
    assert list(Appraisal(1, Condition.NEW).to_dict()) == [
        "new_price_usd",
        "condition",
        "resale_demand",
        "confidence",
        "assumption",
        "model_version",
        "estimated_at",
        "quantity",
        "unit_new_price_usd",
        "footprint_category",
        "impacts",
        "fingerprint",
        "model_fingerprint",
        "buy_value_usd",
        "loan_value_usd",
    ]


def test_package_reports_its_version():
    assert item_appraiser.__version__ == "0.1.0"


def test_to_dict_reports_only_the_requested_impacts():
    both = Appraisal(
        100,
        Condition.NEW,
        footprint_category=FootprintCategory.TOYS_AND_GAMES,
        impacts=frozenset({Impact.MONEY, Impact.CLIMATE}),
    )
    data = json.loads(json.dumps(both.to_dict()))
    assert data["impacts"] == ["climate", "money"]
    assert data["footprint_category"] == "toys and games"
    assert data["buy_value_usd"] == 100
    assert data["new_item_kg_co2e"] == both.new_item_kg_co2e > 0
    assert data["giveaway_kg_co2e"] == both.giveaway_kg_co2e
    assert data["loan_kg_co2e"] == both.loan_kg_co2e

    money = Appraisal(100, Condition.NEW).to_dict()
    assert money["impacts"] == ["money"]
    assert "new_item_kg_co2e" not in money


def test_public_api_is_importable_from_the_package_root():
    for name in item_appraiser.__all__:
        assert hasattr(item_appraiser, name)
