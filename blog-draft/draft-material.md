# Blog draft material: item-appraiser and Meutch's impact

Raw material to rewrite in your own voice. Everything here comes from the repo:
the README, earlier README versions and commit messages. Where the repo doesn't
have something, I've said so under **Gaps** at the end.

---

## 1. How it works, in one paragraph

The appraiser shows an LLM a listing's name, description and photos, and asks
it for just three judgments: **what it would cost new today**, **what condition
it's in** (new / like new / used), and **whether that kind of thing resells
well** (typical / weak). The model also says how many units the listing offers,
how confident it is, and gives a one-sentence assumption a person can check
("Priced as an iPhone 11 64 GB..."). Everything else is ordinary code with
fixed, documented rules:

- **Giveaway value** (what the recipient would have paid secondhand) = new price
  × 0.6 for used, 0.8 for like new, 1.0 for new. For things with weak resale
  markets (big furniture, china, cheap everyday goods) the multipliers drop to
  0.25 / 0.4 / 1.0.
- **Loan value** (what one borrow is worth) = half of the first $50 of giveaway
  value plus a quarter of anything above that, tax-bracket style.
- **Climate**: the model also picks one of 44 item categories. New-item
  footprint = new price × a per-dollar emission factor from the EPA-derived
  USEEIO dataset, except phones, computers, tablets, monitors and TVs, which get
  a fixed per-device footprint (dollar-based factors badly understate imported
  electronics). A giveaway avoids half the new footprint (roughly the share of
  secondhand purchases that replace a new purchase), scaled by remaining life.
  A loan avoids a quarter.

**Why split it this way:** the model only guesses things a person could check,
and the rules are decided by people and can change without re-running the
model. If I decide a loan is worth 30% instead of 25%, I recompute; I don't
re-appraise.

*Possible framing line:* "The LLM is the appraiser. It isn't the accountant."

---

## 2. How I built and vetted it (timeline)

**Step 0: an answer key before any model (Oct 29).**
- Drew a seeded random sample of 50 real Meutch listings from a database dump
  and valued each one by hand: new price, condition, resale demand, quantity,
  and how confident I was in my own number.
- Built the scoring harness *before* writing any model code. The measures are
  on a ratio scale (being $10 off on a $20 item is worse than $10 off on a
  $500 one):
  - *typical error*: the median factor by which estimates miss;
  - *share within 25%* and *within 2x*;
  - *total bias*: sum of estimates ÷ sum of hand values. **This one matters
    most for impact reporting, because impact figures are sums.** Per-item
    misses that cancel out are fine; a systematic lean isn't.
- Set a dumb baseline to beat: guess the median price of other items in the
  same Meutch category. It was off by a typical 2.3x and its total came out at
  just 0.55x the hand total, so it underestimated badly.

**Step 1: get the rules right separately.**
- The first loan rule (half of value up to $75, a quarter above) had a cliff:
  a $75 item lent for $37.50 but a $76 item for $19. Made it tiered like tax
  brackets so a pricier item never lends for less, then lowered the threshold
  to $50.
- Dropped low/high price ranges from the output: I had no hand-labeled ranges
  to score them against, and the measured error from the harness is a better
  error bar on totals anyway.

**Step 2: the Claude appraiser and prompt (Oct 30, prompt `p3`).** Things that
went into the prompt and output design:
- *Resale demand* as its own field, after seeing that some things (furniture,
  tableware, cheap household goods) are worth far less secondhand than a flat
  condition discount implies.
