"""Appraise listings with DeepSeek.

Needs the `deepseek` extra (`pip install item-appraiser[deepseek]`, which adds the
OpenAI SDK, used against DeepSeek's OpenAI-compatible API) and a
`DEEPSEEK_API_KEY` in the environment, or a configured `openai.OpenAI` client
passed in.

The request matches `ClaudeAppraiser`'s: the same system prompt, then the photos
and the listing text, with low-effort thinking. DeepSeek has a JSON mode but
doesn't enforce a schema, so the schema is spelled out at the end of the system
prompt and the answer is checked against it here; anything that doesn't fit is
an AppraisalError, like any other unusable answer.
"""

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from os import PathLike

try:
    import openai
except ImportError:  # the core package works without it; only this appraiser needs it
    openai = None

from item_appraiser import prompt
from item_appraiser.cache import ResponseCache
from item_appraiser.images import image_is_reachable
from item_appraiser.models import MONEY_ONLY, Appraisal, AppraisalError, Impact, Listing

BASE_URL = "https://api.deepseek.com"
API_KEY_VARIABLE = "DEEPSEEK_API_KEY"

# DeepSeek's name for its current Flash model, the only DeepSeek model that takes
# photos. The name is an alias that DeepSeek points at newer versions over time
# (DeepSeek-V4.1-Flash-1017 as of November 2026), so results can drift without
# any change here.
FLASH = "deepseek-flash"
DEFAULT_MODEL = FLASH
# Each response's system_fingerprint becomes Appraisal.model_fingerprint, so a
# change of backend behind the alias can at least be detected.

REASONING_EFFORT = "low"  # DeepSeek's levels are low, high and max
MAX_TOKENS = 16000  # thinking counts toward this, so leave plenty of room


@dataclass(frozen=True)
class Price:
    """USD per million tokens, at DeepSeek's peak rate. Off-peak is half."""

    input: float  # a prompt cache miss
    output: float
    cache_read: float  # a prompt cache hit


PRICES = {
    FLASH: Price(input=0.30, output=1.20, cache_read=0.006),
}

# Peak hours, in UTC on weekdays; every other hour bills at half price. DeepSeek
# also bills Chinese public holidays off-peak, which this ignores, so a cost
# figure can overstate slightly but never understate.
PEAK_HOURS_UTC = frozenset({1, 2, 3, 6, 7, 8, 9})
OFF_PEAK_DISCOUNT = 0.5

# Rough sizes for the pre-run estimate, on the high side so it errs toward overstating.
ESTIMATED_CHARS_PER_TOKEN = 3
ESTIMATED_TOKENS_PER_IMAGE = 1024  # DeepSeek's documented ceiling per photo
ESTIMATED_OUTPUT_TOKENS = 600  # the JSON plus low-effort thinking


def is_peak(when: datetime) -> bool:
    when = when.astimezone(UTC)
    return when.weekday() < 5 and when.hour in PEAK_HOURS_UTC


def usage_cost(usage: dict, price: Price, when: datetime) -> float:
    hits = usage.get("prompt_cache_hit_tokens") or 0
    misses = usage.get("prompt_cache_miss_tokens")
    if misses is None:
        misses = (usage.get("prompt_tokens") or 0) - hits
    tokens = (
        misses * price.input
        + hits * price.cache_read
        + (usage.get("completion_tokens") or 0) * price.output
    )
    rate = 1.0 if is_peak(when) else OFF_PEAK_DISCOUNT
    return tokens * rate / 1_000_000


