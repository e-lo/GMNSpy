---
title: corral API reference
audience: both
kind: reference
summary: Every public corral symbol, auto-generated from docstrings. Stable anchors match the codes in ai/api-index.json.
stability: stable
---

# corral API reference

Auto-generated from package docstrings via [mkdocstrings](https://mkdocstrings.github.io/). Every public symbol gets a stable anchor (`#<dotted.qualname>`) that matches the entries in [`ai/api-index.json`](../ai/index.md).

For task-oriented recipes see the [cookbook](../cookbook/index.md). For design rationale see [architecture](../architecture.md).

## Top-level

::: corral.dataset.Package
    options:
      members:
        - from_source
        - from_tables
        - validate
        - write
        - safe_count
        - tables
      show_root_heading: true

::: corral.dataset.Table
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

::: corral.engines.Engine

::: corral.engines.get_engine

::: corral.engines.register_engine

::: corral.engines.resolve_engine

## Reports

::: corral.reports.ValidationReport

::: corral.reports.Issue

::: corral.reports.Severity

::: corral.reports.Category

## Editing

::: corral.editing.Edit

::: corral.editing.EditResult

::: corral.editing.Session
    options:
      members:
        - add_edit
        - rollback

::: corral.editing.rollback

## Quality (generic framework)

::: corral.quality.Rule

::: corral.quality.RuleConfig

::: corral.quality.run_quality

## Operations (cost model + gating)

::: corral.operations.OperationCost

::: corral.operations.gate

::: corral.operations.ApprovalRequired

::: corral.operations.Batch

::: corral.operations.coalesce

## API server primitives

::: corral.api.build_app

::: corral.api.PackageRegistry
    options:
      members:
        - require
        - source_for
        - describe
        - list_ids

::: corral.api.ServerSettings

::: corral.api.AuthSettings

::: corral.api.ExtraRouterFactory

::: corral.api.AuthDep

::: corral.api.PackageLoader

## MCP primitives

::: corral.mcp.build_server

## See also

* [`shared/ai/index.md`](../ai/index.md) — explains the api-index.json + llms.txt artifacts.
* [corral cookbook](../cookbook/index.md)
* [Architecture](../architecture.md)
