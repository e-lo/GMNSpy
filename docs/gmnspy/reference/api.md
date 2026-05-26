---
title: gmnspy API reference
audience: both
kind: reference
summary: Every public gmnspy symbol, auto-generated from docstrings. Stable anchors match the codes in ai/api-index.json. For the generic datagrove API see the datagrove reference.
stability: stable
---

# gmnspy API reference

GMNS-specific surface. For the generic Frictionless data-package primitives (`Package`, `Table`, validation, editing framework, HTTP + MCP factories) see the [datagrove API reference](../../datagrove/reference/api.md).

Auto-generated from package docstrings via [mkdocstrings](https://mkdocstrings.github.io/). Stable anchors match the codes in [`ai/api-index.json`](../../shared/ai/index.md).

## Network — the GMNS-aware Package

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
        - spec_version
      show_root_heading: true

::: gmnspy.NetworkError

## Spec

::: gmnspy.spec.SUPPORTED_SPECS

::: gmnspy.spec.DEFAULT_SPEC

::: gmnspy.spec.load_gmns_spec

## Semantics

::: gmnspy.semantics.is_connected

::: gmnspy.semantics.connected_components

::: gmnspy.semantics.assemble_link_geometry

::: gmnspy.semantics.resolve_link_attrs_at

## Scope

::: gmnspy.scope.NetworkScope
    options:
      members:
        - apply
        - union
        - intersect
        - subtract
        - buffer_network
        - buffer_spatial

::: gmnspy.scope.from_nodes

::: gmnspy.scope.from_node

::: gmnspy.scope.from_link

::: gmnspy.scope.from_point

::: gmnspy.scope.connected_component

::: gmnspy.scope.from_zone

## Quality (GMNS rule pack)

::: gmnspy.quality.register_all

The 7 rule classes:

::: gmnspy.quality.HighSpeedResidentialRule
::: gmnspy.quality.DisconnectedComponentsRule
::: gmnspy.quality.LaneCountMismatchRule
::: gmnspy.quality.DuplicateNearNodesRule
::: gmnspy.quality.SharpAngleBendsRule
::: gmnspy.quality.ImplausibleVcRule
::: gmnspy.quality.MissingCriticalFieldsRule

## Indexes (optional `[clean]` extra)

::: gmnspy.indexes.GraphIndex

::: gmnspy.indexes.SpatialIndex

::: gmnspy.indexes.build_indexes

## Clean (optional `[clean]` extra)

::: gmnspy.clean.simplify_geometry

::: gmnspy.clean.merge_close_nodes

::: gmnspy.clean.remove_orphans

::: gmnspy.clean.recompute_lengths

## See also

* [datagrove API reference](../../datagrove/reference/api.md) — the generic primitives gmnspy is built on.
* [Schema reference](spec.md) — GMNS field-level reference.
* [Table of tables](table-of-tables.md) — "which table do I use?" entry point.
* [Glossary](glossary.md) — terms used in this API.
