"""Trivial appraisers that set the floor any real appraiser has to beat."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from statistics import median

from item_appraiser.dataset import LabeledItem
from item_appraiser.models import Appraisal, Condition, Listing


class CategoryMedianAppraiser:
    """Predicts the median new price of training items in the same category.

    Categories come from the labeled data, looked up by `item_id`, since
    appraisers don't see them. Falls back to the overall median for unseen
    categories, and always guesses USED, the most common condition.
    """

    model_version = "category-median"

    def __init__(self, training: Iterable[LabeledItem], categories: Mapping[str, str]):
        by_category = defaultdict(list)
        prices = []
        for item in training:
            by_category[item.category].append(item.label.new_price_usd)
            prices.append(item.label.new_price_usd)
        if not prices:
            raise ValueError("CategoryMedianAppraiser needs at least one training item")
        self.overall = median(prices)
        self.by_category = {category: median(p) for category, p in by_category.items()}
        self.categories = categories

    def appraise(self, listing: Listing) -> Appraisal:
        category = self.categories.get(listing.item_id or "")
        return Appraisal(
            new_price_usd=self.by_category.get(category, self.overall),
            condition=Condition.USED,
            model_version=self.model_version,
        )
