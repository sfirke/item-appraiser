# /// script
# requires-python = ">=3.11"
# dependencies = ["item-appraiser[claude,deepseek]>=0.1.1"]
# ///
"""Appraise a few household items: their money value and estimated avoided emissions.

    export ANTHROPIC_API_KEY=...     # or DEEPSEEK_API_KEY=... with --provider deepseek
    uv run appraise.py                                   # the three example items
    uv run appraise.py "Toilet plunger" "Basic rubber plunger, used"
    uv run appraise.py --provider deepseek

Responses are cached in ./appraisal-cache, so running it again costs nothing.
"""

import argparse

from item_appraiser import ClaudeAppraiser, DeepSeekAppraiser, Listing

EXAMPLES = [
    Listing(
        name="Toilet plunger",
        description="Standard flange plunger with a wooden handle. Used, but clean.",
    ),
    Listing(
        name="Arrested Development Season 3 DVD box set",
        description="All 13 episodes of season 3 on DVD. Discs play fine, case has some scuffs.",
    ),
    Listing(
        name="Old iPhone",
        description="iPhone 11, 64 GB, unlocked. Battery health 78%, small scratch on the screen. Includes charging cable.",
    ),
]


def show(appraiser, listing: Listing) -> None:
    a = appraiser.appraise(listing)
    print(f"\n{listing.name}")
    print(f"  Assumption:       {a.assumption}")
    print(
        f"  New price:        ${a.new_price_usd:,.2f}  ({a.condition}, {a.resale_demand} resale, {a.confidence} confidence)"
    )
    print(f"  Giveaway value:   ${a.buy_value_usd:,.2f}")
    print(f"  Loan value:       ${a.loan_value_usd:,.2f} per loan")
    print(f"  Footprint (new):  {a.new_item_kg_co2e:,.1f} kg CO2e  [{a.footprint_category}]")
    print(f"  Giveaway avoids:  {a.giveaway_kg_co2e:,.1f} kg CO2e")
    print(f"  Each loan avoids: {a.loan_kg_co2e:,.1f} kg CO2e")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("name", nargs="?", help="item name (omit to run the examples)")
    parser.add_argument("description", nargs="?", default="", help="item description")
    parser.add_argument("--provider", choices=["claude", "deepseek"], default="claude")
    args = parser.parse_args()

    Appraiser = ClaudeAppraiser if args.provider == "claude" else DeepSeekAppraiser
    appraiser = Appraiser(impacts=["money", "climate"], cache_dir="appraisal-cache")

    listings = [Listing(name=args.name, description=args.description)] if args.name else EXAMPLES
    for listing in listings:
        show(appraiser, listing)
    print(
        f"\nSpent ${appraiser.spent_usd:.4f} on API calls ({args.provider}; cached answers are free)"
    )


if __name__ == "__main__":
    main()
