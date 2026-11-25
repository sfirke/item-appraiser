from pathlib import Path

from item_appraiser import dataset
from item_appraiser.models import Condition, Confidence

FIXTURE = Path(__file__).parent / "fixtures" / "items.csv"


def test_load_skips_rows_without_a_hand_estimate():
    items = dataset.load(FIXTURE)
    assert [i.listing.item_id for i in items] == ["a1", "a2", "a3"]


def test_load_parses_listing_and_label():
    drill = dataset.load(FIXTURE)[0]
    assert drill.category == "Tools & Hardware"
    assert drill.listing.image_urls == ("https://example.com/a.jpg", "https://example.com/b.jpg")
    assert drill.label.new_price_usd == 150
    assert drill.label.condition == Condition.USED
    assert drill.label.confidence == Confidence.HIGH


def test_med_confidence_reads_as_medium():
    hammer = dataset.load(FIXTURE)[1]
    assert hammer.label.confidence == Confidence.MEDIUM
    assert hammer.label.condition == Condition.LIKE_NEW


def test_labels_read_the_assumption_and_default_to_hand():
    row = {"name": "Rake", "new_price_usd": "25", "assumptions": "Priced as a leaf rake."}
    label = dataset.parse_row(row).label
    assert label.assumption == "Priced as a leaf rake."
    assert label.model_version == "hand"
    row = {"name": "Rake", "new_price_usd": "25", "assumption": "Singular column."}
    assert dataset.parse_row(row).label.assumption == "Singular column."


def test_looked_up_used_value_stands_in_for_the_policy():
    row = {"name": "Phone", "new_price_usd": "399", "used_value_usd": "40", "release_year": "2019"}
    phone = dataset.parse_row(row)
    assert phone.used_value_usd == 40
    assert phone.release_year == 2019
    assert phone.buy_value_usd == 40
    assert phone.loan_value_usd == 20
    # The hand release year is for checking the appraiser's, never for pricing the label.
    assert phone.label.release_year is None


def test_hand_value_comes_from_the_policy_without_a_looked_up_value():
    drill = dataset.load(FIXTURE)[0]
    assert drill.used_value_usd is None
    assert drill.release_year is None
    assert drill.buy_value_usd == 90
    assert drill.loan_value_usd == 35
