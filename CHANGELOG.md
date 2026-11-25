# Changelog

## 0.2.0 (unreleased)

Old phones, tablets, laptops and smartwatches are now valued by their age. They
used to get 60% of a new one's price however old they were.

- Appraisals have a `release_year`: the year the model came out for those four
  kinds of device, `None` for everything else. Prompt `p5` asks for it, and for
  the price the model cost when it came out.
- With a release year, buy value follows an age curve: a used device is worth
  about new price × 0.82 × 0.83^age from about 20 months old, and never less
  than 5% of the new price. See "How values are derived" in the README for the
  formula and the resale data it was fitted to.
- These values depend on the date. `buy_value()` takes `release_year` and
  `as_of` (default today), and `Appraisal.buy_value_usd` and `loan_value_usd`
  fall as a device ages.
- Prompt `p5` also asks for weak resale demand on electronics that newer models
  have superseded, such as an older TV, monitor, printer or sound bar.
- The evaluation reads two more optional CSV columns: `used_value_usd`, a
  looked-up resale price that replaces the policy's value as the hand buy
  value, and `release_year`. The report lists every item priced by age.

Upgrading:

- **Store `release_year`** alongside `new_price_usd`, `condition` and
  `resale_demand`, and pass it to `buy_value()` when recomputing.
  `Appraisal.from_dict()` reads stored appraisals that don't have it.
- **Re-appraise to pick it up.** The prompt changed, so every listing's
  `fingerprint` differs from its stored one. An appraisal made with `p4` has no
  release year and keeps its old value until it's redone.
- **Don't cache buy or loan values for long.** For a device with a release year
  they change over time.

## 0.1.1 (2026-11-22)

- `import item_appraiser` no longer imports the `anthropic` and `openai` SDKs.
  `ClaudeAppraiser` and `DeepSeekAppraiser` load on first use, so an app that only
  needs `Appraisal`, the value policy or the climate functions (for example, to
  compute values from stored appraisals in a web process) stays light. About 95 MB
  less memory per process with both extras installed.

## 0.1.0

First release.

- `ClaudeAppraiser` estimates an item's new price, condition and resale demand
  from its name, description and photos, with prompt `p4`.
- Buy and loan values come from a fixed value policy (`item_appraiser.policy`),
  so they can be recomputed without re-appraising.
- Optional climate impact (`impacts=["money", "climate"]`): a footprint category
  from the same call, turned into kg CO2e by `item_appraiser.climate`.
- `Appraisal.to_dict()` and `Appraisal.from_dict()` for storing appraisals, and a
  `fingerprint` on each appraisal (and `ClaudeAppraiser.fingerprint(listing)`) to
  tell when a listing needs re-appraising.
- Photo URLs that aren't public, or don't load, are left out of the request.
- Any Claude model can be used; costs are tracked for Haiku, Sonnet and Opus, or
  for any model given a `price`.
- `DeepSeekAppraiser` (the `deepseek` extra, `DEEPSEEK_API_KEY`) sends the same
  prompt to DeepSeek Flash through DeepSeek's OpenAI-compatible API, checking each
  answer against the schema since DeepSeek doesn't enforce one. Neither provider
  is the default. Its appraisals record DeepSeek's `system_fingerprint` as
  `model_fingerprint`, since the `deepseek-flash` name doesn't pin the model.
- `item-appraiser-eval` scores an appraiser against a hand-valued CSV
  (`--appraiser claude` or `deepseek`), and warns when a DeepSeek run's answers
  came from more than one model fingerprint.
