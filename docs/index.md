---
title: GMNSpy + datagrove
audience: both
hide:
  - navigation
  - toc
summary: Two PyPI packages with separate utility and separate audiences. datagrove is the generic Frictionless data-package engine; gmnspy is the GMNS-specific toolkit built on top. Each has its own documentation site — pick the one that matches your work.
---

# GMNSpy + datagrove

This repo holds **two PyPI packages with separate utility and separate audiences**. Each ships its own documentation site:

<div class="grid cards" markdown>

-   :material-database-outline:{ .lg .middle } &nbsp;**datagrove**

    ---

    Generic engine for **Frictionless tabular data packages** — any spec, any backend. Lazy ibis (DuckDB) by default, pandas / polars on demand. Reads CSV / Parquet / DuckDB / zip-CSV from local paths and URLs with a credentials cascade. Composable primitives for validation, scope, editing, HTTP and MCP.

    Pick datagrove if you're working with **any Frictionless data package** — GTFS-derived feeds, OGD datasets, a custom internal spec, or building your own toolkit.

    [:octicons-arrow-right-24: datagrove docs](https://e-lo.github.io/GMNSpy/datagrove/){ .md-button .md-button--primary }
    [Quickstart](https://e-lo.github.io/GMNSpy/datagrove/quickstart/){ .md-button }

-   :material-map-marker-path:{ .lg .middle } &nbsp;**gmnspy**

    ---

    GMNS-specific toolkit on top of datagrove. Adds the `Network` class, the vendored GMNS spec (0.95 / 0.96 / 0.97), network-aware scope operations, the data-quality rule pack, optional editing tools with rollback, and an optional self-hosted HTTP server + MCP server.

    Pick gmnspy if you're working with **transportation networks** — DOT / MPO planning, travel-demand modeling, GTFS ↔ GMNS interop, OSM-derived routing graphs.

    [:octicons-arrow-right-24: gmnspy docs](https://e-lo.github.io/GMNSpy/gmnspy/){ .md-button .md-button--primary }
    [Quickstart](https://e-lo.github.io/GMNSpy/gmnspy/quickstart/){ .md-button }

</div>

## Which package do I install?

Installing `gmnspy` brings `datagrove` along automatically. You only install `datagrove` directly if you're working on something non-GMNS.

```bash
pip install gmnspy            # GMNS toolkit (brings datagrove with it)
pip install datagrove         # generic engine only — for non-GMNS use cases
```

## Source

* GitHub: [e-lo/GMNSpy](https://github.com/e-lo/GMNSpy) — monorepo holding both packages.
* License: [Apache-2.0](https://github.com/e-lo/GMNSpy/blob/main/LICENSE).
* Status: v1.0 in beta. `gmnspy-v1.0.0` ships when the [Phase 5 acceptance criteria](https://github.com/e-lo/GMNSpy/issues?q=label%3Ablocks-ga) are green.

## Contributing

Both packages live in the same monorepo. See the [development guide](https://e-lo.github.io/GMNSpy/datagrove/development/) (in the datagrove site — it covers the monorepo as a whole).