class DeepSeekAppraiser:
    """Appraise listings with one DeepSeek call each.

    Takes the same options as `ClaudeAppraiser`; see its docstring for `impacts`.

    `appraise()` raises AppraisalError when the model gives no usable answer for a
    listing, or the API rejects or fails that one request; other listings may
    still succeed. Authentication and permission errors propagate unchanged.
    """

    method = "deepseek"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        use_images: bool = True,
        use_quantity: bool = True,
        cache_dir: str | PathLike | None = None,
        client: "openai.OpenAI | None" = None,
        image_check: Callable[[str], bool] | None = None,
        impacts: Iterable[Impact | str] = MONEY_ONLY,
    ):
        if model not in PRICES:
            raise ValueError(f"no pricing for model {model}; known models: {', '.join(PRICES)}")
        if client is None and openai is None:
            raise ImportError(
                "DeepSeekAppraiser needs the openai package: pip install 'item-appraiser[deepseek]'"
            )
        self.model = model
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
        self.spent_usd = 0.0  # what this object paid for, including unusable responses
        self._client = client
        self._image_check = image_check or image_is_reachable
        self._schema = prompt.output_schema(use_quantity, self.impacts)
        self._system = prompt.system_prompt(use_quantity, self.impacts) + prompt.json_instructions(
            self._schema
        )

    @property
    def client(self) -> "openai.OpenAI":
        # Built on first use, so answering from the cache needs no API key.
        if self._client is None:
            api_key = os.environ.get(API_KEY_VARIABLE)
            if not api_key:
                # Without this the SDK would fall back to OPENAI_API_KEY and send it to DeepSeek.
                raise RuntimeError(f"set {API_KEY_VARIABLE}, or pass a configured client")
            self._client = openai.OpenAI(api_key=api_key, base_url=BASE_URL)
        return self._client

    def _image_urls(self, listing: Listing) -> tuple[str, ...]:
        return listing.image_urls if self.use_images else ()

    def _cache_key(self, listing: Listing) -> dict:
        """Everything that shapes the request, so any change to it misses the cache."""
        urls = self._image_urls(listing)
        return {
            "provider": "deepseek",
            "model": self.model,
            "prompt_version": prompt.PROMPT_VERSION,
            "footprint_version": (
                prompt.FOOTPRINT_VERSION if Impact.CLIMATE in self.impacts else None
            ),
            "reasoning_effort": REASONING_EFFORT,
            "system": self._system,
            "image_urls": list(urls),
            "text": prompt.listing_text(listing, len(urls)),
        }

    def uncached(self, listings: Iterable[Listing]) -> list[Listing]:
        """The listings that would need an API call (all of them, without a cache)."""
        if self.cache is None:
            return list(listings)
        return [listing for listing in listings if self._cache_key(listing) not in self.cache]

    def estimate_cost(self, listings: Iterable[Listing]) -> float:
        """Upper-end USD estimate for calling the API on `listings`: peak rates, no prompt caching."""
        price = PRICES[self.model]
        total = 0.0
        for listing in listings:
            images = len(self._image_urls(listing))
            chars = len(self._system) + len(prompt.listing_text(listing, images))
            input_tokens = chars / ESTIMATED_CHARS_PER_TOKEN + images * ESTIMATED_TOKENS_PER_IMAGE
            total += input_tokens * price.input + ESTIMATED_OUTPUT_TOKENS * price.output
        return total / 1_000_000

    def _record_cost(self, record: dict) -> float:
        return usage_cost(
            record["response"].get("usage") or {},
            PRICES[self.model],
            datetime.fromisoformat(record["created_at"]),
        )

    def stored_cost(self, listings: Iterable[Listing]) -> float:
        """What the cached responses for `listings` cost when they were made."""
        if self.cache is None:
            return 0.0
        total = 0.0
        for listing in listings:
            record = self.cache.get(self._cache_key(listing))
            if record is not None:
                total += self._record_cost(record)
        return total

    def _request(self, listing: Listing, urls: tuple[str, ...]) -> dict:
        images = [{"type": "image_url", "image_url": {"url": url}} for url in urls]
        return {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "reasoning_effort": REASONING_EFFORT,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self._system},
                {
                    "role": "user",
                    "content": [
                        *images,
                        {"type": "text", "text": prompt.listing_text(listing, len(urls))},
                    ],
                },
            ],
        }

    def _call_api(self, listing: Listing) -> dict:
        urls = self._image_urls(listing)
        reachable = tuple(url for url in urls if self._image_check(url))
        retryable = (
            (
                openai.BadRequestError,
                openai.UnprocessableEntityError,
                openai.RateLimitError,
                openai.InternalServerError,
                openai.APIConnectionError,  # includes timeouts
            )
            if openai is not None
            else ()
        )
        try:
            completion = self.client.chat.completions.create(**self._request(listing, reachable))
        except retryable as e:
            raise AppraisalError(f"API error: {e}") from e
        record = {
            "model_version": self.model_version,
            "created_at": datetime.now(UTC).isoformat(),
            "images_sent": len(reachable),
            "images_unreachable": len(urls) - len(reachable),
            "response": completion.model_dump(mode="json"),
        }
        self.spent_usd += self._record_cost(record)
        return record

    def _parse(self, record: dict) -> Appraisal:
        choices = record["response"].get("choices") or []
        if not choices:
            raise AppraisalError("no choices in the response")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise AppraisalError(f"stopped early: {choice.get('finish_reason')}")
        # DeepSeek's JSON mode returns blank content when the model's answer wasn't
        # valid JSON, and that fails here too.
        content = (choice.get("message") or {}).get("content") or ""
        try:
            output = json.loads(content)
            prompt.validate_output(output, self._schema)
            return prompt.parse_output(
                output,
                self.use_quantity,
                self.impacts,
                method=self.method,
                model_version=record["model_version"],
                estimated_at=datetime.fromisoformat(record["created_at"]),
                model_fingerprint=record["response"].get("system_fingerprint"),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            raise AppraisalError(f"unusable output: {e!r}") from e

    def appraise(self, listing: Listing) -> Appraisal:
        key = self._cache_key(listing)
        if self.cache is not None and (record := self.cache.get(key)) is not None:
            return self._parse(record)
        record = self._call_api(listing)
        appraisal = self._parse(record)  # only usable responses are stored; failures retry
        if self.cache is not None:
            self.cache.put(key, record)
        return appraisal
