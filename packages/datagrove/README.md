# datagrove

Generic, Frictionless-aligned tabular-data-package engine. Powers [GMNSpy](https://github.com/e-lo/GMNSpy) and is designed to support other tabular data specifications (GTFS, custom formats) via the same primitives.

**Status:** pre-alpha (`0.1.0.dev0`). API is unstable.

## What it provides

- Pydantic models for Frictionless Data Package, Resource, Schema, Field, ForeignKey
- Engine abstraction (Ibis/DuckDB default; Polars; Pandas)
- Format adapters: CSV, Parquet (partitioned), DuckDB, zipped CSV, remote URLs (fsspec)
- Validation framework: schema, structural, foreign-key, sync-state (dirty-tracker)
- Lazy dataset surface: `Package`, `Table`, `View` with geographic scoping (bbox, polygon, geometry-buffer)
- Operation cost model + gating, batched/pooled writes
- Report renderers: rich console, JSON, interactive single-file HTML
- Generic edit/diff/session/rollback framework
- **Generic CLI** (`datagrove …`): `validate`, `convert`, `info`, `scope`, `describe` — extendable by domain packages via plugin pattern
- **Generic data-quality framework** (rule base class, threshold config, entry-point plugin discovery — no domain rules)
- **Generic notebook helpers** (`_repr_html_` for Package/Table/ValidationReport/EditResult)
- FastAPI primitives for building self-hostable data APIs
- MCP server primitives for AI-agent consumption
- Docgen: markdown + `llms.txt` + machine-readable API index

## Composition with domain packages

`gmnspy` and (in the future) similar packages compose on top:

| Concern | datagrove (generic) | gmnspy (GMNS-specific) |
|---|---|---|
| editing framework | `editing/` | `clean/` (simplify_geometry, …) |
| HTTP server | `api/` (primitives) | `server/` (assembled FastAPI app) |
| MCP | `mcp/` (primitives) | `mcp/` (GMNS tool registrations) |
| CLI | `cli/` (generic commands + extension hook) | `cli/` (GMNS commands on the same typer app) |
| Quality | `quality/` (rule framework) | `quality/` (GMNS rule pack via entry point) |
| Notebook | `notebook/` (Package/Table/ValidationReport reprs) | `notebook/` (Network repr + scope widgets) |

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
