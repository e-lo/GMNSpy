---
title: netstead API reference
audience: both
kind: reference
summary: Every public netstead symbol, auto-generated from docstrings. Stable anchors match the codes in ai/api-index.json. For the generic corral API see the corral reference.
stability: stable
---

# netstead API reference

GMNS-specific surface. For the generic Frictionless data-package primitives (`Package`, `Table`, validation, editing framework, HTTP + MCP factories) see the [corral API reference](https://e-lo.github.io/netstead/corral/reference/api/).

Auto-generated from package docstrings via [mkdocstrings](https://mkdocstrings.github.io/). Stable anchors match the codes in [`ai/api-index.json`](https://e-lo.github.io/netstead/corral/ai/).

## Network — the GMNS-aware Package

::: netstead.Network
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

::: netstead.NetworkError

## Spec

::: netstead.spec.SUPPORTED_SPECS

::: netstead.spec.DEFAULT_SPEC

::: netstead.spec.load_gmns_spec

## Semantics

::: netstead.semantics.is_connected

::: netstead.semantics.connected_components

::: netstead.semantics.assemble_link_geometry

::: netstead.semantics.resolve_link_attrs_at

## Scope

::: netstead.scope.NetworkScope
    options:
      members:
        - apply
        - union
        - intersect
        - subtract
        - buffer_network
        - buffer_spatial

::: netstead.scope.from_nodes

::: netstead.scope.from_node

::: netstead.scope.from_link

::: netstead.scope.from_point

::: netstead.scope.connected_component

::: netstead.scope.from_zone

## Quality (GMNS rule pack)

::: netstead.quality.register_all

The 7 rule classes:

::: netstead.quality.HighSpeedResidentialRule
::: netstead.quality.DisconnectedComponentsRule
::: netstead.quality.LaneCountMismatchRule
::: netstead.quality.DuplicateNearNodesRule
::: netstead.quality.SharpAngleBendsRule
::: netstead.quality.ImplausibleVcRule
::: netstead.quality.MissingCriticalFieldsRule

## Indexes (optional `[clean]` extra)

::: netstead.indexes.SpatialIndex

::: netstead.indexes.build_indexes

## Graph / routing (optional `[graph]` extra)

::: netstead.graph.GMNSGraph

## Clean (optional `[clean]` extra)

::: netstead.clean.simplify_geometry

::: netstead.clean.merge_close_nodes

::: netstead.clean.remove_orphans

::: netstead.clean.recompute_lengths

## See also

* [corral API reference](https://e-lo.github.io/netstead/corral/reference/api/) — the generic primitives netstead is built on.
* [Schema reference](spec.md) — GMNS field-level reference.
* [Table of tables](table-of-tables.md) — "which table do I use?" entry point.
* [Glossary](glossary.md) — terms used in this API.
