"""Appraise one item from the command line: its value and estimated avoided emissions.

    item-appraiser "Toilet plunger"
    item-appraiser "Cordless drill" -d "DeWalt 20V, two batteries, used a few times"
    item-appraiser "Road bike" --photo https://example.com/bike.jpg --provider deepseek
    item-appraiser "Old iPhone" -d "iPhone 11, 64 GB, scratched screen" --json

Needs ANTHROPIC_API_KEY (Claude) or DEEPSEEK_API_KEY (DeepSeek) in the environment,
or in a .env file if python-dotenv is installed. With only one key set, that
provider is used; with both, pick one with --provider.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from item_appraiser.models import Appraisal, AppraisalError, Impact, Listing

# provider: (API key variable, extra to install, appraiser class name)
PROVIDERS = {
    "claude": ("ANTHROPIC_API_KEY", "claude", "ClaudeAppraiser"),
    "deepseek": ("DEEPSEEK_API_KEY", "deepseek", "DeepSeekAppraiser"),
}


class UsageError(Exception):
    """A problem the user can fix: printed without a traceback."""


def load_dotenv() -> None:
    """Read API keys from a .env file, if python-dotenv is installed."""
    try:
        import dotenv
    except ImportError:
        return
    dotenv.load_dotenv(dotenv.find_dotenv(usecwd=True))


def choose_provider(requested: str | None, environ=os.environ) -> str:
    """The provider named by --provider, or the only one with an API key set."""
    if requested:
        variable = PROVIDERS[requested][0]
        if not environ.get(variable):
            raise UsageError(f"--provider {requested} needs {variable} set")
        return requested
    available = [name for name, (variable, _, _) in PROVIDERS.items() if environ.get(variable)]
    if len(available) == 1:
        return available[0]
    if not available:
        raise UsageError(
            "set ANTHROPIC_API_KEY (Claude) or DEEPSEEK_API_KEY (DeepSeek); "
            "see https://github.com/sfirke/item-appraiser#choosing-a-model"
        )
    raise UsageError(
        "both API keys are set; pick one with --provider claude or --provider deepseek"
    )


def build_appraiser(provider: str, impacts: Sequence[str], cache_dir: Path | None):
    _, extra, class_name = PROVIDERS[provider]
    import item_appraiser

    try:
        appraiser_class = getattr(item_appraiser, class_name)
        return appraiser_class(impacts=impacts, cache_dir=cache_dir)
    except ImportError:
        raise UsageError(
            f"the {provider} appraiser needs its extra: pip install 'item-appraiser[{extra}]'"
        ) from None


def money(value: float) -> str:
    return f"${value:,.2f}"


def format_appraisal(listing: Listing, appraisal: Appraisal) -> str:
    a = appraisal
    details = ", ".join(
        part
        for part in (
            str(a.condition),
            f"{a.resale_demand} resale demand",
            a.confidence and f"{a.confidence} confidence",
            a.quantity and a.quantity > 1 and f"{a.quantity} x {money(a.unit_new_price_usd)}",
        )
        if part
    )
    lines = [listing.name, f"  Assumption: {a.assumption}", ""]
    lines.append(f"  New price           {money(a.new_price_usd):>12}   {details}")
    if Impact.MONEY in a.impacts:
        lines.append(
            f"  Buy value           {money(a.buy_value_usd):>12}   what it's worth secondhand"
        )
        lines.append(
            f"  Loan value          {money(a.loan_value_usd):>12}   what borrowing it once is worth"
        )
    if a.footprint_category is not None:
        lines += [
            "",
            f"  Footprint new       {a.new_item_kg_co2e:>9,.1f} kg   CO2e, as {a.footprint_category}",
            f"  Giving it away      {a.giveaway_kg_co2e:>9,.1f} kg   estimated avoided CO2e",
            f"  Lending it once     {a.loan_kg_co2e:>9,.1f} kg   estimated avoided CO2e",
        ]
    lines += ["", f"  {a.model_version}"]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="item-appraiser",
        description=__doc__.splitlines()[0],
        epilog="\n".join(__doc__.splitlines()[1:]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", help='what the item is, e.g. "Toilet plunger"')
    parser.add_argument(
        "-d", "--description", default="", help="anything else: brand, model, condition, how many"
    )
    parser.add_argument(
        "--photo",
        action="append",
        default=[],
        metavar="URL",
        help="a publicly reachable photo URL; repeat for more",
    )
    parser.add_argument("--provider", choices=sorted(PROVIDERS))
    parser.add_argument(
        "--money-only",
        action="store_true",
        help="skip the climate estimate (a slightly smaller prompt)",
    )
    parser.add_argument("--json", action="store_true", help="print the appraisal as JSON")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="save answers here, so asking about the same item again is free",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    listing = Listing(name=args.name, description=args.description, image_urls=args.photo)
    impacts = ["money"] if args.money_only else ["money", "climate"]
    try:
        provider = choose_provider(args.provider)
        appraiser = build_appraiser(provider, impacts, args.cache_dir)
        appraisal = appraiser.appraise(listing)
    except UsageError as e:
        parser.exit(2, f"item-appraiser: {e}\n")
    except AppraisalError as e:
        parser.exit(1, f"item-appraiser: no usable answer for this item, try again ({e})\n")

    if args.json:
        json.dump(appraisal.to_dict(), sys.stdout, indent=2)
        print()
    else:
        print(format_appraisal(listing, appraisal))
        if appraiser.spent_usd:
            print(f"  Cost of this answer: ${appraiser.spent_usd:.4f}")


if __name__ == "__main__":
    main()
