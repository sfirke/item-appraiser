"""Climate policy: how an appraisal turns into kg CO2e.

An appraiser says what kind of item a listing offers (its `FootprintCategory`);
everything else here is a fixed policy, so it can change without re-appraising
anything, the same way `item_appraiser.policy` handles money.

Footprint of buying the item new
--------------------------------
Most categories use spend-based emission factors: kg CO2e per dollar of retail
price, multiplied by the appraised new price. They cover cradle to shelf (raw
materials, manufacturing, transport, wholesale and retail), not the use phase or
end of life, which reusing an item doesn't avoid. Factors are the "with margins"
(purchaser price) values from:

    Ingwersen, W., & Young, B. (2025). Supply Chain Greenhouse Gas Emission
    Factors for U.S. Commodities (v1.4.0) [Dataset]. Cornerstone Sustainability
    Data Initiative. https://doi.org/10.5281/zenodo.17202747
    Licensed CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).

    Changes: a subset of commodities, picked by 2017 NAICS code (noted on each
    factor); appraised prices are converted to the factors' 2024 dollars with
    PRICE_YEAR_ADJUSTMENT.

Spend-based factors badly understate electronics (they assume imports are made
with US technology), so computers, phones, tablets, monitors and TVs use a fixed
per-item footprint instead: the manufacturing plus assembly-and-distribution
stages, without use or end of life, from ADEME's Impact CO2 data
(https://impactco2.fr/outils/numerique, source data at
https://github.com/incubateur-ademe/impactco2, src/data/categories/numerique.ts).

Avoided emissions
-----------------
Not every gift or loan stands in for buying something new, so only part of the
new-item footprint counts as avoided. The figures are "estimated avoided
emissions" in the sense of the WBCSD Guidance on Avoided Emissions (v2, 2025):
report them on their own, never subtracted from anyone's emissions footprint.
"""

from dataclasses import dataclass

from item_appraiser.models import Appraisal, Condition, FootprintCategory

# Converts today's prices to the factors' 2024 dollars: CPI-U annual average for
# 2024 (313.689) over September 2026 (336.940), BLS series CUUR0000SA0 / FRED CPIAUCNS.
# Update alongside the factors.
PRICE_YEAR_ADJUSTMENT = 313.689 / 336.940

# Share of the new-item footprint a gift avoids: the midpoint of published
# secondhand replacement rates, which run from 39% (Vinted/Vaayu 2023) through
# 47-55% (Schibsted/Adevinta "Second Hand Effect" survey, 2023) and 56% (eBay /
# Anthesis reuse, 2023) to 65% (WRAP, clothing, 2025).
GIVEAWAY_DISPLACEMENT = 0.5

# A used item has less life left than a new one, so it stands in for less of a
# new purchase. eBay/Anthesis put reused lifetime at 70-90% of new.
REMAINING_LIFE = {
    Condition.NEW: 1.0,
    Condition.LIKE_NEW: 0.9,
    Condition.USED: 0.75,
}

# Share of the new-item footprint each loan avoids. Library of Things (UK)
# credited 25% of a purchase per borrow, later raised to 50% after a member
# survey; we keep the lower figure because the same item lent many times would
# otherwise add up to many avoided purchases. The condition doesn't apply: the
# purchase a loan stands in for would have been new. Capping the total credited
# to one item across many loans is left to the caller, which sees the loan history.
LOAN_FRACTION = 0.25


@dataclass(frozen=True)
class Factor:
    """How to get the new-item footprint for one category: per dollar or per item."""

    description: str  # what the appraiser is told the category covers
    source: str
    kg_per_usd: float | None = None  # kg CO2e per 2024 USD, purchaser price
    kg_per_item: float | None = None  # kg CO2e per unit, cradle to shelf

    def __post_init__(self):
        if (self.kg_per_usd is None) == (self.kg_per_item is None):
            raise ValueError("a factor needs exactly one of kg_per_usd and kg_per_item")


def _useeio(naics: str, title: str) -> str:
    return f"USEEIO v1.4.0 supply chain factor with margins, NAICS {naics} {title}"


