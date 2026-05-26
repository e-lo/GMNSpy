---
title: Quickstart
audience: users
kind: howto
summary: Install, load any Frictionless data package, validate it, scope it, and write it out in five minutes — using only datagrove, no GMNS bits.
---

# Quickstart — datagrove

## When to use this

You want to load + validate + (optionally) spatially scope a Frictionless data package — any spec, not just GMNS — and see what `datagrove` gives you in five minutes. If you're working with GMNS networks specifically, the [gmnspy quickstart](https://e-lo.github.io/GMNSpy/gmnspy/quickstart/) is the better starting point; everything here applies underneath that surface.

## Quick example

The fastest way to confirm `datagrove` is wired up is to load a real Frictionless package, run the four-pass validator, and print a one-line summary. The example below uses the bundled Leavenworth GMNS fixture as a stand-in for "any Frictionless package" — the API is identical regardless of spec.

```bash
pip install datagrove
```

Then in Python:

```python
from datagrove import Package
from gmnspy.fixtures import leavenworth  # any Frictionless dir works here

pkg = Package.from_source(leavenworth.csv_dir(), spec=leavenworth.spec_path())
report = pkg.validate()
print(f"{len(pkg.tables)} tables, {len(report.issues)} validation issues")
```

Expected:

```text
25 tables, 0 validation issues
```

You just loaded a Frictionless data package through the default ibis + DuckDB engine, then ran the structural / schema / FK / sync-state validator in a single call. Nothing was eagerly materialised — `pkg.tables["link"]` is still a lazy expression.

## Step-by-step

### 1. Install

The default install ships everything for the four-pass validator below. Pick your tool:

=== "uv (recommended)"

    ```bash
    uv add datagrove
    ```

=== "uv pip"

    ```bash
    uv pip install datagrove
    ```

=== "pip"

    ```bash
    pip install datagrove
    ```

=== "pipx"

    ```bash
    pipx install datagrove
    ```

Optional extras (`polars` / `pandas` / `s3` / `gcs` / `azure` / `keyring` / `mcp`) opt in to alternative engines, cloud backends, and the AI surface — see the [install guide](index.md#optional-extras) for the full list.

### 2. Load a Frictionless package

`Package.from_source` accepts a local path, an `s3://` / `https://` / `duckdb://` URL, or a directory of CSV / Parquet / DuckDB / zip-CSV files. The example below loads the bundled Leavenworth fixture, which is a CSV directory. Because a CSV-only directory doesn't carry a `datapackage.json` manifest, pass `spec=` explicitly to tell `datagrove` which schema to validate against.

```python
from datagrove import Package
from gmnspy.fixtures import leavenworth

pkg = Package.from_source(
    leavenworth.csv_dir(),
    spec=leavenworth.spec_path(),
)
```

You should see something like:

```python
>>> pkg
<Package: 25 tables, source=.../leavenworth/csv>
```

Substitute any other Frictionless package — your own spec, a GTFS feed converted to a Frictionless package, or a cloud-hosted parquet partition — and the rest of the steps below are identical.

### 3. Validate and read the report

Validation runs four passes in one call — **structural** (required resources present), **schema** (field types and constraints), **foreign-key** (cross-table integrity), and **sync-state** (have FKs gone stale since a previous edit?). The result is one `ValidationReport` with severity-graded issues.

```python
report = pkg.validate()
print(f"{len(report.issues)} issues across {len(pkg.tables)} tables")

for issue in report.issues[:5]:
    print(f"  {issue.severity.value:9} {issue.code:30} {issue.message[:60]}")
```

In a Jupyter notebook, evaluating `report` on its own renders an HTML card grouped by severity. In a script, you can also serialise to JSON for CI:

```python
report.to_json("validation.json")
```

### 4. Scope to a spatial subset

If your package has a geometry column (any WKT or WKB), `datagrove.dataset.view.from_bbox` returns a lazy view filtered to features inside a bounding box. The example below scopes the Leavenworth `link` table to a small bbox around the historic core.

```python
from datagrove.dataset.view import from_bbox

links = pkg.tables["link"]
scoped_links = from_bbox(
    links,
    bbox=(-120.665, 47.594, -120.655, 47.600),  # (minx, miny, maxx, maxy)
    geometry_table=pkg.tables["geometry"],
    geometry_fk="geometry_id",
)
print(f"scoped: {scoped_links.count()} links")
```

The filter pushes down to DuckDB — only the matching rows are read.

### 5. Write the package out

`pkg.write(dest)` round-trips the package to a new location. The output format is inferred from the extension: `.parquet` for a Parquet directory, `.duckdb` for a single-file DuckDB, or a directory for CSV.

```python
pkg.write("./out.parquet")
```

The `datapackage.json` manifest is regenerated alongside the data, so the written-out package is itself a valid Frictionless package.

## Common variations

Each accordion below is one alternative to the defaults used above. The first (most common) is expanded; the rest are collapsed — open the one that matches your situation.

???+ note "Switch the backend engine to pandas or polars"
    Default is `IbisEngine` (lazy, DuckDB-backed). Switch to pandas for eager DataFrame ergonomics, or polars when you want fast in-memory analytics.

    ```python
    from datagrove.engines.pandas_engine import PandasEngine
    # from datagrove.engines.polars_engine import PolarsEngine

    pkg = Package.from_source(path, spec=spec, engine=PandasEngine())
    ```

??? note "Read from S3 with credentials"
    Credentials resolve via a cascade: keyword arg → `DATAGROVE_CRED_<host>_TOKEN` env var → OS keyring → `.netrc`. No code changes needed if the environment is set up.

    ```python
    pkg = Package.from_source(
        "s3://bucket/path/datapackage.json",
    )
    ```

??? note "Load only a subset of tables"
    Pass `tables=` to materialise only the tables you need — useful when the package is large and you only care about a few resources.

    ```python
    pkg = Package.from_source(
        path,
        spec=spec,
        tables=["link", "node", "geometry"],
    )
    ```

??? note "Pass the spec from a URL or another package"
    `spec=` accepts a local path, a URL, or an already-loaded `Spec` object. Useful for sharing a spec across many sibling datasets.

    ```python
    pkg = Package.from_source(
        path,
        spec="https://example.org/specs/my-spec/datapackage.json",
    )
    ```

## Pitfalls

* **No `datapackage.json` in your directory → pass `spec=` explicitly.** CSV-only fixtures and ad-hoc directories don't carry a manifest, so `datagrove` can't infer the schema. Point `spec=` at the canonical `datapackage.json` for your data. See [Frictionless data packages](concepts/frictionless.md) for the spec-vs-data distinction.
* **Credential cascade order matters.** Per-call `credentials=` always wins; otherwise `DATAGROVE_CRED_<host>_TOKEN` env var, then OS keyring, then `.netrc`. If you've stashed a token in two places, the higher-priority one is the one that gets used.
* **Lazy vs eager engine behaviour.** `IbisEngine` (default) doesn't materialise until you call `.execute()` / `.to_pandas()` / `.count()`. `PandasEngine` materialises every table at load time. Use ibis for regional-scale data; switch to pandas only when you actually need the DataFrame in memory.

## See also

* [Cookbook](cookbook/index.md) — task-oriented recipes (read from S3, convert formats, spatial scope).
* [API reference](reference/api.md) — every public symbol with stable anchors.
* [Architecture](architecture.md) — defaults, rationales, extension points.
* [Frictionless data packages](concepts/frictionless.md) — the spec `datagrove` builds on.
