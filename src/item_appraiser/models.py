"""Data types shared by appraisers, the value policy, and the evaluation harness."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class Condition(StrEnum):
    """Item condition, at the granularity the value policy distinguishes."""

    NEW = "new"
    LIKE_NEW = "like new"
    USED = "used"

    @classmethod
    def parse(cls, text: str | None) -> "Condition":
        """Read a hand-entered condition; anything unrecognized, including blank, is USED."""
        normalized = (text or "").strip().lower().replace("_", " ").replace("-", " ")
        for condition in cls:
            if condition.value == normalized:
                return condition
        return cls.USED


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def parse(cls, text: str | None) -> "Confidence | None":
        normalized = (text or "").strip().lower()
        if normalized in ("med", "medium"):
            return cls.MEDIUM
        if normalized in ("low", "high"):
            return cls(normalized)
        return None


class ListingType(StrEnum):
    GIVEAWAY = "giveaway"
    LOAN = "loan"


@dataclass(frozen=True)
class Listing:
    """What an appraiser gets to see: the item as its owner posted it on Meutch."""

    name: str
    description: str = ""
    category: str = ""
    tags: tuple[str, ...] = ()
    listing_type: ListingType = ListingType.LOAN
    image_urls: tuple[str, ...] = ()
    item_id: str | None = None


@dataclass(frozen=True)
class Appraisal:
    """An appraiser's estimate for one listing.

    Appraisers estimate only the new price and condition; buy and loan values are
    derived from these by the value policy (see `item_appraiser.policy`), so the
    policy can change without re-appraising anything.
    """

    new_price_usd: float
    condition: Condition
    confidence: Confidence | None = None
    assumptions: str = ""  # one short sentence, e.g. "priced as a set of 4 rackets"
    method: str = ""
    model_version: str = ""
    estimated_at: datetime | None = None
    currency: str = "USD"


class Appraiser(Protocol):
    def appraise(self, listing: Listing) -> Appraisal: ...
