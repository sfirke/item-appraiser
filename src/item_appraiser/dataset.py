"""Load the hand-valued test set (`data/items_sample.csv`)."""

import csv
from dataclasses import dataclass
from pathlib import Path

from item_appraiser.models import (
    Appraisal,
    Condition,
    Confidence,
    Listing,
    ListingType,
    ResaleDemand,
)

DEFAULT_PATH = Path("data/items_sample.csv")


@dataclass(frozen=True)
class LabeledItem:
    listing: Listing
    label: Appraisal


def _split(text: str, sep: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(sep) if part.strip())


def parse_row(row: dict[str, str]) -> LabeledItem | None:
    """Turn one CSV row into a labeled item, or None if it has no hand estimate yet."""
    new_price = (row.get("new_price_usd") or "").strip()
    if not new_price:
        return None
    listing = Listing(
        item_id=row.get("item_id") or None,
        name=row["name"],
        description=row.get("description") or "",
        category=row.get("category") or "",
        tags=_split(row.get("tags") or "", "|"),
        listing_type=ListingType(row.get("listing_type") or "loan"),
        image_urls=_split(row.get("image_urls") or "", " "),
    )
    quantity = (row.get("quantity") or "").strip()
    label = Appraisal(
        new_price_usd=float(new_price),
        quantity=int(float(quantity)) if quantity else None,
        condition=Condition.parse(row.get("condition")),
        resale_demand=ResaleDemand.parse(row.get("resale_demand")),
        confidence=Confidence.parse(row.get("confidence")),
        assumptions=row.get("assumptions") or "",
        method=row.get("method") or "hand",
        model_version=row.get("model_version") or "",
    )
    return LabeledItem(listing, label)


def load(path: Path = DEFAULT_PATH) -> list[LabeledItem]:
    """Read the labeled rows of a hand-valued CSV, skipping rows not yet estimated."""
    with open(path, newline="", encoding="utf-8") as f:
        items = [parse_row(row) for row in csv.DictReader(f)]
    return [item for item in items if item is not None]
