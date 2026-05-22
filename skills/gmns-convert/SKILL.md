---
name: gmns-convert
description: Convert GMNS (or any datagrove) data between csv, parquet, duckdb, and zip-csv formats. Use when the user has data in one storage format and needs another — e.g. CSVs to parquet for a faster pipeline, or duckdb to CSV for sharing.
---

# gmns-convert

Use this skill when the user has GMNS (or generic Frictionless) data in one
format and wants it in another: CSV folders, Parquet files, DuckDB
databases, or zipped CSV bundles. The validation and authoring skills
should not be your first stop for this — `gmns-convert` is purely about
round-tripping a `Package` between storage backends.

All format conversion preserves the `datapackage.json` schema, so a
round-trip is lossless for typed columns. (Notable exception: WKT geometry
columns survive any format; native geo types are not normalized.)

## Workflow

1. **Confirm the source is valid first.** A bad source produces a bad
   destination. Run `datagrove info <src>` (or `gmnspy info <src>` for
   GMNS) to be sure the schema reads cleanly.
2. **Pick the destination format:**
   - **CSV folder** — human-readable, diff-friendly, slow on big tables
   - **Parquet folder** — fastest reads, typed, smaller on disk; preferred
     for pipelines
   - **DuckDB** — single-file database, great for ad-hoc SQL queries
   - **Zip CSV** — single-file portable bundle; nice for email/uploads
3. **Run the convert command.** Once PR #84 lands, the canonical command
   is:
   ```bash
   datagrove convert <src> <dest> --format=parquet
   ```
   Until then, do it programmatically with the Package API (see example).
4. **Validate the destination.** `datagrove validate <dest>` after every
   conversion. A schema-preserving round-trip should produce 0 new issues.

## Format choice cheat-sheet

| Use case                              | Pick     |
| ------------------------------------- | -------- |
| Sharing with a non-Python collaborator | CSV zip  |
| Loading into a pipeline               | Parquet  |
| Interactive SQL exploration           | DuckDB   |
| Version-controlled in git             | CSV      |
| Largest networks (>10M links)         | Parquet  |

## Example: Leavenworth CSV → Parquet round-trip

Using the bundled Leavenworth fixture:

```bash
# Once PR #84 is merged:
datagrove convert \
    packages/gmnspy/gmnspy/fixtures/leavenworth/csv \
    ./leavenworth_parquet \
    --format=parquet

datagrove validate ./leavenworth_parquet --json | jq '.summary'
# {"errors": 0, "warnings": 0, "tables": 9}
```

Programmatic equivalent (works today):

```python
from datagrove import Package

src = Package.from_source(
    "packages/gmnspy/gmnspy/fixtures/leavenworth/csv"
)
src.write("./leavenworth_parquet", format="parquet")

# Round-trip check
dst = Package.from_source("./leavenworth_parquet")
assert dst.validate().ok
```

## Example: CSV → DuckDB for ad-hoc SQL

```python
from datagrove import Package

pkg = Package.from_source("./my_network")
pkg.write("./my_network.duckdb", format="duckdb")
```

```bash
duckdb ./my_network.duckdb \
  "SELECT facility_type, COUNT(*) AS n
     FROM link
    GROUP BY 1
    ORDER BY n DESC;"
```

## Example: zip a package for sharing

```python
from datagrove import Package

Package.from_source("./my_network").write(
    "./my_network.zip", format="zip-csv"
)
```

The recipient runs `datagrove validate my_network.zip` directly against
the zip — no unpack step needed.

## Pitfalls

- **Don't overwrite the source.** Always write to a fresh directory; the
  writer assumes the destination is empty.
- **Parquet column types are stricter than CSV.** A CSV column that happens
  to be all integers but is declared `string` will write a string column.
  If you want typed numeric output, fix the schema first.
- **DuckDB writes one file** — losing the file loses everything. CSV/Parquet
  directories degrade more gracefully under partial corruption.
- **Geometry as WKT survives all formats.** Native geo types (e.g.
  GeoParquet) are not currently emitted.

## See also

- `datagrove-validate` — validate before and after conversion
- `gmns-validate` — GMNS-specific checks on the converted output
- PR #84 — adds the first-class `datagrove convert` CLI command
- `packages/datagrove/datagrove/io/` — read/write backends per format
