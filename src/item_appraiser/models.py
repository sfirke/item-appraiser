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


class Impact(StrEnum):
    """What an appraisal is for: monetary value, climate impact, or both."""

    MONEY = "money"
    CLIMATE = "climate"


MONEY_ONLY = frozenset({Impact.MONEY})


class FootprintCategory(StrEnum):
    """The kind of item, for the climate policy's emission factors (`item_appraiser.climate`).

    Descriptions and factors for each live in `climate.FACTORS`.
    """

    POWER_TOOLS = "power tools"
    HAND_TOOLS = "hand tools"
    HARDWARE = "hardware and fasteners"
    OUTDOOR_POWER_EQUIPMENT = "outdoor power equipment"
    SPORTING_GOODS = "sporting and camping goods"
    BICYCLES = "bicycles"
    TOYS_AND_GAMES = "toys and games"
    BOOKS = "books and printed matter"
    RECORDED_MEDIA = "recorded media and video games"
    APPAREL = "apparel and accessories"
    FOOTWEAR_AND_LEATHER = "footwear and leather goods"
    JEWELRY = "jewelry"
    HOME_TEXTILES = "home textiles and bedding"
    WOOD_FURNITURE = "wood furniture"
    METAL_AND_OTHER_FURNITURE = "metal and other furniture"
    UPHOLSTERED_FURNITURE = "upholstered furniture"
    SMALL_APPLIANCES = "small appliances"
    MAJOR_APPLIANCES = "major appliances"
    HEATING_AND_COOLING = "heating and cooling"
    LIGHTING = "lighting"
    SMALL_ELECTRONICS = "small electronics and accessories"
    COOKWARE = "cookware and kitchen tools"
    CERAMICS = "ceramics"
    GLASSWARE = "glassware"
    PLASTIC_GOODS = "plastic household goods"
    WOOD_PRODUCTS = "wood products"
    MUSICAL_INSTRUMENTS = "musical instruments"
    CRAFT_AND_OFFICE_SUPPLIES = "craft and office supplies"
    PAPER_STATIONERY = "paper stationery"
    VEHICLE_PARTS = "vehicle parts and accessories"
    FOOD = "food"
    CLEANING_PRODUCTS = "cleaning products"
    LUBRICANTS = "lubricants and oils"
    MEDICINES = "medicines and supplements"
    PERSONAL_CARE = "personal care products"
    PLANTS_AND_SEEDS = "plants and seeds"
    LAPTOP = "laptop computer"
    DESKTOP_COMPUTER = "desktop computer"
    MONITOR = "computer monitor"
    TABLET = "tablet"
    SMARTPHONE = "smartphone"
    TELEVISION = "television"
    NOT_A_PRODUCT = "ticket, gift card or service"
    OTHER = "other"


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

    Appraisers estimate only the new price, condition, resale demand and (for
    climate impact) footprint category; buy and loan values come from the value
    policy (`item_appraiser.policy`) and kg CO2e from the climate policy
    (`item_appraiser.climate`), so either can change without re-appraising anything.
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
    # The kind of item, for climate impact; None when climate wasn't requested.
    footprint_category: FootprintCategory | None = None
    # What the appraisal was requested for; decides which derived values to_dict() reports.
    impacts: frozenset[Impact] = MONEY_ONLY
    # Identifies the listing and settings this was estimated from; compare it with
    # the appraiser's `fingerprint(listing)` to tell whether it needs redoing.
    fingerprint: str = ""
    # Not to be confused with `fingerprint` (our inputs): what the provider reported
    # about the backend that answered, when the model name alone doesn't pin it
    # (DeepSeek's system_fingerprint). A new value means the model or its serving
    # setup changed, so estimates may not be comparable with older ones. None when
    # the provider pins the model by name (Claude) or reported nothing.
    model_fingerprint: str | None = None

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

    @property
    def new_item_kg_co2e(self) -> float | None:
        """kg CO2e of buying the item new, under the climate policy; None without a category."""
        from item_appraiser import climate

        return climate.appraisal_new_item_kg_co2e(self)

    @property
    def giveaway_kg_co2e(self) -> float | None:
        """Estimated avoided emissions when the item is given away; None without a category."""
        from item_appraiser import climate

        return climate.appraisal_giveaway_kg_co2e(self)

    @property
    def loan_kg_co2e(self) -> float | None:
        """Estimated avoided emissions per loan of the item; None without a category."""
        from item_appraiser import climate

        return climate.appraisal_loan_kg_co2e(self)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready dict of every field plus the derived values for the requested impacts:
        buy and loan values for money, the three kg CO2e figures for climate."""
        result: dict[str, Any] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, StrEnum):
                value = value.value
            elif isinstance(value, frozenset):
                value = sorted(str(v) for v in value)
            result[field.name] = value
        if Impact.MONEY in self.impacts:
            result["buy_value_usd"] = self.buy_value_usd
            result["loan_value_usd"] = self.loan_value_usd
        if Impact.CLIMATE in self.impacts:
            result["new_item_kg_co2e"] = self.new_item_kg_co2e
            result["giveaway_kg_co2e"] = self.giveaway_kg_co2e
            result["loan_kg_co2e"] = self.loan_kg_co2e
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Appraisal":
        """Rebuild an appraisal from `to_dict()` output.

        The derived values (buy and loan, kg CO2e) and any other keys that aren't
        fields are ignored, so they always come from the current policies.
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
        if values.get("footprint_category") is not None:
            values["footprint_category"] = FootprintCategory(values["footprint_category"])
        if values.get("impacts") is not None:
            values["impacts"] = frozenset(Impact(impact) for impact in values["impacts"])
        else:
            values.pop("impacts", None)
        if isinstance(values.get("estimated_at"), str):
            values["estimated_at"] = datetime.fromisoformat(values["estimated_at"])
        return cls(**values)


class AppraisalError(Exception):
    """The appraiser gave no usable appraisal for this listing; others may still succeed."""


class Appraiser(Protocol):
    def appraise(self, listing: Listing) -> Appraisal: ...
