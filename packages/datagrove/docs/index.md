---
title: datagrove
audience: users
summary: Generic Frictionless data-package engine — lazy ibis with DuckDB, with pandas + polars on demand. Reads CSV / Parquet / DuckDB / zip-CSV from local paths and URLs with a credentials cascade. Composable validation, scope, editing, HTTP and MCP primitives.
---

# datagrove

A generic engine for tabular data packages in the [Frictionless](concepts/frictionless.md) format. Lazy by default, regional-scale ready, with composable primitives for validation, scope, editing, and serving.

## What problems datagrove solves

**Reading any Frictionless data package**, regardless of physical format, with one API surface:

```python
from datagrove import Package

pkg = Package.from_source("local/path/datapackage.json")      # local directory
pkg = Package.from_source("s3://bucket/path/datapackage.json")  # cloud, credentials cascade
pkg = Package.from_source("./mydata.duckdb")                    # single-file duckdb
pkg = Package.from_source("./mydata.csv.zip")                   # zipped CSV bundle
```

**Lazy evaluation at regional scale.** Tables aren't materialised until you ask. `pkg.tables["link"].filter(...).count()` pushes the count to DuckDB; only the integer comes back to Python.

**Engine choice without API rewrite.** The same `Package.from_source(...).validate()` works against ibis (default), pandas, or polars. Switch via `engine=` per call.

**Validation as a single report.** `pkg.validate()` returns one `ValidationReport` covering structural, schema, foreign-key, and sync-state checks. Severity-graded; rendered as rich console, JSON, or interactive HTML.

**Composable editing with rollback.** Open a `Session`, apply one or many edits, commit or roll back atomically. Persisted log as a sidecar parquet file.

**Generic surfaces** — CLI, FastAPI HTTP server, and MCP server — all reusable for any domain-specific spec that builds on datagrove (gmnspy being the canonical example).

## Use cases — when to install datagrove directly

<div class="grid cards" markdown>

-   :material-truck-fast-outline:{ .lg .middle } &nbsp;**GTFS interop research**

    ---

    Building a GTFS ↔ GMNS bridge, or analysing GTFS feeds with the same toolchain you use for other tabular specs.

-   :material-file-cog-outline:{ .lg .middle } &nbsp;**Custom internal spec**

    ---

    Your organisation has a tabular data spec (sensor metadata, asset catalogs, planning datasets) that you want to validate, version, and serve consistently.

-   :material-cloud-outline:{ .lg .middle } &nbsp;**Cloud-resident data**

    ---

    Tables live in S3 / Azure Blob / GCS, and you want lazy SQL pushdown without writing the connection plumbing yourself.

-   :material-wrench-cog-outline:{ .lg .middle } &nbsp;**Building your own toolkit**

    ---

    You want the generic primitives (engine ABC, FormatAdapter registry, ValidationReport, Session, FastAPI helpers) to compose into a domain-specific package. gmnspy is the worked example.

</div>

## Why install datagrove

**It's small and focused.** Generic data-package primitives only — no domain semantics. Easy to reason about, easy to extend.

**Backend-agnostic.** ibis for SQL pushdown by default, pandas for compatibility, polars for fast in-memory. Add a backend by implementing the `Engine` protocol; no API rewrite.

**Production-grade defaults.** Bearer-token auth on the HTTP server by default. Warn-loudly on misconfiguration (e.g. `auth=none` + non-localhost bind). Cost-model gating on long operations with explicit approval semantics.

**Extension points are first-class.** `register_adapter` for new formats. `register_engine` for new backends. `register_rule` for quality rules. `extra_router_factory` for HTTP extensions. Same pattern across the surface.

## Install

```bash
pip install datagrove
```

That's it. No optional extras at the datagrove level — every dependency is core. (Optional extras live one level up in `gmnspy`.)

## Where to go next

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } &nbsp;**Quickstart**

    ---

    Load a data package, validate it, scope it, write it out — in five minutes.

    [:octicons-arrow-right-24: Get started](quickstart.md)

-   :material-book-open-page-variant:{ .lg .middle } &nbsp;**Cookbook**

    ---

    Task-oriented recipes — read from S3, convert formats, spatial scope.

    [:octicons-arrow-right-24: Browse recipes](cookbook/index.md)

-   :material-api:{ .lg .middle } &nbsp;**API reference**

    ---

    Every public symbol, auto-generated from docstrings, with stable anchors.

    [:octicons-arrow-right-24: API reference](reference/api.md)

-   :material-architecture:{ .lg .middle } &nbsp;**Architecture**

    ---

    Defaults, rationales, extension points. Single source of truth.

    [:octicons-arrow-right-24: Architecture](architecture.md)

</div>
