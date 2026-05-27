# datagrove sample fixture — books / authors / venues

## What this is

A tiny, deliberately-generic Frictionless data package bundled inside the `datagrove` wheel. Three tables (`author`, `venue`, `book`) with two foreign-key relationships and one WKT geometry column. Total footprint is about 10 KB.

Used by `datagrove`'s own doctests so the engine surface (Package / Table / view / FK validator / format adapters) can demonstrate itself without importing any domain package.

## Why it exists separate from `gmnspy.fixtures.leavenworth`

`gmnspy` ships its own canonical example fixture — the Leavenworth, WA GMNS network. That fixture is fine for gmnspy's own doctests, but it's a GMNS network: importing it from datagrove's doctests would make `datagrove` look like a GMNS tool and would create an upward dependency from the generic engine to a specific domain layer.

The repo enforces this with an import-linter contract:

```toml
[[tool.importlinter.contracts]]
name = "datagrove must not depend on gmnspy"
type = "forbidden"
source_modules = ["datagrove"]
forbidden_modules = ["gmnspy"]
```

So datagrove needs its own bundled fixture. This is it. The domain is books-and-bookstores precisely to make the composition boundary visible — a developer reading `datagrove.Package.from_source.__doc__` should immediately see that datagrove is a generic engine, not a transportation tool.

## Contents

| Table    | Rows | Notes                                                                     |
| -------- | ---- | ------------------------------------------------------------------------- |
| `author` | 5    | `id` (PK), `name`, `country`                                              |
| `venue`  | 4    | `id` (PK), `name`, `geometry` (WKT POINT in EPSG:4326)                    |
| `book`   | 10   | `id` (PK), `title`, `author_id` (FK), `published_year`, `venue_id` (FK)   |

Foreign keys:

- `book.author_id -> author.id`
- `book.venue_id -> venue.id`

The `venue.geometry` column carries WKT POINTs at real bookstores (Powell's in Portland, Strand in NYC, Shakespeare & Co. in Paris, Books Kinokuniya in Shinjuku) so the spatial-scope view helpers (`from_bbox`, `from_polygon`, `from_geometry_buffer`) have something to filter against.

## Storage variants

All variants hold the same data so format adapters can round-trip and assert equality.

- `csv/`         — one CSV per table (most readable on disk)
- `parquet/`     — one Parquet per table (smallest + fastest)
- `sample.duckdb` — single-file DuckDB database (lets the `DuckdbAdapter` doctests
  exercise `scan` / `read` against a real on-disk file)

Plus `datapackage.json` (the Frictionless manifest) at the fixture root.

## Use

```python
from datagrove.fixtures import sample
from datagrove import read

print(sample.csv_dir())           # .../csv/
print(sample.parquet_dir())       # .../parquet/
print(sample.DATAPACKAGE)         # .../datapackage.json

pkg = read(sample.csv_dir())      # returns a datagrove.Package
pkg["book"].count()               # -> 10
```

## How to regenerate

The CSVs are authored by hand (small enough to keep readable in PRs). The Parquet and DuckDB files are generated from the CSVs and the column types declared in `datapackage.json`:

```bash
# Parquet
uv run python -c "
import pandas as pd, pyarrow as pa, pyarrow.parquet as pq
from pathlib import Path
root = Path('packages/datagrove/datagrove/fixtures/sample')
schemas = {
    'author': pa.schema([('id', pa.int64()), ('name', pa.string()), ('country', pa.string())]),
    'venue':  pa.schema([('id', pa.int64()), ('name', pa.string()), ('geometry', pa.string())]),
    'book':   pa.schema([('id', pa.int64()), ('title', pa.string()), ('author_id', pa.int64()), ('published_year', pa.int64()), ('venue_id', pa.int64())]),
}
for name, schema in schemas.items():
    df = pd.read_csv(root / 'csv' / f'{name}.csv')
    pq.write_table(pa.Table.from_pandas(df, schema=schema, preserve_index=False), root / 'parquet' / f'{name}.parquet', compression='snappy')
"

# DuckDB
uv run python -c "
import duckdb
from pathlib import Path
root = Path('packages/datagrove/datagrove/fixtures/sample')
db = root / 'sample.duckdb'
db.unlink(missing_ok=True)
con = duckdb.connect(str(db))
for name in ['author', 'venue', 'book']:
    con.execute(f\"CREATE TABLE {name} AS SELECT * FROM read_csv_auto('{root / 'csv' / (name + '.csv')}')\")
con.close()
"
```

## License

The fixture data is published under CC0-1.0 (public domain). Bookstore coordinates are approximate; bookstore names are public-record landmarks.
