# datagrove

Generic, Frictionless-aligned tabular-data-package engine. Powers [GMNSpy](https://github.com/e-lo/GMNSpy) and is designed to support other tabular data specifications (GTFS, custom formats) via the same primitives.

**Status:** pre-alpha (`0.1.0.dev0`). API is unstable.

## What it provides

- Pydantic models for Frictionless Data Package, Resource, Schema, Field, ForeignKey
- Engine abstraction (Ibis/DuckDB default; Polars; Pandas)
- Format adapters: CSV, Parquet (partitioned), DuckDB, zipped CSV, remote URLs (fsspec)
- Validation framework: schema, structural, foreign-key, sync-state (dirty-tracker)
- Lazy dataset surface: `Package`, `Table`, `View` with geographic scoping
- Operation cost model + gating, batched/pooled writes
- Report renderers: rich console, JSON, interactive single-file HTML
- Generic edit/diff/session/rollback framework
- FastAPI primitives for building self-hostable data APIs
- MCP server primitives for AI-agent consumption
- Docgen: markdown + `llms.txt` + machine-readable API index

## Install

```bash
pip install datagrove
# with polars conversion
pip install 'datagrove[polars,pandas]'
# with cloud storage backends
pip install 'datagrove[s3,gcs,azure]'
```

## Repo

Developed in the [GMNSpy monorepo](https://github.com/e-lo/GMNSpy) under `packages/datagrove/`.
