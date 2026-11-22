"""Estimate the value and climate impact of household goods being lent and given away.

Pick a model provider by constructing its appraiser; there's no default. With
the `claude` extra installed and ANTHROPIC_API_KEY set, or the `deepseek` extra
and DEEPSEEK_API_KEY::

    from item_appraiser import ClaudeAppraiser, DeepSeekAppraiser, Listing

    appraiser = ClaudeAppraiser(impacts=["money", "climate"])  # default: money only
    # or: appraiser = DeepSeekAppraiser(impacts=["money", "climate"])
    appraisal = appraiser.appraise(
        Listing(name="Cordless drill", description="18V, two batteries", image_urls=[url])
    )
    appraisal.new_price_usd, appraisal.buy_value_usd, appraisal.loan_value_usd
    appraisal.new_item_kg_co2e, appraisal.giveaway_kg_co2e, appraisal.loan_kg_co2e
"""

import importlib
from typing import TYPE_CHECKING

from item_appraiser._version import __version__
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

if TYPE_CHECKING:
    from item_appraiser.claude import ClaudeAppraiser
    from item_appraiser.deepseek import DeepSeekAppraiser

# The appraisers import their provider SDKs, which are slow to import and large in
# memory, so they load on first use. Importing the models and policies stays light.
_LAZY = {
    "ClaudeAppraiser": "item_appraiser.claude",
    "DeepSeekAppraiser": "item_appraiser.deepseek",
}


def __getattr__(name: str):
    if name in _LAZY:
        value = getattr(importlib.import_module(_LAZY[name]), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))


__all__ = [
    "__version__",
    "Appraisal",
    "AppraisalError",
    "Appraiser",
    "ClaudeAppraiser",
    "Condition",
    "Confidence",
    "DeepSeekAppraiser",
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
