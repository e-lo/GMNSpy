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

Convert the bundled Leavenworth CSV directory into a parquet directory. Destination extension determines the output format:

```bash
gmnspy convert packages/gmnspy/gmnspy/fixtures/leavenworth/csv ./leavenworth.parquet
```

Expected:

```text
wrote 9 tables to ./leavenworth.parquet (parquet)
```

The same network reloads ~5× faster than the CSV directory it came from.

## Step-by-step

### 1. Pick the destination format

Each format has different trade-offs for cold-read latency, write speed, and predicate pushdown. Rule of thumb: **parquet for interchange, duckdb for repeated local use, zipcsv for emailing, csv only when a downstream tool demands it**.

| Format | Cold read | Write | Predicate pushdown | Portability |
|---|---|---|---|---|
| `csv` (directory) | Slowest — full scan, no schema. | Slow — text encoding. | None. | Universal. Any tool reads CSV. |
| `parquet` (directory or file) | Fast — columnar, schema embedded. | Fast. | Yes — column + row-group prune. | Wide. Arrow, DuckDB, Polars, pandas. |
| `duckdb` (single file) | Fastest — pre-indexed, statistics cached. | Slowest — DDL + insert per table. | Yes — full SQL. | DuckDB-only readers. |
| `zipcsv` (single `.zip`) | Slow — text decode after unzip. | Medium. | None. | Universal + single-file. |

### 2. Run `gmnspy convert`

The CLI infers format from the destination extension (`.parquet`, `.duckdb`, `.zip`) or from whether the target is an existing directory:

```bash
gmnspy convert <source> <dest>
```

Override the inference with `--format` when the extension is missing or ambiguous:

```bash
gmnspy convert ./csv_dir ./out.duckdb --format duckdb
gmnspy convert ./csv_dir ./out          --format parquet
```

The same dispatch is available from Python — `Network.write` and `Package.write` accept the same destination + optional `format=` kwarg as the CLI:

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth

net = Network.from_source(leavenworth.csv_dir())
net.write("./leavenworth.duckdb")
```

### 3. (Optional) Pick an engine

Switch to the pandas engine if you hit the null-typed column issue in [#163](https://github.com/e-lo/GMNSpy/issues/163) — DuckDB's strict typing rejects columns that are entirely null in the source, while pandas coerces them to object/None:

```bash
gmnspy convert ./csv_dir ./out.parquet --engine pandas
```

### 4. Verify the round-trip

Load the destination back and validate against the spec. This catches any schema drift introduced by the conversion (e.g. a string column that came back as int because every value happened to parse):

```python
from gmnspy import Network

net = Network.from_source("./leavenworth.parquet")
report = net.validate()
assert report.passed, [i.code for i in report.issues if i.is_error()]
print(f"{net.spec_version}: {net.links.count()} links — round-trip clean")
```

See [validate-network](../../gmnspy/cookbook/validate-network.md) for what's in the report.

### 5. (Optional) Convert remote → local

`convert` accepts the same URL surface as `from_source`, so cloud → local is a one-liner. The download happens once; from then on you load the local copy:

```bash
gmnspy convert s3://my-bucket/networks/leavenworth/ ./leavenworth.parquet
```

See [Read from S3](read-from-s3.md) for credential handling.

## Common variations

???+ note "Default — CLI conversion with extension inference"
    Most conversions are one-line CLI calls. The destination extension picks the format.

    ```bash
    gmnspy convert ./csv_dir ./out.parquet
    ```

??? note "Programmatic conversion in Python"
    Same dispatch as the CLI; useful inside scripts and notebooks.

    ```python
    from datagrove.package import Package
    Package.from_source(src).write(dest)
    ```

??? note "Re-pack only a subset of tables"
    Keep just the tables you need; the writer drops the rest.

    ```python
    Package.from_source(src).select(["link", "node"]).write(dest)
    ```

    See the [scope recipes](index.md) for FK-aware variants that walk relationships.

??? note "Partitioned parquet (one file per table)"
    Pass a directory destination with `--format parquet`. The writer creates one file per table; per-table row-group partitioning is the parquet engine's default.

    ```bash
    gmnspy convert ./csv_dir ./parquet_dir --format parquet
    ```

??? note "Compress the CSV output (zipcsv)"
    Same wire format as CSV but typically 5–10× smaller — useful for emailing or storing in artifact stores.

    ```bash
    gmnspy convert ./csv_dir ./out.zip --format zipcsv
    ```

??? note "Validate during the write"
    Raises before writing if any ERROR finding fires.

    ```python
    Package.from_source(src).validate().write(dest)
    ```

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
* [Architecture](../../shared/architecture.md) — Package → Engine → format dispatch.
* [API reference](../reference/api.md) — `Package.write`, `Package.from_source`.
