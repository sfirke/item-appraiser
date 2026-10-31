# item-appraiser
Python library for estimating the value of household goods

Built to value items lent and given away on [Meutch](https://github.com/sfirke/meutch),
so we can roughly quantify how much members save themselves and each other.


## How values are derived

An appraiser looks at a listing (name, description, category, tags, photos)
and estimates three things: the item's **new price**, its **condition**, and its
**resale demand**. Everything else comes from a fixed policy in
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
re-appraising anything.


## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```


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


## Claude appraiser

`ClaudeAppraiser` (`src/item_appraiser/claude.py`) asks Claude for a quantity, a
unit new price, a condition, a confidence and a one-sentence assumption. Code
computes the new price as quantity × unit price.

Put `ANTHROPIC_API_KEY` in `.env`, then:

```sh
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --limit 5   # Haiku, photos
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --model sonnet
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --no-images
.venv/bin/python -m item_appraiser.evaluate --appraiser claude --no-quantity
```

Any run that would call the API prints a cost estimate and asks first (`--yes`
skips the question). Responses are cached in `data/cache/claude/`, keyed by the
listing, model, prompt version and prompt text, so re-scoring costs nothing and
needs no API key. Photo URLs that no longer load are left out of the request.
