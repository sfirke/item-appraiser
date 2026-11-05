"""Data types shared by appraisers, the value policy, and the evaluation harness."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


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


class ResaleDemand(StrEnum):
    """Whether this kind of item holds its value secondhand; the value policy decides how much."""

    TYPICAL = "typical"
    WEAK = "weak"

    @classmethod
    def parse(cls, text: str | None) -> "ResaleDemand":
        """Read a hand-entered value; anything but "weak", including blank, is TYPICAL."""
        return cls.WEAK if (text or "").strip().lower() == cls.WEAK else cls.TYPICAL


@dataclass(frozen=True)
class Listing:
    """What an appraiser gets to see: an item as its owner described it.

    `item_id` is yours to round-trip; appraisers never see it.
    """

    name: str
    description: str = ""
    image_urls: tuple[str, ...] = ()
    item_id: str | None = None

    def __post_init__(self):
        # Accept any iterable of URLs, but store a tuple so the listing stays hashable.
        if isinstance(self.image_urls, str):
            raise TypeError("image_urls must be a sequence of URLs, not one string")
        object.__setattr__(self, "image_urls", tuple(self.image_urls))


@dataclass(frozen=True)
class Appraisal:
    """An appraiser's estimate for one listing.

    Appraisers estimate only the new price, condition and resale demand; buy and
    loan values are derived from these by the value policy (see
    `item_appraiser.policy`), so the policy can change without re-appraising anything.
    """

    new_price_usd: float
    condition: Condition
    resale_demand: ResaleDemand = ResaleDemand.TYPICAL
    confidence: Confidence | None = None
    assumption: str = ""  # one short sentence, e.g. "priced as a set of 4 rackets"
    # What produced the estimate, e.g. "claude-sonnet-5-5/p4+img+qty" or "hand".
    model_version: str = ""
    estimated_at: datetime | None = None
    # How the new price was reached, when the appraiser counted units.
    quantity: int | None = None
    unit_new_price_usd: float | None = None
    # Identifies the listing and settings this was estimated from; compare it with
    # the appraiser's `fingerprint(listing)` to tell whether it needs redoing.
    fingerprint: str = ""

    @property
    def buy_value_usd(self) -> float:
        """What the item would cost to buy in its current condition, under the value policy."""
        from item_appraiser import policy

        return policy.appraisal_buy_value(self)

    @property
    def loan_value_usd(self) -> float:
        """What borrowing the item once is worth, under the value policy."""
        from item_appraiser import policy

        return policy.appraisal_loan_value(self)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready dict of every field plus the derived buy and loan values."""
        result: dict[str, Any] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, StrEnum):
                value = value.value
            result[field.name] = value
        result["buy_value_usd"] = self.buy_value_usd
        result["loan_value_usd"] = self.loan_value_usd
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Appraisal":
        """Rebuild an appraisal from `to_dict()` output.

        The derived buy and loan values, and any other keys that aren't fields,
        are ignored, so values always come from the current policy.
        """
        known = {field.name for field in fields(cls)}
        values = {key: value for key, value in data.items() if key in known}
        values["condition"] = Condition(values["condition"])
        if values.get("resale_demand") is not None:
            values["resale_demand"] = ResaleDemand(values["resale_demand"])
        else:
            values.pop("resale_demand", None)
        if values.get("confidence") is not None:
            values["confidence"] = Confidence(values["confidence"])
        if isinstance(values.get("estimated_at"), str):
            values["estimated_at"] = datetime.fromisoformat(values["estimated_at"])
        return cls(**values)


class AppraisalError(Exception):
    """The appraiser gave no usable appraisal for this listing; others may still succeed."""


class Appraiser(Protocol):
    def appraise(self, listing: Listing) -> Appraisal: ...