def _ademe(slug: str, construction: float, distribution: float) -> str:
    return (
        f"ADEME Impact CO2 '{slug}': construction {construction} + "
        f"assembly and distribution {distribution} kg CO2e"
    )


C = FootprintCategory

FACTORS: dict[FootprintCategory, Factor] = {
    C.POWER_TOOLS: Factor(
        "corded and cordless power tools: drills, saws, sanders, heat guns, soldering irons",
        _useeio("333991", "Power-Driven Handtool Manufacturing"),
        kg_per_usd=0.113,
    ),
    C.HAND_TOOLS: Factor(
        "hand tools: wrenches, hammers, pliers, clamps, bike tools, shovels, rakes, ladders",
        _useeio("332216", "Saw Blade and Handtool Manufacturing"),
        kg_per_usd=0.192,
    ),
    C.HARDWARE: Factor(
        "hardware and fasteners: latches, hinges, clips, wire connectors, chain, wire fencing",
        _useeio("332510", "Hardware Manufacturing"),
        kg_per_usd=0.18,
    ),
    C.OUTDOOR_POWER_EQUIPMENT: Factor(
        "lawn and garden machines: mowers, string trimmers, leaf blowers, pressure washers, snow blowers",
        _useeio("333112", "Lawn and Garden Tractor and Home Lawn and Garden Equipment"),
        kg_per_usd=0.106,
    ),
    C.SPORTING_GOODS: Factor(
        "sporting and camping goods: skis, skates, balls, sports gear, tents, sleeping bags, fishing gear, wagons",
        _useeio("339920", "Sporting and Athletic Goods Manufacturing"),
        kg_per_usd=0.15,
    ),
    C.BICYCLES: Factor(
        "bicycles, balance bikes, bike parts",
        _useeio("336991", "Motorcycle, Bicycle, and Parts Manufacturing"),
        kg_per_usd=0.229,
    ),
    C.TOYS_AND_GAMES: Factor(
        "toys, board and card games, puzzles, dolls, building sets, strollers and baby gear",
        _useeio("339930", "Doll, Toy, and Game Manufacturing"),
        kg_per_usd=0.135,
    ),
    C.BOOKS: Factor(
        "books, magazines and other printed matter",
        _useeio("511130", "Book Publishers"),
        kg_per_usd=0.094,
    ),
    C.RECORDED_MEDIA: Factor(
        "DVDs, CDs, records and video games on disc",
        _useeio(
            "334614", "Software and Other Prerecorded Compact Disc, Tape, and Record Reproducing"
        ),
        kg_per_usd=0.054,
    ),
    C.APPAREL: Factor(
        "clothing, costumes, hats and other apparel accessories",
        _useeio("315990", "Apparel Accessories and Other Apparel Manufacturing"),
        kg_per_usd=0.104,
    ),
    C.FOOTWEAR_AND_LEATHER: Factor(
        "shoes, boots, bags, luggage and other leather goods",
        _useeio("316210", "Footwear Manufacturing"),
        kg_per_usd=0.251,
    ),
    C.JEWELRY: Factor(
        "jewelry, watches and silverware",
        _useeio("339910", "Jewelry and Silverware Manufacturing"),
        kg_per_usd=0.094,
    ),
    C.HOME_TEXTILES: Factor(
        "quilts, bedding, curtains, towels, air mattresses, tarps",
        _useeio("314120", "Curtain and Linen Mills"),
        kg_per_usd=0.254,
    ),
    C.WOOD_FURNITURE: Factor(
        "wood furniture: tables, bed frames, shelves, dressers, chairs",
        _useeio("337122", "Nonupholstered Wood Household Furniture Manufacturing"),
        kg_per_usd=0.165,
    ),
    C.METAL_AND_OTHER_FURNITURE: Factor(
        "metal, plastic or other non-wood furniture, including folding and outdoor furniture",
        _useeio("337124", "Metal Household Furniture Manufacturing"),
        kg_per_usd=0.222,
    ),
    C.UPHOLSTERED_FURNITURE: Factor(
        "sofas, armchairs and other upholstered furniture; mattresses",
        _useeio("337121", "Upholstered Household Furniture Manufacturing"),
        kg_per_usd=0.177,
    ),
    C.SMALL_APPLIANCES: Factor(
        "small household appliances: pressure cookers, blenders, dehydrators, vacuums, sewing machines, fans",
        _useeio("335210", "Small Electrical Appliance Manufacturing"),
        kg_per_usd=0.146,
    ),
    C.MAJOR_APPLIANCES: Factor(
        "major appliances: refrigerators and mini-fridges, washers, dryers, ranges, dishwashers",
        _useeio("335220", "Major Household Appliance Manufacturing"),
        kg_per_usd=0.16,
    ),
    C.HEATING_AND_COOLING: Factor(
        "air conditioners, space heaters, patio heaters, dehumidifiers",
        _useeio("333415", "Air-Conditioning and Warm Air Heating Equipment Manufacturing"),
        kg_per_usd=0.184,
    ),
    C.LIGHTING: Factor(
        "light bulbs, lamps and light fixtures",
        _useeio("335110", "Electric Lamp Bulb and Part Manufacturing"),
        kg_per_usd=0.146,
    ),
    C.SMALL_ELECTRONICS: Factor(
        "other electronics: cables, chargers, headphones, speakers, radios, routers, cameras, game consoles and controllers, meters",
        _useeio(
            "334220", "Radio and Television Broadcasting and Wireless Communications Equipment"
        ),
        kg_per_usd=0.106,
    ),
    C.COOKWARE: Factor(
        "pots, pans, bakeware, utensils, cutlery and other metal kitchen tools",
        _useeio("332215", "Metal Kitchen Cookware, Utensil, Cutlery, and Flatware"),
        kg_per_usd=0.192,
    ),
    C.CERAMICS: Factor(
        "dishes, mugs, tea sets, pottery and other ceramics",
        _useeio("327110", "Pottery, Ceramics, and Plumbing Fixture Manufacturing"),
        kg_per_usd=0.41,
    ),
    C.GLASSWARE: Factor(
        "drinking glasses, glass bowls, jars, vases, mirrors, windows",
        _useeio("327212", "Other Pressed and Blown Glass and Glassware Manufacturing"),
        kg_per_usd=0.496,
    ),
    C.PLASTIC_GOODS: Factor(
        "plastic household goods: storage bins, food containers, stools, buckets, pet ramps",
        _useeio("326199", "All Other Plastics Product Manufacturing"),
        kg_per_usd=0.332,
    ),
    C.WOOD_PRODUCTS: Factor(
        "wooden goods other than furniture: sawhorses, crates, racks, carvings, lumber",
        _useeio("321999", "All Other Miscellaneous Wood Product Manufacturing"),
        kg_per_usd=0.177,
    ),
    C.MUSICAL_INSTRUMENTS: Factor(
        "musical instruments, including electronic keyboards",
        _useeio("339992", "Musical Instrument Manufacturing"),
        kg_per_usd=0.159,
    ),
    C.CRAFT_AND_OFFICE_SUPPLIES: Factor(
        "craft, art and office supplies: yarn, thread, needles, paints, glue guns, pens, staplers",
        _useeio("339940", "Office Supplies (except Paper) Manufacturing"),
        kg_per_usd=0.237,
    ),
    C.PAPER_STATIONERY: Factor(
        "notebooks, paper, envelopes, cards and other paper stationery",
        _useeio("322230", "Stationery Product Manufacturing"),
        kg_per_usd=0.261,
    ),
    C.VEHICLE_PARTS: Factor(
        "car parts and accessories: roof carriers, wheel locks, car seats, mats",
        _useeio("336390", "Other Motor Vehicle Parts Manufacturing"),
        kg_per_usd=0.246,
    ),
    C.FOOD: Factor(
        "food, drinks, spices and baking supplies",
        _useeio("311999", "All Other Miscellaneous Food Manufacturing"),
        kg_per_usd=0.373,
    ),
    C.CLEANING_PRODUCTS: Factor(
        "soaps, detergents, disinfectants, drain cleaners and other cleaning products",
        _useeio("325611", "Soap and Other Detergent Manufacturing"),
        kg_per_usd=0.298,
    ),
    C.LUBRICANTS: Factor(
        "lubricating oils, greases and anti-seize compounds",
        _useeio("324191", "Petroleum Lubricating Oil and Grease Manufacturing"),
        kg_per_usd=0.544,
    ),
    C.MEDICINES: Factor(
        "medicines, supplements, test kits and first aid",
        _useeio("325412", "Pharmaceutical Preparation Manufacturing"),
        kg_per_usd=0.093,
    ),
    C.PERSONAL_CARE: Factor(
        "toiletries, cosmetics, hair and skin care",
        _useeio("325620", "Toilet Preparation Manufacturing"),
        kg_per_usd=0.175,
    ),
    C.PLANTS_AND_SEEDS: Factor(
        "live plants, seedlings, saplings, bulbs and seeds",
        _useeio("111421", "Nursery and Tree Production"),
        kg_per_usd=0.405,
    ),
    C.LAPTOP: Factor(
        "laptop computers, one unit each",
        _ademe("ordinateurportable", 170, 12.3),
        kg_per_item=182.0,
    ),
    C.DESKTOP_COMPUTER: Factor(
        "desktop computers without a screen, one unit each",
        _ademe("ordinateurfixeparticulier", 259, 2.94),
        kg_per_item=262.0,
    ),
    C.MONITOR: Factor(
        "computer monitors, one unit each",
        _ademe("ecran", 64.6, 1.29),
        kg_per_item=66.0,
    ),
    C.TABLET: Factor(
        "tablets and e-readers, one unit each",
        _ademe("tabletteclassique", 80.5, 3.43),
        kg_per_item=84.0,
    ),
    C.SMARTPHONE: Factor(
        "smartphones, one unit each",
        _ademe("smartphone", 77, 2.27),
        kg_per_item=79.0,
    ),
    C.TELEVISION: Factor(
        "televisions, one unit each",
        _ademe("television", 325, 3.26),
        kg_per_item=328.0,
    ),
    C.NOT_A_PRODUCT: Factor(
        "anything that isn't a manufactured object: event tickets, gift cards, coupons, services",
        "Nothing is manufactured, so a gift or loan avoids no production emissions",
        kg_per_item=0.0,
    ),
    C.OTHER: Factor(
        "anything that fits none of the categories above",
        _useeio("339999", "All Other Miscellaneous Manufacturing"),
        kg_per_usd=0.159,
    ),
}

