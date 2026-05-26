---
title: API reference
audience: both
kind: reference
summary: Auto-generated symbol reference for datagrove + gmnspy. Stable anchors match the codes in ai/api-index.json.
stability: stable
---

# API reference

This page is generated from the package docstrings via [mkdocstrings](https://mkdocstrings.github.io/). Every public symbol gets a stable anchor (`#<dotted.qualname>`) that matches the entries in [`ai/api-index.json`](../ai/api-index.json).

For task-oriented intros, see the [cookbook](../cookbook/index.md). For design rationale, see [architecture](../architecture.md).

## datagrove

### Top-level

::: datagrove.dataset.Package
    options:
      members:
        - from_source
        - from_tables
        - validate
        - write
        - tables
      show_root_heading: true
      show_source: false
      heading_level: 4

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
      show_source: false
      heading_level: 4

### Reports

::: datagrove.reports.ValidationReport
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.reports.Issue
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.reports.Severity
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.reports.Category
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

### Editing

::: datagrove.editing.Edit
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.editing.EditResult
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.editing.Session
    options:
      members:
        - add_edit
        - rollback
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.editing.rollback
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

### Quality (framework)

::: datagrove.quality.Rule
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.quality.RuleConfig
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.quality.run_quality
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

### Operations (cost model + gating)

::: datagrove.operations.OperationCost
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.operations.gate
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.operations.ApprovalRequired
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.operations.Batch
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: datagrove.operations.coalesce
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

## gmnspy

### Network

::: gmnspy.Network
    options:
      members:
        - from_source
        - validate
        - links
        - nodes
        - geometry
        - lanes
        - link_tod
        - segments
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.NetworkError
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

### Spec

::: gmnspy.spec.SUPPORTED_SPECS
    options:
      show_root_heading: true
      heading_level: 4

::: gmnspy.spec.DEFAULT_SPEC
    options:
      show_root_heading: true
      heading_level: 4

::: gmnspy.spec.load_gmns_spec
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

### Semantics

::: gmnspy.semantics.is_connected
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.semantics.connected_components
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.semantics.assemble_link_geometry
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.semantics.resolve_link_attrs_at
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

### Scope

::: gmnspy.scope.NetworkScope
    options:
      members:
        - apply
        - union
        - intersect
        - subtract
        - buffer_network
        - buffer_spatial
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.scope.from_nodes
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.scope.from_node
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.scope.from_link
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.scope.from_point
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.scope.connected_component
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.scope.from_zone
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

### Indexes (optional `[clean]` extra)

::: gmnspy.indexes.GraphIndex
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.indexes.SpatialIndex
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.indexes.build_indexes
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

### Clean (optional `[clean]` extra)

::: gmnspy.clean.simplify_geometry
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.clean.merge_close_nodes
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.clean.remove_orphans
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

::: gmnspy.clean.recompute_lengths
    options:
      show_root_heading: true
      show_source: false
      heading_level: 4

## See also

* [`ai/api-index.json`](../ai/api-index.json) — same symbols, JSON-shape.
* [Cookbook](../cookbook/index.md) — task-oriented recipes that use these APIs.
* [Architecture](../architecture.md) — design rationale.