- *Quantity counting*: the model gives a unit price and a count, and code
  multiplies. Explicit rules for what counts as one unit ("croquet set with six
  mallets" is one; "I have 5 of these to lend" is five).
- *Pricing rules*: mainstream retailer price, not the cheapest knock-off or a
  boutique; the specific model if identifiable, or its closest successor;
  closest new equivalent for vintage/out-of-print; price the amount offered for
  partial packages; don't discount for wear (condition handles that).
- *The model states its assumption first*: output fields are ordered so the
  model commits to *what* it's pricing before it writes the number.
- *Listing text is data*: the prompt tells the model the listing was written by
  a member and to never treat it as instructions.
- Photos on, quantity counting on, low-effort thinking, Claude Sonnet 5.5.
- Every response cached on disk, so re-scoring is free and repeatable.

**Step 3: tune on 50, freeze, test on 50 fresh items (Nov 4).**
- All tuning happened on the first 50 items. Then I froze the settings and drew
  a *second*, non-overlapping 50 with a new random seed, valued those by hand,
  and scored once. That held-out set is the honest number; scores on tuning data
  always flatter.

**Step 4: make it generic (prompt `p4`).**
- `p3` also sent Meutch's category, tags and listing type. Removing them made no
  difference to total bias over all 100 items (1.01x buy, 1.04x loan either way)
  and slightly *improved* typical error (1.57x → 1.50x). So the model now sees
  only name, description and photos, which means it works for anyone's
  listings, not just Meutch's.

**Step 5: climate impact (Nov 4).**
- Drew up the 44 footprint categories against *all 329* Meutch listings, not
  just the labeled ones, because Meutch's own categories are too coarse ("Home &
  Garden" spans light bulbs, saplings, mowers and furniture).
- Coverage check across all 329 cost $1.02: only 4 (1%) landed in "other".
- There are no hand labels for climate, so these figures are unscored. They
  inherit the price error and the spread within each category.

**Step 6: a second model, DeepSeek (Nov 5).** Same prompt, same scoring. Covered
in section 4.

---

## 3. How accurate it got with Claude (Sonnet 5.5, prompt `p4`)

| | First 50 (tuning) | Held-out 50 | All 100 |
|---|---|---|---|
| New price, typical error | 1.26x | 1.37x | 1.33x |
| Giveaway value, typical error | 1.47x | 1.60x | 1.50x |
| Giveaway value, within 25% | 40% | 28% | 34% |
| Giveaway value, within 2x | 80% | 64% | 72% |
| Giveaway value, total bias | 0.97x | 1.06x | 1.01x |
| Loan value, total bias | 1.00x | 1.08x | 1.04x |
| Condition accuracy | 92% | 94% | 93% |
| Quantity accuracy | 94% | 96% | 95% |

(The README calls giveaway value "buy value": what you'd pay to buy it in that
condition.)

Plain-English version:
- Over all 100 items, **summed values land within 5% of my hand totals.** For
  impact reporting, that's what counts.
- **Individual items are rough.** A typical estimate is off by about 1.5x (a
  $100 item might come out anywhere from ~$67 to ~$150), and about a quarter
  miss by more than 2x.
- **Resale demand was the weakest field.** It disagreed with my label on about
  a quarter to a third of items, mostly calling things "weak" that I'd called
  "typical".
- Cost: about $0.003 per item, or $0.14 for a 50-item run.
- With 50 items per set, differences of a few points between columns are noise.

---

## 4. How accurate it got with DeepSeek (V4.1 Flash)

DeepSeek was added after the prompt was frozen, and scored only on the held-out
50, with no tuning for it. Its API has a JSON mode but doesn't enforce a schema,
so the library spells the schema out in the prompt and checks every answer. All
50 answers were valid on the first try.

---

## 5. Head-to-head on the 50 held-out items

| Held-out 50 items | Better is | Claude Sonnet 5.5 | DeepSeek V4.1 Flash |
|---|---|---|---|
| New price, typical error | lower | 1.37x | **1.30x** |
| Giveaway value, typical error | lower | 1.60x | **1.39x** |
| Giveaway value, within 25% | higher | 28% | **40%** |
| Giveaway value, within 2x | higher | 64% | **78%** |
| Giveaway value, total bias | closer to 1.00x | 1.06x | **0.97x** |
| Loan value, total bias | closer to 1.00x | 1.08x | **0.99x** |
| Condition accuracy | higher | 94% | 94% |
| Quantity accuracy | higher | 96% | **98%** |
| Resale demand disagreements | lower | 17 | **13** |
| Cost per item | lower | $0.0026 | **$0.0003** |

Talking points:
- **DeepSeek won, at about an eighth of the cost.** Item by item, its value was
  closer to mine on 32 items, Sonnet's on 12, with 6 ties. That's notable given
  the prompt was tuned on Claude.
- **Both are good enough in aggregate**: totals within 8% of the hand values.
  The baseline was at 0.55x.
- **Neither is precise per item.**
- **DeepSeek's big misses** were mostly everyday items (a multimeter, a shovel,
  a booster seat) it called weak resale, which cuts the value by more than half.
