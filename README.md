# item-appraiser
Python library for estimating the value of household goods

Built to value items lent and given away on [Meutch](https://github.com/sfirke/meutch),
so we can roughly quantify how much members save themselves and each other, but
it works on any listing with a name, a description and optional photos. An LLM
estimates a few facts about the item; fixed, documented policies turn those into
dollars and kg CO2e.


## Install

Pick a model provider and install its extra:

```sh
pip install 'item-appraiser[claude]'     # Claude, with an ANTHROPIC_API_KEY
pip install 'item-appraiser[deepseek]'   # DeepSeek, with a DEEPSEEK_API_KEY
```

The core package (data types, policies, prompt) has no dependencies; each extra
adds one provider's SDK.


## Choosing a model

There's no default. Both appraisers send the same prompt, return the same
`Appraisal`, and score about the same (see Results).

- **Claude Sonnet 5.5** (`ClaudeAppraiser`): scored on 100 items, and the model
  ID is pinned, so its answers don't change underneath you. About \$0.003 per item.
- **DeepSeek V4.1 Flash** (`DeepSeekAppraiser`): about a tenth of the cost
  (\$0.0003 per item, half that off-peak), scored on 50 items. DeepSeek moves the
  `deepseek-flash` name to newer models over time; each appraisal's
  `model_fingerprint` records which backend answered, so you can detect a change
  but not prevent it.


## Usage

```python
from item_appraiser import AppraisalError, ClaudeAppraiser, DeepSeekAppraiser, Listing

appraiser = ClaudeAppraiser()    # reads ANTHROPIC_API_KEY from the environment
# or
appraiser = DeepSeekAppraiser()  # reads DEEPSEEK_API_KEY from the environment

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

For climate impact too, ask for it. It rides on the same API call:

```python
appraiser = ClaudeAppraiser(impacts=["money", "climate"])  # or just ["climate"]
appraisal = appraiser.appraise(listing)

appraisal.footprint_category  # FootprintCategory.POWER_TOOLS
appraisal.new_item_kg_co2e    # 12.5, the footprint of buying it new
appraisal.giveaway_kg_co2e    # 4.7, estimated avoided emissions if given away
appraisal.loan_kg_co2e        # 3.1, estimated avoided emissions per loan
```

Besides the estimates, an `Appraisal` carries the model's confidence, a
one-sentence `assumption` a reviewer can check ("Priced as a DeWalt 20V MAX drill
kit with two batteries..."), the quantity and unit price when the model counted
units, a `model_version` such as `claude-sonnet-5-5/p5+img+qty`, a `fingerprint`
and, for DeepSeek, a `model_fingerprint`.

### Storing appraisals and keeping them current

Store `to_dict()` (as columns or a JSON column) and rebuild with
`Appraisal.from_dict()`. It ignores the stored derived values, so buy and loan
values and kg CO2e always come from the current policies.

`fingerprint` covers everything the estimate depended on: the listing's text and
photo URLs, and the model, prompt, impacts and settings. Re-appraise when it
changes, after an owner edits the listing or an upgrade changes the prompt:

```python
if stored.fingerprint != appraiser.fingerprint(listing):
    stored = appraiser.appraise(listing)
```

`model_fingerprint` covers what answered: for DeepSeek, a new value means the
model or its serving setup changed. Whether to re-appraise then is up to you.

Each call can take several seconds, so appraise from a background job rather
than inside a web request, and pass a client with a timeout that suits it (both
SDKs default to 10 minutes):

```python
appraiser = ClaudeAppraiser(client=anthropic.Anthropic(timeout=60, max_retries=2))
appraiser = DeepSeekAppraiser(
    client=openai.OpenAI(api_key=key, base_url=item_appraiser.deepseek.BASE_URL, timeout=60)
)
```

### Options

Both appraisers take:

- `model`: Sonnet (`item_appraiser.claude.SONNET`) or DeepSeek Flash
  (`item_appraiser.deepseek.FLASH`) by default, the scored settings. Other models
  work; pass `price=...Price(...)` to track the cost of one without a built-in
  price (Claude's `HAIKU`, `SONNET` and `OPUS` have them).
- `client`: a configured SDK client. DeepSeek's must have `base_url` set to
  `https://api.deepseek.com`; without one it reads `DEEPSEEK_API_KEY` and never
  `OPENAI_API_KEY`.
- `cache_dir`: keep every usable response on disk, so appraising the same
  listing again costs nothing and needs no API key. Off by default.
- `impacts`: `"money"` (default), `"climate"`, or both.
- `use_images`, `use_quantity`: both on, the scored settings.
- `image_check`: replaces the photo check. Each photo URL is sent only if it is
  public http(s) and answers, since the provider fails the whole request on a
  photo it can't load; skipped photos leave the listing appraised from its text.

`appraiser.spent_usd` totals what an appraiser has spent, and
`appraiser.estimate_cost(listings)` gives an upper-end estimate before a batch.
Authentication errors propagate as the provider SDK's exceptions.


## How values are derived

The appraiser estimates the item's **new price**, **condition** and **resale
demand**, and for phones, tablets, laptops and smartwatches the **release year**
of the model. A fixed policy in `src/item_appraiser/policy.py` does the rest:

- **Buy value** = new price × condition multiplier: new 1.0, like new 0.8,
  anything else 0.6. Items with weak resale demand, such as large furniture,
  china and superseded electronics, get 1.0, 0.4 and 0.25.
- **Devices with a release year** lose value with age instead: buy value = new
  price (at release) × condition multiplier × an age factor of 1.37 × 0.83^age,
  capped at 1, with age measured from the middle of the release year. For a used
  device that is **0.82 × 0.83^age** of the new price once it's about 20 months
  old: 47% at three years, 32% at five, 13% at ten, never below 5%.
- **Loan value** = half of the first \$50 of buy value plus a quarter of the
  rest, like tax brackets, since expensive items are more often rented than bought.

The age curve was fitted in November 2026 to secondhand prices for 55 phones,
tablets, laptops and smartwatches released from 2014 to 2025, as a share of
their launch prices; the typical model is within 1.25x of it. Its limits: it
covers only those four kinds of device; the laptop fit rests on six models, all
MacBooks or Chromebooks; the 5% floor is a guess, as nothing in the data is that
old; and it doesn't see damage. `AGE_VALUE_AT_RELEASE`, `AGE_VALUE_PER_YEAR` and
`AGE_VALUE_FLOOR` are the numbers to refit.

Because the policy is separate from the appraiser, it can change without
re-appraising anything: store `new_price_usd`, `condition`, `resale_demand` and
`release_year`, and recompute with `item_appraiser.buy_value()` and
`loan_value()`. Values of devices with a release year fall over time, so those
functions take an `as_of` date (default today).


## How climate impact is derived

The appraiser also picks one of 44 `FootprintCategory` values, and a fixed policy
in `src/item_appraiser/climate.py` does the rest:

- **New-item footprint** (kg CO2e to make and sell one, cradle to shelf; use and
  end of life are left out, since reuse avoids neither):
  - Most categories: new price × a USEEIO emission factor in kg per dollar,
    from about 0.05 (DVDs) to 0.5 (glassware). A \$100 drill comes to about 10.5 kg.
  - Computers, phones, tablets, monitors and TVs: a fixed footprint per unit
    from ADEME (laptop 182 kg, smartphone 79 kg, TV 328 kg), because per-dollar
    factors badly understate imported electronics.
  - Tickets, gift cards and services: zero.
- **Given away** = new-item footprint × 0.5 (the midpoint of published rates,
  39-65%, at which secondhand purchases replace new ones) × remaining life (new
  1.0, like new 0.9, used 0.75).
- **Per loan** = new-item footprint × 0.25, the low end of the 25-50% Library of
  Things credits per borrow, since one item may be lent many times. Capping the
  total for one item is up to the caller.
- **Devices with a release year** have less life left as they age, so both
  figures are also multiplied by the value policy's age factor, never below 5%.
  A used 2019 phone given away in late 2026 avoids about 10 kg, against 30 kg
  for a current one.

Report these as **estimated avoided emissions**, on their own, never subtracted
from anyone's footprint (WBCSD Guidance on Avoided Emissions, 2025). They're
rough: they inherit the new-price error and the spread within each category, and
there are no hand labels to check them against. To recompute, store
`footprint_category` and `quantity` as well as the value inputs, and use
`new_item_kg_co2e()`, `giveaway_kg_co2e()` and `loan_kg_co2e()`; the last two
take `release_year` and `as_of`.

The categories are meant to cover every Meutch listing. Of all 329 in November
2026, 4 landed in "other" and 3 in the zero-footprint category; together they
come to about 4,200 kg CO2e new. Bump `FOOTPRINT_VERSION` in `prompt.py` when the
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


## Results

Scored with prompt `p5`, photos and quantity counting on, against hand-valued
Meutch listings. **Typical error** is the median factor by which estimates miss;
**total bias** is the sum of estimates over the sum of hand values, which matters
most because impact figures are sums.

| Held-out 50 items | Claude Sonnet 5.5 | DeepSeek V4.1 Flash |
|---|---|---|
| New price, typical error | 1.44x | 1.33x |
| Buy value, typical error | 1.50x | 1.56x |
| Buy value, within 25% / within 2x | 28% / 68% | 34% / 76% |
| Buy value, total bias | 1.01x | 0.97x |
| Loan value, total bias | 0.99x | 0.98x |
| Condition accuracy | 94% | 90% |
| Quantity accuracy | 98% | 96% |
| Cost per item | \$0.0028 | \$0.0003 |

Sonnet on its other sets:

| Claude Sonnet 5.5 | First 50 (tuning) | All 100 | Electronics (34) |
|---|---|---|---|
| Buy value, typical error | 1.41x | 1.47x | 1.74x |
| Buy value, total bias | 0.89x | 0.95x | 1.42x |

- **Good in aggregate, not per item.** Summed values land within about 5% of the
  hand totals on the general sets, but a typical estimate is off by 1.5x and a
  quarter to a third miss by more than 2x. Repeat runs of the same prompt differ
  by up to 0.1x in typical error and 0.12x in bias, so the two models are level.
- **Electronics still come out high**, by about 1.4x in total. The electronics
  set's buy values were looked up on resale sites rather than put through the
  policy. Its three phones, all damaged, came out at \$82, \$174 and \$330
  against \$40, \$80 and \$150; the policy doesn't see damage.
- **Resale demand is the weakest field.** Most large misses are everyday items
  (a multimeter, a hot glue gun) called weak resale, which cuts their value to
  under half.
- **Release years go where they should**: on 56 made-up listings, Sonnet gave a
  year to all 16 devices and to one other item (an iPod Touch); DeepSeek got all
  56 right.

The DeepSeek run was served by V4.1-Flash-1017 (fingerprint
`bc19ba97cbe016479903222bb1578db6`) in November 2026.


## Other models

Anything with an `appraise(listing) -> Appraisal` method fits the `Appraiser`
protocol and can be scored with the evaluation harness. The prompt, output schema
and answer parsing live in `item_appraiser.prompt`, so a new provider only needs
the API call: `deepseek.py` is the example to copy for an OpenAI-compatible API.
Score a new model against the hand-valued sets before trusting its values.


## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[claude,deepseek]' --group dev   # needs pip 25.1 or later
.venv/bin/pytest
```

CI runs the tests on Python 3.11 to 3.14, checks the core works without the
extras, and checks the built package.

To release, bump `version` in `pyproject.toml`, date the entry in
`CHANGELOG.md`, merge to `main`, and push a matching tag (`git tag v1.2.3 && git
push origin v1.2.3`). The `Publish` workflow uploads it to PyPI with Trusted
Publishing.

### Test data and evaluation

`scripts/sample_items.py` draws a seeded random sample from a Meutch database
dump into a CSV with blank columns for hand values (`--help` for options;
`--exclude` draws a held-out set that skips items already drawn). `data/` is
git-ignored because the listings are real member content.

Score an appraiser against a hand-valued CSV:

```sh
.venv/bin/python -m item_appraiser.evaluate                                 # category-median baseline
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --limit 5
.venv/bin/python -m item_appraiser.evaluate --appraiser deepseek --data data/items_heldout.csv
```

The CSV needs `name` and `new_price_usd`, and reads `description`, `image_urls`
(space-separated), `item_id`, `category`, `quantity`, `condition`,
`resale_demand`, `confidence`, `release_year` and `used_value_usd` (a looked-up
resale price, used as the hand buy value) when present. The report gives typical
error, within 25% and 2x, and total bias for new price, buy and loan value, plus
condition and quantity accuracy and the largest misses next to the model's
assumption. The baseline guesses each category's median price, and any real
appraiser needs to beat it.

Runs that call the API read keys from `.env`, show a cost estimate and ask first
(`--yes` skips), and cache responses under `data/cache/`. A DeepSeek run warns
when the answers came from more than one model fingerprint. `--impacts
money,climate` adds an unscored climate summary; with climate on, `--unlabeled`
prints only that summary for a CSV without hand values, to check category coverage across
all listings.
