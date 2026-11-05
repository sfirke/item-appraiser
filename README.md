# item-appraiser
Python library for estimating the value of household goods

Built to value items lent and given away on [Meutch](https://github.com/sfirke/meutch),
so we can roughly quantify how much members save themselves and each other, but
it works on any listing with a name, a description and optional photos.


## Install

```sh
pip install 'item-appraiser[claude]'
```

The core package (data types, value policy, prompt) has no dependencies. The
`claude` extra adds the Anthropic SDK for `ClaudeAppraiser`, the only appraiser
so far.


## Usage

```python
from item_appraiser import AppraisalError, ClaudeAppraiser, Listing

appraiser = ClaudeAppraiser()  # reads ANTHROPIC_API_KEY from the environment

listing = Listing(
    name="Cordless drill",
    description="DeWalt 20V drill, two batteries and charger, used a few times.",
    image_urls=["https://example.com/drill.jpg"],  # optional; publicly reachable URLs
    item_id="1234",  # optional, yours to round-trip; never sent to the model
)

try:
    appraisal = appraiser.appraise(listing)
except AppraisalError as e:
    ...  # no usable answer for this listing; worth retrying later

appraisal.new_price_usd   # 119.0
appraisal.buy_value_usd   # 71.4, from the value policy below
appraisal.loan_value_usd  # 30.35
appraisal.to_dict()       # every field plus the derived values, ready for JSON or a DB row
```

An `Appraisal` also carries the condition, resale demand, the model's confidence,
a one-sentence assumption a reviewer can check ("Priced as a DeWalt 20V MAX drill
kit with two batteries..."), the quantity and unit price where the model counted
units, and a `model_version` string such as `claude-sonnet-5-5/p4+img+qty` that
identifies the model, prompt version and settings.

`ClaudeAppraiser` options:

- `model`: defaults to Sonnet, the tested setting. `item_appraiser.claude.HAIKU`
  and `OPUS` are also priced.
- `cache_dir`: store every usable response on disk, so appraising the same
  listing again (same text, photos, model and prompt) costs nothing and needs no
  API key. Off by default.
- `client`: a configured `anthropic.Anthropic` client, for a different API key,
  base URL, timeout or retry policy.
- `use_images`, `use_quantity`: the tested settings are both on.

Each call costs about $0.003 with Sonnet. `appraiser.spent_usd` totals what an
appraiser has spent, and `appraiser.estimate_cost(listings)` gives an upper-end
estimate before running a batch. Photo URLs that don't load are left out of the
request rather than failing it. Authentication errors propagate as Anthropic SDK
exceptions.


## How values are derived

The appraiser estimates three things: the item's **new price**, its **condition**,
and its **resale demand**. Everything else comes from a fixed policy in
`src/item_appraiser/policy.py`:

- **Buy value** = new price × condition multiplier (new 1.0, like new 0.8,
  anything else 0.6). Kinds of item that sell for far less secondhand, such as
  large furniture and china, have weak resale demand and lower multipliers
  (new 1.0, like new 0.4, anything else 0.25).
- **Loan value** = half of the first $50 of buy value plus a quarter of
  anything above that, like tax brackets, so a pricier item never lends for
  less. The lower rate on the top slice reflects that expensive items are more
  rentable and less likely to be bought outright.

Keeping the policy out of the appraiser means it can change without
re-appraising anything: store `new_price_usd`, `condition` and `resale_demand`,
and recompute values with `item_appraiser.buy_value()` and `loan_value()`.


## Other models

Only Claude is implemented and tested, but nothing outside `claude.py` depends on
it. The prompt, the output JSON schema and the parsing of the model's answer live
in `item_appraiser.prompt`, and the on-disk response cache in
`item_appraiser.cache`. An appraiser for another model with structured output
would send `prompt.system_prompt()` as the system prompt, the photos plus
`prompt.listing_text()` as the user message, request `prompt.output_schema()`, and
pass the parsed JSON to `prompt.parse_output()`. Anything with an
`appraise(listing) -> Appraisal` method fits the `Appraiser` protocol and can be
scored with the evaluation harness below. A different model would need its own
run against the hand-valued sets before its values are trusted.


## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

To release: bump `version` in `pyproject.toml`, then
`.venv/bin/python -m build && .venv/bin/twine upload dist/*`.


## Test data

`scripts/sample_items.py` draws a seeded random sample of items from a Meutch
database dump into `data/items_sample.csv`, with blank columns for
hand-estimated values:

```sh
python3 scripts/sample_items.py            # 50 items, default seed
python3 scripts/sample_items.py --help     # --dump, --out, --seed, -n, --exclude, --force
```

To draw a held-out set for checking settings that were tuned on the first 50,
use a new seed and exclude the items already drawn:

```sh
python3 scripts/sample_items.py --seed 20261030 --exclude data/items_sample.csv --out data/items_heldout.csv
```

`data/` is git-ignored because the listings are real member content.


## Evaluation

Score an appraiser against the hand-valued items:

```sh
.venv/bin/python -m item_appraiser.evaluate                 # reads data/items_sample.csv
.venv/bin/python -m item_appraiser.evaluate --data other.csv --worst 10
```

The CSV needs `name` and `new_price_usd` columns, and reads `description`,
`image_urls` (space-separated), `item_id`, `category`, `quantity`, `condition`,
`resale_demand` and `confidence` when present.

The report gives, for new price, buy value and loan value:

- **typical error**: the median factor by which estimates miss (1.5x means
  half the estimates are within a factor of 1.5);
- the share of estimates **within 25%** and **within 2x**;
- **total bias**: the sum of estimates over the sum of hand values. This
  matters most, because impact figures are sums.

It also breaks buy-value error down by the hand estimate's confidence and the
model's own, reports condition accuracy and quantity accuracy (where the labels
have a `quantity` column), and lists the largest disagreements to review by hand,
with the model's assumption next to the hand value.

`category-median` is a baseline that guesses the median new price of other items
in the same category (scored leave-one-out). On the 50-item set its typical
buy-value error is about 2.3x, and its total buy value comes out at 0.55x the hand
total. Any real appraiser needs to beat that.

To score Claude, put `ANTHROPIC_API_KEY` in `.env`, then:

```sh
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --limit 5   # Sonnet, photos
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --model haiku
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --no-images
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --no-quantity
```

Any run that would call the API prints a cost estimate and asks first (`--yes`
skips the question). Responses are cached in `data/cache/claude/`, so re-scoring
costs nothing and needs no API key.


### Results

Settings were tuned on the first 50 hand-valued items, then frozen (Sonnet,
photos, quantity) and scored on a second, non-overlapping 50-item held-out set
(`--exclude` in the sampler). About $0.14 per 50 items.

Prompt `p4` (current) sends the model only the name, description and photos.
`p3` also sent Meutch's category, tags and listing type; dropping them made no
difference over all 100 items (total bias 1.01x buy, 1.04x loan both ways;
typical buy-value error 1.57x for p3, 1.50x for p4), so the input stays generic.

| p4 | first 50 | held-out 50 | all 100 |
|---|---|---|---|
| new price, typical error | 1.26x | 1.37x | 1.33x |
| buy value, typical error | 1.47x | 1.60x | 1.50x |
| buy value, within 25% | 40% | 28% | 34% |
| buy value, within 2x | 80% | 64% | 72% |
| buy value, total bias | 0.97x | 1.06x | 1.01x |
| loan value, total bias | 1.00x | 1.08x | 1.04x |
| condition accuracy | 92% | 94% | 93% |
| quantity accuracy | 94% | 96% | 95% |

For comparison, p3 scored total bias of 1.00x / 1.02x (buy) and 1.02x / 1.05x
(loan) on the first 50 / held-out 50.

Takeaways: summed values over all 100 items land within 5% of the hand totals,
which is what impact figures need, though either 50-item set alone can drift a
few points further (held-out loan value is 1.08x). Individual items are typically
off by about 1.5x, and only about two thirds to four fifths land within 2x, so
don't read single estimates as precise. Resale demand is the weakest field (the
model disagrees with the hand label on about a quarter of items). With 50 items
per set, differences of a few points between columns are within noise.