- **Caveats on the win**: one 50-item set, one run. `deepseek-flash` is a name
  DeepSeek points at newer models over time, so the model I scored (V4.1 Flash,
  fingerprint `bc19ba97…`, November 2026) may not be the one you get. The
  library records a fingerprint per answer so a change is at least detectable.
  Claude's model ID is pinned. That's why neither is the default.

---

## 6. Caveats worth saying in the post

- These are estimates, meant for totals. Don't quote a single item's value as
  fact.
- Climate figures are *estimated avoided emissions*: reported separately, never
  subtracted from anyone's footprint (per WBCSD guidance). They're unscored
  against hand labels.
- The hand labels are my own judgment. They're one careful person's values, not
  market data.

---

## 7. Try it yourself

```sh
pip install 'item-appraiser[claude]'      # or [deepseek]
export ANTHROPIC_API_KEY=sk-ant-...       # or DEEPSEEK_API_KEY
```

The shortest version, for the post:

```python
from item_appraiser import ClaudeAppraiser, Listing

appraiser = ClaudeAppraiser(impacts=["money", "climate"])
a = appraiser.appraise(Listing(
    name="Toilet plunger",
    description="Standard flange plunger with a wooden handle. Used, but clean.",
))

print(a.assumption)
print(f"New ${a.new_price_usd:.2f} | giveaway ${a.buy_value_usd:.2f} | loan ${a.loan_value_usd:.2f}")
print(f"Avoided: {a.giveaway_kg_co2e} kg CO2e if given away, {a.loan_kg_co2e} kg per loan")
```

Swap `ClaudeAppraiser` for `DeepSeekAppraiser` to use DeepSeek. Photos are
optional: `image_urls=["https://..."]`.

For drafting, `blog-draft/appraise.py` runs the plunger, the Arrested
Development Season 3 DVDs and an old iPhone, and caches answers so reruns cost
nothing:

```sh
uv run blog-draft/appraise.py                       # the three examples
uv run blog-draft/appraise.py --provider deepseek
uv run blog-draft/appraise.py "Bundt pan" "Nordic Ware, lightly used"
```

(Without uv: `pip install 'item-appraiser[claude,deepseek]'` then
`python blog-draft/appraise.py`.)

And `blog-draft/policy_math.py` shows the math with no API key. Given a
model guess of $400 new for a used iPhone 11:

```
Giveaway value $240.00, loan value $72.50
Footprint new 79.0 kg; giveaway avoids 29.6 kg; each loan avoids 19.8 kg
```

---

## Gaps (probably on your local machine)

- **Prompt iterations before `p3`.** The Claude appraiser's first commit is
  already at `p3`, so whatever `p1` and `p2` were, and what each change bought,
  isn't in git.
- **Ablations during tuning**: Haiku vs Sonnet vs Opus, photos on vs off,
  quantity counting on vs off. The harness supports all of these
  (`--model haiku`, `--no-images`, `--no-quantity`), but no numbers were
  recorded. If `data/cache/claude/` survives locally, re-scoring those runs
  costs nothing.
- **Specific anecdotes from the tuning loop**: which items made you change the
  prompt. The `--worst 10` report output from those runs would be good
  material.
- **`p3` held-out numbers**, if you want them as a "before" (in an earlier
  README): giveaway-value typical error 1.67x, within 2x 64%, total bias 1.02x.
- **DeepSeek on the first 50**, which would show whether its lead holds.
- **Meutch-wide totals** (total value and kg CO2e across all giveaways and
  loans), which is presumably the punchline of the post and lives in the Meutch
  database.
