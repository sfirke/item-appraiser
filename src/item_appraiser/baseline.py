"""Trivial appraisers that set the floor any real appraiser has to beat."""

from collections import defaultdict
from collections.abc import Iterable
from statistics import median

from item_appraiser.dataset import LabeledItem
from item_appraiser.models import Appraisal, Condition, Listing


class CategoryMedianAppraiser:
    """Predicts the median new price of training items in the same category.

    Falls back to the overall median for unseen categories, and always guesses
    USED, the most common condition.
    """

    method = "baseline"
    model_version = "category-median"

    def __init__(self, training: Iterable[LabeledItem]):
        by_category = defaultdict(list)
        prices = []
        for item in training:
            by_category[item.listing.category].append(item.label.new_price_usd)
            prices.append(item.label.new_price_usd)
        if not prices:
            raise ValueError("CategoryMedianAppraiser needs at least one training item")
        self.overall = median(prices)
        self.by_category = {category: median(p) for category, p in by_category.items()}

    def appraise(self, listing: Listing) -> Appraisal:
        return Appraisal(
            new_price_usd=self.by_category.get(listing.category, self.overall),
            condition=Condition.USED,
            method=self.method,
            model_version=self.model_version,
        )
