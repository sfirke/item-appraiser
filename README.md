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

For climate impact too, ask for it:

```python
appraiser = ClaudeAppraiser(impacts=["money", "climate"])  # or just ["climate"]
appraisal = appraiser.appraise(listing)

appraisal.footprint_category  # FootprintCategory.POWER_TOOLS
appraisal.new_item_kg_co2e    # 12.5, the footprint of buying it new
appraisal.giveaway_kg_co2e    # 4.7, estimated avoided emissions if given away
appraisal.loan_kg_co2e        # 3.1, estimated avoided emissions per loan
```

Climate rides on the same API call (one extra field, about 1,400 more prompt
tokens, mostly cached). The new price is estimated either way, because most
emission factors are per dollar; `impacts` decides which derived values
`to_dict()` reports. Money only, the default, sends exactly the tested prompt.

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
- `impacts`: `"money"`, `"climate"`, or both; defaults to money. With climate,
  `model_version` gains a suffix such as `+co2-f1`.

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


## How climate impact is derived

The same split applies. The appraiser says what kind of item it is (one of 44
`FootprintCategory` values), and a fixed policy in
`src/item_appraiser/climate.py` does the rest:

- **New-item footprint** (kg CO2e of buying it new, cradle to shelf):
  - Most categories: new price × an emission factor in kg CO2e per dollar, from
    USEEIO (see Data sources), with prices converted to the factors' 2024
    dollars by CPI. Factors run from about 0.05 (DVDs) to 0.5 (glassware)
    kg per dollar; a $100 cordless drill comes to about 10.5 kg.
  - Computers, phones, tablets, monitors and TVs: a fixed footprint per unit
    (laptop 182 kg, smartphone 79 kg, TV 328 kg), because per-dollar factors
    badly understate imported electronics.
  - Tickets, gift cards and services: zero, since nothing is manufactured.
  - Use and end of life are left out: reusing an item avoids neither.
- **Given away** = new-item footprint × 0.5 (the share of secondhand purchases
  that replace buying new, the midpoint of published rates from 39% to 65%) ×
  remaining life (new 1.0, like new 0.9, used 0.75).
- **Per loan** = new-item footprint × 0.25. Library of Things credits 25-50%
  of a purchase per borrow; the lower figure leaves room for the same item
  being lent many times. Capping the total credited to one item across many
  loans is up to the caller, which sees the loan history.

Report these as **estimated avoided emissions**, separately, and never subtract
them from anyone's emissions footprint (WBCSD Guidance on Avoided Emissions,
2025). They're rough: they inherit the new-price error (typically 1.3x per item)
and the spread within each category, and they haven't been checked against hand
labels. Store `new_price_usd`, `quantity`, `condition` and `footprint_category`,
and recompute with `item_appraiser.new_item_kg_co2e()`, `giveaway_kg_co2e()` and
`loan_kg_co2e()`.

The categories were drawn up against every listing on Meutch (329 when written),
not just the hand-valued ones, because Meutch's own categories are too coarse
("Home & Garden" spans light bulbs, saplings, mowers and furniture). To check
coverage as listings grow, run the climate prompt over a CSV of all listings and
review what lands in "other" (see Evaluation). Anything recurring there is a
candidate for a new category; bump `FOOTPRINT_VERSION` in `prompt.py` when the
categories change.


### Data sources

- Spend-based factors: Ingwersen, W., & Young, B. (2025). *Supply Chain
  Greenhouse Gas Emission Factors for U.S. Commodities* (v1.4.0) [Dataset].
  Cornerstone Sustainability Data Initiative.
  https://doi.org/10.5281/zenodo.17202747. Licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). We use the "with
  margins" (purchaser price) factors for a subset of commodities, picked by
  2017 NAICS code (noted on each factor in `climate.py`), and convert appraised
  prices to 2024 dollars with the CPI-U.
- Per-unit electronics: ADEME, [Impact CO2](https://impactco2.fr/outils/numerique)
  (manufacturing plus assembly and distribution stages only).
- Displacement and loan rates: Vinted/Vaayu (2023), Schibsted/Adevinta Second
  Hand Effect (2023), eBay/Anthesis refurbished and reuse methodology (2023),
  WRAP (2025), and Library of Things' impact methodology (2024); see the comments
  in `climate.py`.


## Other models

Only Claude is implemented and tested, but nothing outside `claude.py` depends on
it. The prompt, the output JSON schema and the parsing of the model's answer live
in `item_appraiser.prompt`, and the on-disk response cache in
`item_appraiser.cache`. An appraiser for another model with structured output
would send `prompt.system_prompt()` as the system prompt, the photos plus
`prompt.listing_text()` as the user message, request `prompt.output_schema()`, and
pass the parsed JSON to `prompt.parse_output()`, giving each the same `impacts`
to add the footprint category. Anything with an
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

`--impacts money,climate` adds an unscored climate summary after the report:
totals, how many items fell in each footprint category, every item in "other"
or the zero-footprint category, and the largest footprints with the model's
assumption. There are no hand labels for climate, so this is for eyeballing.

To check category coverage across every listing, not just the hand-valued ones,
draw them all (the sampler with `-n` set to the total) and run `--unlabeled`,
which appraises every row and prints only the climate summary:

```sh
python3 scripts/sample_items.py -n 329 --out data/items_all.csv
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --impacts climate \
    --unlabeled --data data/items_all.csv
```


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
