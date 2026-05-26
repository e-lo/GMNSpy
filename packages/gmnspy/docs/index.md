---
title: gmnspy
audience: users
summary: Python toolkit for the General Modeling Network Specification — load, validate, scope, edit GMNS networks at regional scale, with CLI / notebook / HTTP / MCP surfaces. Built on datagrove.
---

# gmnspy

A Python toolkit for the [General Modeling Network Specification (GMNS)](https://github.com/zephyr-data-specs/GMNS) — the Zephyr Foundation's open standard for routable transportation networks. Built on top of [datagrove](https://e-lo.github.io/GMNSpy/datagrove/).

## What problems gmnspy solves

**Reading any GMNS network without writing import code.** Local CSV directory, S3 parquet partition, single-file DuckDB, zipped CSV bundle — same `Network.from_source(...)` call, same lazy-evaluation behaviour:

```python
from gmnspy import Network

net = Network.from_source("./my-network/")              # CSV directory
net = Network.from_source("s3://bucket/network.parquet/")  # cloud parquet
net = Network.from_source("./network.duckdb")              # single duckdb
```

**Validation in one report.** `net.validate()` covers structural (required tables), schema (per-field constraints), foreign-key (cross-table integrity), and sync-state (have FKs gone stale since the last edit?). Severity-graded, rendered as rich console / JSON / interactive HTML.

**Data quality beyond the spec.** Seven rules out of the box — high-speed-on-residential, disconnected components, lane-count mismatch, near-duplicate nodes, sharp-angle bends, implausible v/c ratios, missing critical fields. Plug in your own with a class + entry point.

**Network-aware scope** at regional scale. BFS-induced subgraph from seed nodes, Dijkstra-bounded network buffer, spatial-buffer from any link or point, connected-component, zone filter. Chainable, with FK pushdown to every related table (TOD overrides, lane detail, signal control).

**Editing with atomic rollback.** `with Session(net) as s: simplify_geometry(net, s); merge_close_nodes(net, s)` — commit on clean exit, roll back on exception. Persisted log as a sidecar parquet so you can replay later.

**Surfaces for every workflow.** CLI for shells and scripts, notebook `_repr_html_` for Jupyter, FastAPI HTTP server for self-hosting, MCP server for Claude Desktop / Claude Code, every command supports `--json`.

## Use cases — when to install gmnspy

<div class="grid cards" markdown>

-   :material-map:{ .lg .middle } &nbsp;**MPO / DOT planning**

    ---

    Loading regional networks from OSM-derived sources, validating against the spec, applying data-quality checks before they feed a model.

-   :material-truck-fast-outline:{ .lg .middle } &nbsp;**Travel-demand modeling**

    ---

    Scoping a regional GMNS network down to a project area or analysis subnet, exporting to your modeling tool's format with zero conversion code.

-   :material-pencil-ruler:{ .lg .middle } &nbsp;**Network editing**

    ---

    Cleaning up an OSM-extract before it goes into a model — simplify geometry, merge near-duplicate nodes, remove orphans, recompute lengths.

-   :material-robot-outline:{ .lg .middle } &nbsp;**AI-assisted analysis**

    ---

    Letting Claude (or any MCP-compatible agent) drive validation, quality checks, and scope queries through a tool-call loop.

-   :material-server-network:{ .lg .middle } &nbsp;**Self-hosted network API**

    ---

    Exposing a curated set of GMNS networks behind a FastAPI HTTP server with bearer-token auth for consumers in your organisation.

-   :material-school-outline:{ .lg .middle } &nbsp;**GTFS-GMNS interop research**

    ---

    Researching the bridge between transit schedules and routable street networks; gmnspy gives you the GMNS side as a stable substrate.

</div>

## Why install gmnspy

**GMNS spec built in.** Vendored 0.95 / 0.96 / 0.97 side-by-side. Default 0.97; per-call override `Network.from_source(path, spec_version="0.96")`. Networks load against the version they were written against — no silent upgrades.

**Regional scale on a laptop.** Lazy ibis + DuckDB by default. A 200k-node network reads in seconds and validates in tens of seconds. Spatial and graph indexes built on demand, cached to sidecar parquet, content-hash keyed for auto-invalidation.

**Three usage modes target the same data.** CLI, notebook, programmatic — choose by ergonomics, not capability.

**AI-first by design.** Every CLI command supports `--json` for tool-call loops. `llms.txt` + `llms-full.txt` + `ai/api-index.json` regenerate on every docs build. Optional MCP server (`gmnspy mcp serve`) for Claude Desktop / Claude Code. Five Claude Code Skills shipped in-repo.

**No vendor lock-in.** Pure Python under Apache 2.0. Engines, formats, quality rules, scope ops all behind protocols you can implement yourself.

## Install

Pick by what you need:

```bash
pip install gmnspy                # core: read, validate, scope
pip install 'gmnspy[clean]'       # + shapely + igraph + editing ops
pip install 'gmnspy[server]'      # + self-hostable HTTP server (FastAPI + uvicorn)
pip install 'gmnspy[mcp]'         # + MCP server for AI agents
pip install 'gmnspy[notebook]'    # + Jupyter rendering helpers
pip install 'gmnspy[clean,server,mcp,notebook]'  # everything
```

`datagrove` comes along automatically. You don't install both.

## Where to go next

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } &nbsp;**Quickstart**

    ---

    Install, load the bundled Leavenworth fixture, run validation in five minutes.

    [:octicons-arrow-right-24: Get started](quickstart.md)

-   :material-book-open-variant:{ .lg .middle } &nbsp;**What is GMNS?**

    ---

    Plain-English intro to the spec — what it defines, who maintains it, how it relates to GTFS / OSM / Frictionless.

    [:octicons-arrow-right-24: Spec overview](what-is-gmns.md)

-   :material-eye-outline:{ .lg .middle } &nbsp;**Visual tour**

    ---

    See the bundled Leavenworth network rendered as a map, validated, quality-checked, edited, and scoped — all in one notebook session.

    [:octicons-arrow-right-24: Visual tour](visual-tour.md)

-   :material-book-open-page-variant:{ .lg .middle } &nbsp;**Cookbook**

    ---

    Task-oriented recipes — read from S3, scope, edit with rollback, self-host, AI-drive.

    [:octicons-arrow-right-24: Browse recipes](cookbook/index.md)

-   :material-api:{ .lg .middle } &nbsp;**API reference**

    ---

    Every public symbol with stable anchors that match the api-index.json.

    [:octicons-arrow-right-24: API reference](reference/api.md)

-   :material-table:{ .lg .middle } &nbsp;**Schema reference**

    ---

    Every GMNS table, field, foreign key, with ER diagrams.

    [:octicons-arrow-right-24: Schema](reference/spec.md)

</div>

## Upgrading from v0.3?

v1.0 is a clean-break rewrite. See the [migration guide](migration/v0.3-to-v1.0.md) for the side-by-side API mapping.
