---
title: Convert CSV ↔ Parquet ↔ DuckDB ↔ zip-CSV
audience: users
kind: howto
summary: Round-trip a data package between the four bundled storage formats — when to pick which, how the CLI and Python entry points compare.
---

# Convert CSV ↔ Parquet ↔ DuckDB ↔ zip-CSV

## When to use this

You have data in format X (a regulator handed you a folder of CSVs, an upstream pipeline emits parquet, a teammate sent a DuckDB file) and a downstream tool wants format Y. Or you're loading the same package over and over and want to switch to a format with faster cold-start.

## Quick example

```text
$ gmnspy convert packages/gmnspy/gmnspy/fixtures/leavenworth/csv ./leavenworth.parquet
wrote 9 tables to ./leavenworth.parquet (parquet)
```

That writes a parquet directory (one file per table) inferred from the destination extension. The same network reloads ~5× faster than the CSV directory it came from.

## Step-by-step

### 1. Pick the destination format

| Format | Cold read | Write | Predicate pushdown | Portability |
|---|---|---|---|---|
| `csv` (directory) | Slowest — full scan, no schema. | Slow — text encoding. | None. | Universal. Any tool reads CSV. |
| `parquet` (directory or file) | Fast — columnar, schema embedded. | Fast. | Yes — column + row-group prune. | Wide. Arrow, DuckDB, Polars, pandas. |
| `duckdb` (single file) | Fastest — pre-indexed, statistics cached. | Slowest — DDL + insert per table. | Yes — full SQL. | DuckDB-only readers. |
| `zipcsv` (single `.zip`) | Slow — text decode after unzip. | Medium. | None. | Universal + single-file. |

Rule of thumb: **parquet for interchange, duckdb for repeated local use, zipcsv for emailing, csv only when a downstream tool demands it**.

### 2. Run `gmnspy convert`

```text
$ gmnspy convert <source> <dest>
```

The format of `<dest>` is inferred from the extension (`.parquet`, `.duckdb`, `.zip`) or from whether it's an existing directory (CSV / Parquet). Override the inference with `--format`:

```text
$ gmnspy convert ./csv_dir ./out.duckdb --format duckdb
$ gmnspy convert ./csv_dir ./out          --format parquet
```

Or programmatically:

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth

net = Network.from_source(leavenworth.csv_dir())
net.write("./leavenworth.duckdb")
```

`Network.write` and `Package.write` use the same dispatch as the CLI — extension inference plus an optional `format=` kwarg.

### 3. (Optional) Pick an engine

```text
$ gmnspy convert ./csv_dir ./out.parquet --engine pandas
```

The default is the ibis engine. Switch to `pandas` if you hit the null-typed column issue tracked in [#163](https://github.com/e-lo/GMNSpy/issues/163) — DuckDB's strict typing rejects columns that are entirely null in the source. The pandas engine coerces them to object/None so the write succeeds.

### 4. Verify the round-trip

```python
from gmnspy import Network

net = Network.from_source("./leavenworth.parquet")
report = net.validate()
assert report.passed, [i.code for i in report.issues if i.is_error()]
print(f"{net.spec_version}: {net.links.count()} links — round-trip clean")
```

Validation against the spec catches any schema drift introduced by the conversion (e.g. a string column that came back as int because every value happened to parse). See [validate-network](validate-network.md) for what's in the report.

### 5. (Optional) Convert remote → local

`convert` accepts the same URL surface as `from_source`, so cloud → local is a one-liner:

```text
$ gmnspy convert s3://my-bucket/networks/leavenworth/ ./leavenworth.parquet
```

That downloads once, writes parquet locally, and from then on you load the local copy. See [Read from S3](read-from-s3.md) for credential handling.

## Common variations

| You want... | Do this |
|---|---|
| Programmatic conversion | `Package.from_source(src).write(dest)` — same dispatch as the CLI. |
| Re-pack only a few tables | `Package.from_source(src).select(["link", "node"]).write(dest)` — see [scope recipes](index.md#scope--geographic-subsetting) for FK-aware variants. |
| Partitioned parquet | `--format parquet` to a directory and the writer will create one file per table. Per-table row-group partitioning is the parquet engine's default. |
| Compress the CSV output | Convert to `zipcsv` instead — same wire format, 5-10× smaller. |
| Validate during the write | `Package.from_source(src).validate().write(dest)` raises before writing if any ERROR finding fires. |

## Pitfalls

* **DuckDB SQL DDL via PolarsEngine is not supported.** The polars engine doesn't speak DuckDB's `CREATE TABLE` dialect, so writing to `.duckdb` requires the default ibis engine. Pick `--engine ibis` or omit `--engine`.
* **Null-typed columns can fail strict-write backends.** If a column is 100% null in the source CSV, the ibis/duckdb engine may reject the write. Workarounds: `--engine pandas`, or open the source, fill the column with a typed default, and write. Tracked in [#163](https://github.com/e-lo/GMNSpy/issues/163).
* **Extension inference is case-sensitive.** `out.PARQUET` won't be recognised as parquet — pass `--format parquet`.
* **Converting *to* CSV loses dtypes.** Re-reading the CSV without a schema (no GMNS spec match) infers columns afresh. Round-trip safety relies on the schema being re-applied at load time, which happens automatically for GMNS-shaped directories.
* **DuckDB files lock per-process.** Two Python processes can't open the same `.duckdb` file in write mode at once. For shared use, write parquet instead; for one-writer-many-readers, ensure the writer closes the connection (the Engine does this when the `Network` is garbage-collected or `net.close()` is called).
* **Zip-CSV holds the whole archive in memory on read.** Fine for Leavenworth-scale networks; not fine for regional ones. Convert zip-CSV to parquet up-front if you'll re-read.
* **Overwriting an existing destination is allowed.** `convert` won't ask before clobbering — chain a `test -e dest && exit 1` in CI scripts if you need an explicit guard.

## See also

* [Read from S3](read-from-s3.md) — `convert` works across cloud schemes too (`gmnspy convert s3://… ./local.parquet`).
* [Architecture](../architecture.md) — Package → Engine → format dispatch.
* [API reference](../reference/api.md) — `Package.write`, `Package.from_source`.
