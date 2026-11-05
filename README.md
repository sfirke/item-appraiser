# item-appraiser
Python library for estimating the value of household goods

Built to value items lent and given away on [Meutch](https://github.com/sfirke/meutch),
so we can roughly quantify how much members save themselves and each other, but
it works on any listing with a name, a description and optional photos.


## Install

Pick a model provider (see Choosing a model) and install its extra:

```sh
pip install 'item-appraiser[claude]'     # Claude, with an ANTHROPIC_API_KEY
pip install 'item-appraiser[deepseek]'   # DeepSeek, with a DEEPSEEK_API_KEY
```

The core package (data types, value policy, prompt) has no dependencies and
can't appraise anything on its own. The `claude` extra adds the Anthropic SDK for
`ClaudeAppraiser`; the `deepseek` extra adds the OpenAI SDK, which
`DeepSeekAppraiser` uses against DeepSeek's OpenAI-compatible API. Install both if
you like; they're independent.


## Choosing a model

There's no default: you pick by constructing one appraiser or the other. Both
send the same prompt and give the same `Appraisal` back, and both have been
scored against hand-valued items (see Results).

- **Claude Sonnet 5.5** (`ClaudeAppraiser`). The prompt was tuned on it, and it
  has been scored on 100 items. The model ID is pinned, so its answers don't
  change underneath you. About $0.003 per item.
- **DeepSeek V4.1 Flash** (`DeepSeekAppraiser`). It scored better than Sonnet on
  the 50 held-out items, at about an eighth of the cost ($0.0003 per item), but
  it has been scored on only those 50. `deepseek-flash` is a name DeepSeek moves
  to newer models over time, so its answers can change without notice. You can
  detect a change, though not prevent it: each appraisal's `model_fingerprint`
  records the backend that answered (see below).

Store `model_version` with each appraisal either way, plus `model_fingerprint`
for DeepSeek, so you can tell later which model produced it. If you need fixed
numbers, re-appraising old items is your call; the library won't do it for you.


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

For climate impact too, ask for it:

```python
appraiser = ClaudeAppraiser(impacts=["money", "climate"])  # or just ["climate"];
# DeepSeekAppraiser takes the same impacts
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
a one-sentence `assumption` a reviewer can check ("Priced as a DeWalt 20V MAX drill
kit with two batteries..."), the quantity and unit price where the model counted
units, a `model_version` string such as `claude-sonnet-5-5/p4+img+qty` or
`deepseek-flash/p4+img+qty` that identifies the model, prompt version and
settings, a `fingerprint`, and for DeepSeek a `model_fingerprint`.

`to_dict()` gives these keys: `new_price_usd`, `condition`, `resale_demand`,
`confidence`, `assumption`, `model_version`, `estimated_at` (ISO 8601),
`quantity`, `unit_new_price_usd`, `footprint_category` (null without climate),
`impacts` (a sorted list such as `["climate", "money"]`), `fingerprint` and
`model_fingerprint` (null for Claude), plus
the derived values for the requested impacts: `buy_value_usd` and
`loan_value_usd` for money, `new_item_kg_co2e`, `giveaway_kg_co2e` and
`loan_kg_co2e` for climate.


### Storing appraisals and keeping them current

Store `to_dict()` (as columns or a JSON column) and rebuild with
`Appraisal.from_dict()`, which ignores the stored derived values (buy and loan
values, kg CO2e) so they always come from the current policies.

The `fingerprint` identifies everything the estimate depended on: the listing's
name, description and photo URLs, and the model, prompt, impacts and settings. To find
listings that need appraising again, after an owner edits them or after an
upgrade changes the prompt, compare it with what the appraiser would use now:

```python
if stored.fingerprint != appraiser.fingerprint(listing):
    stored = appraiser.appraise(listing)
```

`fingerprint` covers what you send. For DeepSeek, whose model name doesn't pin
the model, `model_fingerprint` covers what answered: a stored value that differs
from newer appraisals' means DeepSeek changed the model or its serving setup
since. Whether to re-appraise then is your call; the appraiser can't tell before
calling the API.

Each call can take several seconds, so appraise from a background job or
scheduled command rather than inside a web request, and pass a client with a
timeout that suits it (the Anthropic SDK's default is 10 minutes):

```python
appraiser = ClaudeAppraiser(client=anthropic.Anthropic(timeout=60, max_retries=2))
appraiser = DeepSeekAppraiser(  # the OpenAI SDK's default is also 10 minutes
    client=openai.OpenAI(api_key=key, base_url=item_appraiser.deepseek.BASE_URL, timeout=60)
)
```

`ClaudeAppraiser` options:

- `model`: defaults to Sonnet, the tested setting. Any Claude model ID works;
  `item_appraiser.claude.HAIKU`, `SONNET` and `OPUS` have prices built in, so
  their costs are tracked. For another model, pass
  `price=item_appraiser.claude.Price(...)` to track costs, or go without.
- `cache_dir`: store every usable response on disk, so appraising the same
  listing again (same text, photos, model and prompt) costs nothing and needs no
  API key. Off by default.
- `client`: a configured `anthropic.Anthropic` client, for a different API key,
  base URL, timeout or retry policy.
- `use_images`, `use_quantity`: the tested settings are both on.
- `impacts`: `"money"`, `"climate"`, or both; defaults to money. With climate,
  `model_version` gains a suffix such as `+co2-f1`.

`DeepSeekAppraiser` takes the same options, except:

- `model`: defaults to `deepseek-flash` (`item_appraiser.deepseek.FLASH`), the
  tested setting and the only DeepSeek model that reads photos; its price is
  built in. Another DeepSeek model works with `price=item_appraiser.deepseek.Price(...)`
  to track costs, or without. DeepSeek points `deepseek-flash` at newer model versions
  over time, so `model_version` (`deepseek-flash/p4+img+qty`) doesn't pin the
  exact model the way a Claude model ID does. Each appraisal's
  `model_fingerprint` holds the `system_fingerprint` DeepSeek reported for that
  answer. A new value means the model or its serving setup changed, so newer
  estimates may not be comparable with older ones. DeepSeek doesn't document
  exactly what changes it, so treat it as a signal to check, not a version
  number. Claude appraisals leave it `None`, since the model ID already pins
  the model.
- `client`: a configured `openai.OpenAI` client with `base_url` set to
  `https://api.deepseek.com`. Without one, the appraiser builds its own from
  `DEEPSEEK_API_KEY`, and never falls back to `OPENAI_API_KEY`.

Each call costs about $0.003 with Sonnet and $0.0003 with DeepSeek Flash
(DeepSeek bills half price outside its peak hours, 01:00-04:00 and 06:00-10:00 UTC
on weekdays). `appraiser.spent_usd` totals what an appraiser has spent, and
`appraiser.estimate_cost(listings)` gives an upper-end estimate before running a
batch. Authentication errors propagate as the provider SDK's exceptions.

The API fetches photos from the provider's servers and fails the whole request if one
won't load, so each URL is checked first and left out of the request (rather than
failing it) unless it is http(s) on a public address and answers a HEAD request,
or a one-byte GET where HEAD is refused. So `localhost` photos from a development
server are skipped and the listing is appraised from its text. Pass
`image_check=` to replace the check, or `use_images=False` to send no photos.


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

