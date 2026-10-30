from pathlib import Path

from item_appraiser import dataset
from item_appraiser.models import Condition, Confidence, ListingType

FIXTURE = Path(__file__).parent / "fixtures" / "items.csv"


def test_load_skips_rows_without_a_hand_estimate():
    items = dataset.load(FIXTURE)
    assert [i.listing.item_id for i in items] == ["a1", "a2", "a3"]


def test_load_parses_listing_and_label():
    drill = dataset.load(FIXTURE)[0]
    assert drill.listing.tags == ("drill", "power tools")
    assert drill.listing.image_urls == ("https://example.com/a.jpg", "https://example.com/b.jpg")
    assert drill.listing.listing_type == ListingType.LOAN
    assert drill.label.new_price_usd == 150
    assert drill.label.condition == Condition.USED
    assert drill.label.confidence == Confidence.HIGH


def test_med_confidence_reads_as_medium():
    hammer = dataset.load(FIXTURE)[1]
    assert hammer.label.confidence == Confidence.MEDIUM
    assert hammer.label.condition == Condition.LIKE_NEW
