# datagrove v0.1.0-beta.1

> **This is a public preview, not GA.** The API is stable enough to build against; we expect bug reports and small breaking changes before `v0.1.0`. See [BETA.md](https://github.com/e-lo/GMNSpy/blob/main/BETA.md) for the beta program.

## What datagrove is

A generic engine for Frictionless Data Packages — code-agnostic schemas, lazy ibis + DuckDB by default, foreign-key + sync-state validation, geographic scoping, and edit/rollback primitives. Built so spec-specific toolkits (like `gmnspy` for GMNS, or future ones for GTFS) can compose on top instead of reimplementing the engine.

This is the **first public release** of datagrove as a standalone package.

## Quick start

```bash
uv add 'datagrove==0.1.0b1'        # uv
pip install 'datagrove==0.1.0b1'   # pip
```

```python
import datagrove

pkg = datagrove.read("path/to/datapackage.json")
report = pkg.validate()
report.to_html("report.html")
```

## Highlights

- **`datagrove.read()`** — one front door for `.csv`, `.parquet`, `.duckdb`, `.zip` — local, `s3://`, `https://`, or `duckdb://`.
- **Three interchangeable engines** — ibis (default), polars (`[polars]` extra), pandas (`[pandas]` extra). Switch per call.
- **Four-pass validator** returning a single `ValidationReport` — structural, schema, foreign-key, sync-state. Rich / JSON / interactive HTML output.
- **Spatial scope primitives** (`from_bbox`, `from_polygon`, `from_geometry_buffer`) — predicates push down to DuckDB SQL.
- **Generic edit/rollback framework** with atomic sessions.
- **FastAPI + MCP primitives** for downstream packages to compose into concrete servers.

## Compatibility

- Python 3.11, 3.12, 3.13.
- Optional extras: `polars`, `pandas`, `s3`, `gcs`, `azure`, `keyring`, `mcp`.

## Known limitations

- `Package.from_source()` mis-dispatches `.csv.zip` to the CSV adapter — workaround: load via `csv_dir()` or `parquet_dir()`.
- `datagrove.quality.run()` is named `run_quality()` — alias coming.
- HTML report doesn't yet embed a map view for geo-located issues.

## How to report issues

[**Beta-feedback issue template →**](https://github.com/e-lo/GMNSpy/issues/new?template=beta-feedback.md)

## Full CHANGELOG

[packages/datagrove/CHANGELOG.md](https://github.com/e-lo/GMNSpy/blob/main/packages/datagrove/CHANGELOG.md)

**Full Changelog**: https://github.com/e-lo/GMNSpy/commits/datagrove-v0.1.0-beta.1
