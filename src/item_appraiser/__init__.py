"""Estimate the value and climate impact of household goods being lent and given away.

Typical use, with the `claude` extra installed and ANTHROPIC_API_KEY set::

    from item_appraiser import ClaudeAppraiser, Listing

    appraiser = ClaudeAppraiser(impacts=["money", "climate"])  # default: money only
    appraisal = appraiser.appraise(
        Listing(name="Cordless drill", description="18V, two batteries", image_urls=[url])
    )
    appraisal.new_price_usd, appraisal.buy_value_usd, appraisal.loan_value_usd
    appraisal.new_item_kg_co2e, appraisal.giveaway_kg_co2e, appraisal.loan_kg_co2e
"""

from item_appraiser._version import __version__
from item_appraiser.claude import ClaudeAppraiser
from item_appraiser.climate import giveaway_kg_co2e, loan_kg_co2e, new_item_kg_co2e
from item_appraiser.models import (
    Appraisal,
    AppraisalError,
    Appraiser,
    Condition,
    Confidence,
    FootprintCategory,
    Impact,
    Listing,
    ResaleDemand,
)
from item_appraiser.policy import buy_value, loan_value

__all__ = [
    "__version__",
    "Appraisal",
    "AppraisalError",
    "Appraiser",
    "ClaudeAppraiser",
    "Condition",
    "Confidence",
    "FootprintCategory",
    "Impact",
    "Listing",
    "ResaleDemand",
    "buy_value",
    "giveaway_kg_co2e",
    "loan_kg_co2e",
    "loan_value",
    "new_item_kg_co2e",
]
