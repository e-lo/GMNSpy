---
title: GMNSpy + datagrove
audience: both
hide:
  - navigation
summary: Two PyPI packages that solve different problems — datagrove is the generic Frictionless data-package engine, gmnspy is the GMNS-specific toolkit built on top. Pick the one that matches your work.
---

# GMNSpy + datagrove documentation

Two related Python packages, one repo, two distinct audiences.

<div class="grid cards" markdown>

-   :material-database-outline:{ .lg .middle } &nbsp;**datagrove**

    ---

    Generic engine for **Frictionless tabular data packages** — any spec, any backend. Lazy ibis (DuckDB) by default, pandas or polars on demand. Reads CSV / Parquet / DuckDB / zip-CSV from local paths and URLs with a credentials cascade. Validation, scope, editing, HTTP and MCP primitives.

    Pick datagrove if you're working with **any Frictionless data package** — GTFS, OGD, custom internal spec, or building your own toolkit.

    [:octicons-arrow-right-24: Explore datagrove](datagrove/index.md){ .md-button .md-button--primary }

-   :material-map-marker-path:{ .lg .middle } &nbsp;**gmnspy**

    ---

    GMNS-specific toolkit on top of datagrove. Adds the `Network` class, the vendored GMNS spec (0.95 / 0.96 / 0.97), network-aware scope operations, the data-quality rule pack, optional editing tools with rollback, and an optional self-hosted HTTP server + MCP server.

    Pick gmnspy if you're working with **transportation networks** — DOT planning, MPO models, GTFS-GMNS interop, OSM-derived routing graphs.

    [:octicons-arrow-right-24: Explore gmnspy](gmnspy/index.md){ .md-button .md-button--primary }

</div>

## Which package do I install?

Installing `gmnspy` brings `datagrove` along automatically — you only pick separately if you're building on `datagrove` for a non-GMNS use case.

=== "I work with GMNS transportation networks"

    Install `gmnspy`. `datagrove` comes along as a dependency, and every datagrove API is reachable from your code if you need it.

    ```bash
    pip install gmnspy                # core: read, validate, scope
    pip install 'gmnspy[clean]'       # + shapely + igraph + editing ops
    pip install 'gmnspy[server]'      # + self-hostable HTTP server
    pip install 'gmnspy[mcp]'         # + MCP server for AI agents
    pip install 'gmnspy[notebook]'    # + Jupyter rendering helpers
    pip install 'gmnspy[clean,server,mcp,notebook]'  # everything
    ```

=== "I work with non-GMNS Frictionless packages"

    Install `datagrove` directly.

    ```bash
    pip install datagrove
    ```

    Then jump to the [datagrove quickstart](datagrove/quickstart.md).

## Shared resources

Some concepts apply to both packages — read them once and they apply everywhere.

<div class="grid cards" markdown>

-   :material-book-open:{ .lg .middle } &nbsp;**Concepts**

    ---

    [Frictionless data packages](shared/concepts/frictionless.md) — the spec both packages build on.

-   :material-robot-outline:{ .lg .middle } &nbsp;**AI surface**

    ---

    [Drive both packages from an AI agent](shared/ai/index.md) — llms.txt, api-index.json, Claude Code Skills, MCP server.

-   :material-architecture:{ .lg .middle } &nbsp;**Architecture**

    ---

    [Single source of truth](shared/architecture.md) for the design — defaults, rationales, extension points.

-   :material-account-multiple-plus:{ .lg .middle } &nbsp;**Contribute**

    ---

    [Development guide](shared/development.md) — how to set up the monorepo, run tests, file PRs.

</div>

## Status

This is the **v1.0 documentation**. v1.0 is a clean-break rewrite of GMNSpy v0.3.x — see the [migration guide](gmnspy/migration/v0.3-to-v1.0.md) for the side-by-side API mapping. The project is **currently in beta**; `gmnspy-v1.0.0` ships when the [Phase 5 acceptance criteria](https://github.com/e-lo/GMNSpy/issues?q=label%3Ablocks-ga) are green.
