# corral

Generic, Frictionless-aligned tabular-data-package engine. Powers [Netstead](https://github.com/e-lo/netstead) and is designed to support other tabular data specifications (GTFS, custom formats) via the same primitives.

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
- **Generic CLI** (`corral …`): `validate`, `convert`, `info`, `scope`, `describe` — extendable by domain packages via plugin pattern
- **Generic data-quality framework** (rule base class, threshold config, entry-point plugin discovery — no domain rules)
- **Generic notebook helpers** (`_repr_html_` for Package/Table/ValidationReport/EditResult)
- FastAPI primitives for building self-hostable data APIs
- MCP server primitives for AI-agent consumption
- Docgen: markdown + `llms.txt` + machine-readable API index

## Composition with domain packages

`netstead` and (in the future) similar packages compose on top:

| Concern | corral (generic) | netstead (GMNS-specific) |
|---|---|---|
| editing framework | `editing/` | `clean/` (simplify_geometry, …) |
| HTTP server | `api/` (primitives) | `server/` (assembled FastAPI app) |
| MCP | `mcp/` (primitives) | `mcp/` (GMNS tool registrations) |
| CLI | `cli/` (generic commands + extension hook) | `cli/` (GMNS commands on the same typer app) |
| Quality | `quality/` (rule framework) | `quality/` (GMNS rule pack via entry point) |
| Notebook | `notebook/` (Package/Table/ValidationReport reprs) | `notebook/` (Network repr + scope widgets) |

## Install

Pick the tool you already use — these are equivalent:

```bash
# uv (recommended — fastest, handles workspace projects + lockfiles)
uv add dbcorral

# uv pip (drop-in pip replacement, no project file needed)
uv pip install dbcorral

# pip (classic)
pip install dbcorral

# pipx (CLI-only, isolated env; gives you the `corral` command without
#       polluting your project env)
pipx install dbcorral
```

### Optional extras

```bash
# Engines (pick the one your downstream code already uses)
uv add 'dbcorral[polars]'      # lazy polars frames
uv add 'dbcorral[pandas]'      # eager pandas DataFrames

# Cloud storage backends (read from s3://, gs://, azure://)
uv add 'dbcorral[s3]'          # add 'gcs' or 'azure' as needed

# Credential helpers + AI surface
uv add 'dbcorral[keyring]'     # resolve creds from system keychain
uv add 'dbcorral[mcp]'         # `corral mcp serve` for Claude Desktop / Code
```

Combine extras with commas: `uv add 'dbcorral[polars,s3,keyring]'`.

## Repo

Developed in the [Netstead monorepo](https://github.com/e-lo/netstead) under `packages/corral/`.
