# item-appraiser
Python library for estimating the value of household goods


## Test data

`scripts/sample_items.py` draws a seeded random sample of items from a Meutch
database dump into `data/items_sample.csv`, with blank columns for
hand-estimated values:

```sh
python3 scripts/sample_items.py            # 50 items, default seed
python3 scripts/sample_items.py --help     # --dump, --out, --seed, -n, --force
```

`data/` is git-ignored because the listings are real member content.
