---
title: datagrove cookbook
audience: users
kind: concept
summary: Task-oriented recipes for the generic Frictionless data-package surface — read from S3, convert between formats, spatial scope.
---

# datagrove cookbook

Generic recipes — apply to any Frictionless package, not just GMNS. For GMNS-specific recipes (network-aware scope, quality rules, editing, MCP), see the [gmnspy cookbook](../../gmnspy/cookbook/index.md).

## I/O + formats

* [Read from S3 with credentials](read-from-s3.md) — credential cascade, partial loads, predicate pushdown.
* [Convert formats](convert-formats.md) — CSV ↔ Parquet ↔ DuckDB ↔ zip-CSV.

## Scope

* [Spatial scope — bbox and polygon](scope-bbox.md) — generic geometric scope on any geometry-bearing package.

## Contributing a recipe

A recipe is `kind: howto` per the [Page Style Guide](../../_page-style-guide.md). One-liner trigger, a runnable example with **prose before the code**, step-by-step, accordion-style variations, pitfalls, see-also.