The categories are built to cover every listing on Meutch, not just the
hand-valued ones, because Meutch's own categories are too coarse ("Home &
Garden" spans light bulbs, saplings, mowers and furniture). Over all 329
listings, the climate prompt (Sonnet, `f1`, $1.02 in all) puts 4 (1%) in
"other" (one-off specialty equipment with no common theme) and 3 tickets, gift
cards and coupons in the zero-footprint category. Six categories (computers,
monitors, tablets, TVs, upholstered furniture) have no listings so far. Together
the 329 come to about 4,200 kg CO2e new (median 5.4 kg). To
check coverage as listings grow, run the climate prompt over a CSV of all listings and
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

Claude and DeepSeek are implemented and scored (see Results). Neither depends on
the other: the prompt, the output JSON schema and the parsing of the model's
answer live in `item_appraiser.prompt`, and the on-disk response cache in
`item_appraiser.cache`. An appraiser for another model would send
`prompt.system_prompt()` as the system prompt, the photos plus
`prompt.listing_text()` as the user message, request `prompt.output_schema()`, and
pass the parsed JSON to `prompt.parse_output()`, giving each the same `impacts`
to add the footprint category. A model whose API enforces a JSON schema (Claude)
needs nothing more. One with only a JSON mode (DeepSeek) gets
`prompt.json_instructions()` appended to the system prompt and its answer checked
with `prompt.validate_output()`; `deepseek.py` is the example to copy for any
OpenAI-compatible API. Anything with an `appraise(listing) -> Appraisal` method
fits the `Appraiser` protocol and can be scored with the evaluation harness
below. A different model would need its own run against the hand-valued sets
before its values are trusted.


## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[claude,deepseek]' --group dev   # needs pip 25.1 or later
.venv/bin/pytest
```

CI runs the tests on Python 3.11 to 3.14, checks the core works without the
`claude` extra, and checks the built package.

To release: bump `version` in `pyproject.toml` and date the entry in
`CHANGELOG.md`, merge to `main`, then tag and push:

```sh
git tag v0.1.0 && git push origin v0.1.0
```

The `Publish` workflow builds the package and uploads it to PyPI with Trusted
Publishing. Before the first release, add a pending publisher on PyPI (project
`item-appraiser`, owner `sfirke`, repository `item-appraiser`, workflow
`publish.yml`, environment `pypi`) and create a `pypi` environment in the
GitHub repository settings.


## Test data

`scripts/sample_items.py` draws a seeded random sample of items from a Meutch
database dump into `data/items_sample.csv`, with blank columns for
hand-estimated values. Point it at the gzipped dump with `--dump`, or set
`ITEM_APPRAISER_DUMP` once:

```sh
export ITEM_APPRAISER_DUMP=~/path/to/db_backup.sql.gz
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

