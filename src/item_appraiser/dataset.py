"""Load a hand-valued test set (default `data/items_sample.csv`).

The CSV needs `name` and `new_price_usd` columns; `description`, `image_urls`
(space-separated), `item_id`, `category`, `quantity`, `condition`,
`resale_demand`, `confidence`, `assumption` (or `assumptions`) and
`model_version` are read when present. Rows with no `new_price_usd` are skipped as not yet valued.

Two more columns are for items whose used value was looked up rather than
derived: `used_value_usd` is what the item would sell for as listed, and stands
in for the value policy when scoring; `release_year` is the year the model came out.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from item_appraiser import policy
from item_appraiser.models import (
    Appraisal,
    Condition,
    Confidence,
    Listing,
    ResaleDemand,
)

DEFAULT_PATH = Path("data/items_sample.csv")


@dataclass(frozen=True)
class LabeledItem:
    listing: Listing
    label: Appraisal
    category: str = ""  # used only by the category-median baseline
    # What the item would sell for as listed, looked up by hand; None to derive
    # the hand value from the label with the value policy.
    used_value_usd: float | None = None
    # The year the model came out, by hand. Kept off the label so the policy never
    # applies the age curve to a hand value: it's for checking the appraiser's year.
    release_year: int | None = None

    @property
    def buy_value_usd(self) -> float:
        """The hand buy value: the looked-up used value, or the policy's from the label."""
        if self.used_value_usd is not None:
            return self.used_value_usd
        return policy.appraisal_buy_value(self.label)

    @property
    def loan_value_usd(self) -> float:
        return policy.loan_value(self.buy_value_usd)


def _split(text: str, sep: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(sep) if part.strip())


def parse_listing(row: dict[str, str]) -> Listing:
    return Listing(
        item_id=row.get("item_id") or None,
        name=row["name"],
        description=row.get("description") or "",
        image_urls=_split(row.get("image_urls") or "", " "),
    )


def parse_row(row: dict[str, str]) -> LabeledItem | None:
    """Turn one CSV row into a labeled item, or None if it has no hand estimate yet."""
    new_price = (row.get("new_price_usd") or "").strip()
    if not new_price:
        return None
    listing = parse_listing(row)
    quantity = (row.get("quantity") or "").strip()
    label = Appraisal(
        new_price_usd=float(new_price),
        quantity=int(float(quantity)) if quantity else None,
        condition=Condition.parse(row.get("condition")),
        resale_demand=ResaleDemand.parse(row.get("resale_demand")),
        confidence=Confidence.parse(row.get("confidence")),
        assumption=row.get("assumption") or row.get("assumptions") or "",
        model_version=row.get("model_version") or "hand",
    )
    used_value = (row.get("used_value_usd") or "").strip()
    release_year = (row.get("release_year") or "").strip()
    return LabeledItem(
        listing,
        label,
        category=(row.get("category") or "").strip(),
        used_value_usd=float(used_value) if used_value else None,
        release_year=int(float(release_year)) if release_year else None,
    )


def load(path: Path = DEFAULT_PATH) -> list[LabeledItem]:
    """Read the labeled rows of a hand-valued CSV, skipping rows not yet estimated."""
    with open(path, newline="", encoding="utf-8") as f:
        items = [parse_row(row) for row in csv.DictReader(f)]
    return [item for item in items if item is not None]


def load_listings(path: Path = DEFAULT_PATH) -> list[Listing]:
    """Read every row as a listing, valued or not, e.g. for a climate coverage check."""
    with open(path, newline="", encoding="utf-8") as f:
        return [parse_listing(row) for row in csv.DictReader(f)]