del C


def new_item_kg_co2e(
    new_price_usd: float, category: FootprintCategory, quantity: int | None = None
) -> float:
    """kg CO2e of buying the item new, cradle to shelf.

    `new_price_usd` is the total new price at today's prices; `quantity` counts
    units for per-item categories such as laptops (None means one).
    """
    factor = FACTORS[category]
    if factor.kg_per_item is not None:
        return round((quantity or 1) * factor.kg_per_item, 1)
    return round(new_price_usd * PRICE_YEAR_ADJUSTMENT * factor.kg_per_usd, 1)


def giveaway_kg_co2e(new_item_kg: float, condition: Condition) -> float:
    """Estimated avoided emissions when the item is given away."""
    return round(new_item_kg * GIVEAWAY_DISPLACEMENT * REMAINING_LIFE[condition], 1)


def loan_kg_co2e(new_item_kg: float) -> float:
    """Estimated avoided emissions for one loan of the item."""
    return round(new_item_kg * LOAN_FRACTION, 1)


def appraisal_new_item_kg_co2e(appraisal: Appraisal) -> float | None:
    if appraisal.footprint_category is None:
        return None
    return new_item_kg_co2e(
        appraisal.new_price_usd, appraisal.footprint_category, appraisal.quantity
    )


def appraisal_giveaway_kg_co2e(appraisal: Appraisal) -> float | None:
    new_item_kg = appraisal_new_item_kg_co2e(appraisal)
    return None if new_item_kg is None else giveaway_kg_co2e(new_item_kg, appraisal.condition)


def appraisal_loan_kg_co2e(appraisal: Appraisal) -> float | None:
    new_item_kg = appraisal_new_item_kg_co2e(appraisal)
    return None if new_item_kg is None else loan_kg_co2e(new_item_kg)