To score DeepSeek, put `DEEPSEEK_API_KEY` in `.env`; the same options apply:

```sh
.venv/bin/python -m item_appraiser.evaluate --appraiser deepseek --limit 5   # Flash, photos
.venv/bin/python -m item_appraiser.evaluate --appraiser deepseek --data data/items_heldout.csv
```

Any run that would call the API prints a cost estimate and asks first (`--yes`
skips the question). Responses are cached in `data/cache/claude/` or
`data/cache/deepseek/` (`--cache-dir` to change it), so re-scoring costs nothing
and needs no API key.

DeepSeek runs also print the model fingerprint the answers came from. Cached
answers are keyed by the name `deepseek-flash`, so after DeepSeek moves that name
to a newer model, a partly cached run would mix the two. When the scored answers
span more than one fingerprint, the report prints a warning with a count for
each; score each model with its own `--cache-dir` before comparing them.

`--impacts money,climate` adds an unscored climate summary after the report:
totals, how many items fell in each footprint category, every item in "other"
or the zero-footprint category, and the largest footprints with the model's
assumption. There are no hand labels for climate, so this is for eyeballing.

To check category coverage across every listing, not just the hand-valued ones,
draw them all (the sampler with `-n` set to the total) and run `--unlabeled`
(with either LLM appraiser),
which appraises every row and prints only the climate summary:

```sh
python3 scripts/sample_items.py -n 329 --out data/items_all.csv
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --impacts climate \
    --unlabeled --data data/items_all.csv
```


### Results

Both models were scored on the same 50 held-out items, which were never used to
tune anything, with the same prompt (`p4`) and settings (photos, quantity
counting, low-effort thinking). See the start of Evaluation for what each
measure means.

| Held-out 50 items | Better is | Claude Sonnet 5.5 | DeepSeek V4.1 Flash (1017) |
|---|---|---|---|
| New price, typical error | lower | 1.37x | **1.30x** |
| Buy value, typical error | lower | 1.60x | **1.39x** |
| Buy value, within 25% | higher | 28% | **40%** |
| Buy value, within 2x | higher | 64% | **78%** |
| Buy value, total bias | closer to 1.00x | 1.06x | **0.97x** |
| Loan value, total bias | closer to 1.00x | 1.08x | **0.99x** |
| Condition accuracy | higher | 94% | 94% |
| Quantity accuracy | higher | 96% | **98%** |
| Resale demand, items disagreeing with hand label | lower | 17 | **13** |
| Cost per item | lower | $0.0026 | **$0.0003** |
| Model ID | | `claude-sonnet-5-5` | `deepseek-flash` |
| Model fingerprint | | (pinned by ID) | `bc19ba97…` (all 50 answers) |

Takeaways:

- **DeepSeek Flash did better on this set, at about an eighth of the cost.** Item
  by item, its buy value was closer to the hand value on 32 items and Sonnet's on
  12 (6 tied). All 50 of its answers were usable on the first try.
- **Both are good enough in aggregate.** Summed buy and loan values land within
  8% of the hand totals, which is what impact figures need.
- **Neither is precise per item.** A typical estimate is off by about 1.4-1.6x,
  and a fifth (DeepSeek) to a third (Sonnet) miss by more than 2x.
- **Resale demand is the weakest field for both.** Most of DeepSeek's large
  misses are everyday items (a multimeter, a shovel, a booster seat) it called
  "weak" resale where the hand label says "typical", which cuts the buy value to
  well under half.
- **Each has a case, so neither is the default.** Sonnet is the model the
  prompt was tuned on, scored on 100 items, with a pinned model ID. DeepSeek did
  better here and costs far less, but this is one 50-item set and one run, and
  `deepseek-flash` moves to newer models over time (it served V4.1-Flash-1017,
  fingerprint `bc19ba97cbe016479903222bb1578db6`, in November 2026). Scoring
  DeepSeek on the first 50 items as well would show whether its lead holds.


#### Claude Sonnet 5.5 on both sets

The prompt and settings were tuned with Sonnet 5.5 on the first 50 hand-valued
items. The held-out 50 are a second, non-overlapping sample (`--exclude` in the
sampler) used only for scoring, so they're the fairer measure.

| Claude Sonnet 5.5, prompt `p4` | First 50 (tuning) | Held-out 50 | All 100 |
|---|---|---|---|
| New price, typical error | 1.26x | 1.37x | 1.33x |
| Buy value, typical error | 1.47x | 1.60x | 1.50x |
| Buy value, within 25% | 40% | 28% | 34% |
| Buy value, within 2x | 80% | 64% | 72% |
| Buy value, total bias | 0.97x | 1.06x | 1.01x |
| Loan value, total bias | 1.00x | 1.08x | 1.04x |
| Condition accuracy | 92% | 94% | 93% |
| Quantity accuracy | 94% | 96% | 95% |

Over all 100, summed values land within 5% of the hand totals. With 50 items
per set, differences of a few points between columns are within noise.
