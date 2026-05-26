---
title: datagrove API reference
audience: both
kind: reference
summary: Every public datagrove symbol, auto-generated from docstrings. Stable anchors match the codes in ai/api-index.json.
stability: stable
---

# datagrove API reference

Auto-generated from package docstrings via [mkdocstrings](https://mkdocstrings.github.io/). Every public symbol gets a stable anchor (`#<dotted.qualname>`) that matches the entries in [`ai/api-index.json`](../ai/index.md).

For task-oriented recipes see the [cookbook](../cookbook/index.md). For design rationale see [architecture](../architecture.md).

## Top-level

::: datagrove.dataset.Package
    options:
      members:
        - from_source
        - from_tables
        - validate
        - write
        - safe_count
        - tables
      show_root_heading: true

::: datagrove.dataset.Table
    options:
      members:
        - filter
        - select
        - head
        - count
        - to_pandas
        - to_polars
        - collect
        - columns
      show_root_heading: true

## Engines

::: datagrove.engines.Engine

::: datagrove.engines.get_engine

::: datagrove.engines.register_engine

::: datagrove.engines.resolve_engine

## Reports

::: datagrove.reports.ValidationReport

::: datagrove.reports.Issue

::: datagrove.reports.Severity

::: datagrove.reports.Category

## Editing

::: datagrove.editing.Edit

::: datagrove.editing.EditResult

::: datagrove.editing.Session
    options:
      members:
        - add_edit
        - rollback

::: datagrove.editing.rollback

## Quality (generic framework)

::: datagrove.quality.Rule

::: datagrove.quality.RuleConfig

::: datagrove.quality.run_quality

## Operations (cost model + gating)

::: datagrove.operations.OperationCost

::: datagrove.operations.gate

::: datagrove.operations.ApprovalRequired

::: datagrove.operations.Batch

::: datagrove.operations.coalesce

## API server primitives

::: datagrove.api.build_app

::: datagrove.api.PackageRegistry
    options:
      members:
        - require
        - source_for
        - describe
        - list_ids

::: datagrove.api.ServerSettings

::: datagrove.api.AuthSettings

::: datagrove.api.ExtraRouterFactory

::: datagrove.api.AuthDep

::: datagrove.api.PackageLoader

## MCP primitives

::: datagrove.mcp.build_server

## See also

* [`shared/ai/index.md`](../ai/index.md) — explains the api-index.json + llms.txt artifacts.
* [datagrove cookbook](../cookbook/index.md)
* [Architecture](../architecture.md)
