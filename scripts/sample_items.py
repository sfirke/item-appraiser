#!/usr/bin/env python3
"""Draw a seeded random sample of Meutch items into a CSV for hand valuation.

Reads the plain-SQL pg_dump directly (no database needed) and writes one row
per sampled item, with blank columns to fill in by hand.
"""

import argparse
import csv
import gzip
import random
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_DUMP = Path.home() / "git/meutch-db-backups/db_backup.sql.gz"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data/items_sample.csv"
DEFAULT_SEED = 20261012
DEFAULT_N = 50

TABLES = {"item", "category", "tag", "item_tags", "item_image"}
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}

# Left blank by this script; filled in by hand.
VALUE_COLUMNS = [
    "new_price_usd",
    "used_value_usd",
    "condition",
    "confidence",
    "notes",
]


def unescape(field):
    """Decode one field of Postgres COPY text format; \\N is NULL."""
    if field == "\\N":
        return None
    if "\\" not in field:
        return field
    out = []
    chars = iter(field)
    for ch in chars:
        if ch == "\\":
            nxt = next(chars, "")
            out.append(ESCAPES.get(nxt, nxt))
        else:
            out.append(ch)
    return "".join(out)


def read_tables(dump_path):
    """Return {table: [row dict, ...]} for the tables in TABLES."""
    tables = defaultdict(list)
    columns = None
    table = None
    with gzip.open(dump_path, "rt", encoding="utf-8", newline="\n") as f:
        for line in f:
            line = line.rstrip("\n")
            if columns is None:
                if line.startswith("COPY public."):
                    name, rest = line[len("COPY public.") :].split(" (", 1)
                    if name in TABLES:
                        table = name
                        columns = [
                            c.strip().strip('"') for c in rest.split(") FROM stdin")[0].split(",")
                        ]
            elif line == "\\.":
                columns = None
            else:
                values = [unescape(v) for v in line.split("\t")]
                tables[table].append(dict(zip(columns, values)))
    return tables


def build_rows(tables):
    categories = {c["id"]: c["name"] for c in tables["category"]}
    tag_names = {t["id"]: t["name"] for t in tables["tag"]}

    tags = defaultdict(list)
    for link in tables["item_tags"]:
        tags[link["item_id"]].append(tag_names[link["tag_id"]])

    images = defaultdict(list)
    for img in tables["item_image"]:
        images[img["item_id"]].append((int(img["position"]), img["url"]))

    rows = []
    for item in tables["item"]:
        item_id = item["id"]
        rows.append(
            {
                "item_id": item_id,
                "name": item["name"],
                "description": item["description"] or "",
                "category": categories[item["category_id"]],
                "tags": " | ".join(sorted(tags[item_id])),
                "listing_type": "giveaway" if item["is_giveaway"] == "t" else "loan",
                "listed_on": (item["created_at"] or "")[:10],
                "image_urls": " ".join(url for _, url in sorted(images[item_id])),
            }
        )
    # Sort so the sample does not depend on row order within the dump.
    rows.sort(key=lambda r: r["item_id"])
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, default=DEFAULT_DUMP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("-n", type=int, default=DEFAULT_N)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing output file (discards hand-entered values)",
    )
    args = parser.parse_args()

    if args.out.exists() and not args.force:
        sys.exit(f"{args.out} already exists; pass --force to overwrite it.")

    rows = build_rows(read_tables(args.dump))
    sample = random.Random(args.seed).sample(rows, args.n)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(sample[0]) + VALUE_COLUMNS)
        writer.writeheader()
        for row in sample:
            writer.writerow({**row, **dict.fromkeys(VALUE_COLUMNS, "")})

    print(f"Sampled {len(sample)} of {len(rows)} items (seed {args.seed}) -> {args.out}")


if __name__ == "__main__":
    main()
