"""Appraise listings with Claude.

Needs the `claude` extra (`pip install item-appraiser[claude]`) and an
`ANTHROPIC_API_KEY` in the environment, or a configured `anthropic.Anthropic`
client passed in.

Each listing is one API call: the fixed system prompt, then the photos and the
listing text, with structured JSON back. With a `cache_dir`, every usable
response is stored on disk, so appraising the same listing again costs nothing.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from os import PathLike

try:
    import anthropic
except ImportError:  # the core package works without it; only this appraiser needs it
    anthropic = None

from item_appraiser import prompt
from item_appraiser.cache import ResponseCache, digest
from item_appraiser.images import image_is_reachable
from item_appraiser.models import MONEY_ONLY, Appraisal, AppraisalError, Impact, Listing

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"

# The settings scored on the hand-valued test sets (see the README).
DEFAULT_MODEL = SONNET

EFFORT = "low"
MAX_TOKENS = 16000  # thinking counts toward this, so leave plenty of room


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    output: float
    cache_write: float
    cache_read: float


PRICES = {
    HAIKU: Price(input=0.10, output=0.50, cache_write=0.125, cache_read=0.01),
    SONNET: Price(input=2.00, output=10.00, cache_write=2.50, cache_read=0.20),
    OPUS: Price(input=4.00, output=20.00, cache_write=5.00, cache_read=0.20),
}

# Rough sizes for the pre-run estimate, on the high side so it errs toward overstating.
ESTIMATED_CHARS_PER_TOKEN = 3
ESTIMATED_TOKENS_PER_IMAGE = 650  # the largest photos in the test set come to about 640
ESTIMATED_OUTPUT_TOKENS = 400  # the JSON plus low-effort thinking


def response_text(response: dict) -> str:
    # A response can begin with thinking blocks, so find the answer by type.
    for block in response.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    raise AppraisalError(f"no text in the response (stop_reason {response.get('stop_reason')})")


def usage_cost(usage: dict, price: Price) -> float:
    tokens = (
        usage.get("input_tokens", 0) * price.input
        + usage.get("output_tokens", 0) * price.output
        + (usage.get("cache_creation_input_tokens") or 0) * price.cache_write
        + (usage.get("cache_read_input_tokens") or 0) * price.cache_read
    )
    return tokens / 1_000_000


class ClaudeAppraiser:
    """Appraise listings with one Claude call each.

    `impacts` chooses what the appraisal is for: "money" (the default, and the
    tested prompt), "climate", or both. Climate adds a footprint category to the
    same call; the new price is estimated either way, since most emission factors
    are per dollar.

    `appraise()` raises AppraisalError when the model gives no usable answer for a
    listing, or the API rejects or fails that one request; other listings may
    still succeed. Authentication and permission errors propagate unchanged.

    Any Claude model works. Costs are tracked for the models in `PRICES`; for
    another model, pass its `price` or go without cost tracking.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        use_images: bool = True,
        use_quantity: bool = True,
        cache_dir: str | PathLike | None = None,
        client: "anthropic.Anthropic | None" = None,
        image_check: Callable[[str], bool] | None = None,
        impacts: Iterable[Impact | str] = MONEY_ONLY,
        price: Price | None = None,
    ):
        if client is None and anthropic is None:
            raise ImportError(
                "ClaudeAppraiser needs the anthropic package: pip install 'item-appraiser[claude]'"
            )
        self.model = model
        self.price = price or PRICES.get(model)  # None: costs aren't tracked
        self.use_images = use_images
        self.use_quantity = use_quantity
        self.impacts = prompt.normalize_impacts(impacts)
        self.cache = ResponseCache(cache_dir) if cache_dir is not None else None
        self.model_version = (
            f"{model}/{prompt.PROMPT_VERSION}"
            f"+{'img' if use_images else 'text'}+{'qty' if use_quantity else 'total'}"
        )
        if Impact.CLIMATE in self.impacts:
            self.model_version += f"+co2-{prompt.FOOTPRINT_VERSION}"
        # What this object paid for, including unusable responses; stays 0 without a price.
        self.spent_usd = 0.0
        self._client = client
        self._image_check = image_check or image_is_reachable
        self._system = prompt.system_prompt(use_quantity, self.impacts)
        self._schema = prompt.output_schema(use_quantity, self.impacts)

    @property
    def client(self) -> "anthropic.Anthropic":
        # Built on first use, so answering from the cache needs no API key.
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _image_urls(self, listing: Listing) -> tuple[str, ...]:
        return listing.image_urls if self.use_images else ()

    def _cache_key(self, listing: Listing) -> dict:
        """Everything that shapes the request, so any change to it misses the cache."""
        urls = self._image_urls(listing)
        key = {
            "model": self.model,
            "prompt_version": prompt.PROMPT_VERSION,
            "effort": EFFORT,
            "system": self._system,
            "schema": self._schema,
            "image_urls": list(urls),
            "text": prompt.listing_text(listing, len(urls)),
        }
        # The system prompt and schema already differ by impact; this is for anyone
        # reading the key. Money-only keys stay as they were, so old responses still hit.
        if Impact.CLIMATE in self.impacts:
            key["footprint_version"] = prompt.FOOTPRINT_VERSION
        return key

    def fingerprint(self, listing: Listing) -> str:
        """Identifies everything a fresh appraisal of `listing` would depend on.

        The same value is stored on each `Appraisal`; when they differ, the listing
        (name, description, photos) or the appraiser's model or prompt has changed
        since it was estimated.
        """
        return digest(self._cache_key(listing))

    def _require_price(self) -> Price:
        if self.price is None:
            raise ValueError(f"no pricing for model {self.model}; pass price= to track costs")
        return self.price

    def uncached(self, listings: Iterable[Listing]) -> list[Listing]:
        """The listings that would need an API call (all of them, without a cache)."""
        if self.cache is None:
            return list(listings)
        return [listing for listing in listings if self._cache_key(listing) not in self.cache]

    def estimate_cost(self, listings: Iterable[Listing]) -> float:
        """Upper-end USD estimate for calling the API on `listings`, ignoring prompt caching."""
        price = self._require_price()
        prompt_chars = len(self._system) + len(json.dumps(self._schema))
        total = 0.0
        for listing in listings:
            images = len(self._image_urls(listing))
            chars = prompt_chars + len(prompt.listing_text(listing, images))
            input_tokens = chars / ESTIMATED_CHARS_PER_TOKEN + images * ESTIMATED_TOKENS_PER_IMAGE
            total += input_tokens * price.input + ESTIMATED_OUTPUT_TOKENS * price.output
        return total / 1_000_000

    def stored_cost(self, listings: Iterable[Listing]) -> float:
        """What the cached responses for `listings` cost when they were made."""
        price = self._require_price()
        if self.cache is None:
            return 0.0
        total = 0.0
        for listing in listings:
            record = self.cache.get(self._cache_key(listing))
            if record is not None:
                total += usage_cost(record["response"].get("usage", {}), price)
        return total

    def _request(self, listing: Listing, urls: tuple[str, ...]) -> dict:
        images = [{"type": "image", "source": {"type": "url", "url": url}} for url in urls]
        return {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": [
                {"type": "text", "text": self._system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        *images,
                        {"type": "text", "text": prompt.listing_text(listing, len(urls))},
                    ],
                }
            ],
            "output_config": {
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": self._schema},
            },
        }

    def _call_api(self, listing: Listing) -> dict:
        urls = self._image_urls(listing)
        reachable = tuple(url for url in urls if self._image_check(url))
        retryable = (
            (
                anthropic.BadRequestError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
                anthropic.APIConnectionError,
            )
            if anthropic is not None
            else ()
        )
        try:
            message = self.client.messages.create(**self._request(listing, reachable))
        except retryable as e:
            raise AppraisalError(f"API error: {e}") from e
        response = message.model_dump(mode="json")
        if self.price is not None:
            self.spent_usd += usage_cost(response.get("usage", {}), self.price)
        return {
            "model_version": self.model_version,
            "created_at": datetime.now(UTC).isoformat(),
            "images_sent": len(reachable),
            "images_unreachable": len(urls) - len(reachable),
            "response": response,
        }

    def _parse(self, record: dict, fingerprint: str) -> Appraisal:
        response = record["response"]
        if response.get("stop_reason") != "end_turn":
            raise AppraisalError(f"stopped early: {response.get('stop_reason')}")
        try:
            return prompt.parse_output(
                json.loads(response_text(response)),
                self.use_quantity,
                self.impacts,
                model_version=record["model_version"],
                estimated_at=datetime.fromisoformat(record["created_at"]),
                fingerprint=fingerprint,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            raise AppraisalError(f"unusable output: {e!r}") from e

    def appraise(self, listing: Listing) -> Appraisal:
        key = self._cache_key(listing)
        fingerprint = digest(key)
        if self.cache is not None and (record := self.cache.get(key)) is not None:
            return self._parse(record, fingerprint)
        record = self._call_api(listing)
        # Only usable responses are stored, so failures are retried next time.
        appraisal = self._parse(record, fingerprint)
        if self.cache is not None:
            self.cache.put(key, record)
        return appraisal
