# Changelog

## 0.1.0 (unreleased)

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
- `item-appraiser-eval` scores an appraiser against a hand-valued CSV.
