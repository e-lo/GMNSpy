---
title: Glossary
audience: both
kind: reference
summary: GMNS-domain terms (link, lane, TOD, …) and project conventions (sync state, scope, EditResult, …) defined in one place.
---

# Glossary

!!! info "Stub — to be filled in Wave 4"
    This page is scaffolded. The content fill is tracked in [issue #96](https://github.com/e-lo/GMNSpy/issues/96) and follows the [Page Style Guide](../_page-style-guide.md).

## GMNS domain

**Link** — a directed (or undirected) edge in the routable network, between two nodes.

**Node** — a vertex in the routable network.

**Lane** — a sub-element of a link with its own lane number, optional turn restrictions.

**Geometry** — a row in the optional `geometry` table holding a WKT shape, referenced by `link.geometry_id`.

**TOD (time-of-day)** — per-time-period overrides on link / lane / segment / movement attributes. Keyed by `time_set_definitions.timeday_id`.

**Movement** — a turning movement at a node, from an inbound link to an outbound link.

**Zone** — a traffic analysis zone (TAZ); nodes carry an optional `zone_id`.

**Spec version** — the GMNS spec release the data conforms to. Vendored: 0.95 / 0.96 / 0.97.

## Project conventions

**Engine** — the materialisation backend (`IbisEngine` default, `PandasEngine`, `PolarsEngine`).

**Lazy expression** — a `Table.expr` that has not been materialised. Operations on a lazy expression return a new lazy expression.

**Sync state** — content-hash tracking on every table; the validator warns when a previously-validated FK has gone stale.

**Scope** — a `NetworkScope` is a (node_ids, link_ids) pair that, when applied, returns a filtered `Network`.

**Network buffer** — a Dijkstra-bounded expansion in **graph distance** (uses `link.length`).

**Spatial buffer** — a shapely-bounded expansion in **CRS units** (degrees for WGS84, meters for projected).

**EditResult** — the value returned by every `gmnspy.clean` op; carries the diff + the rollback record.

**Session** — context manager around one or more Edits with atomic rollback.

**Severity / Category / Issue** — see [API reference](api.md#datagrove.reports.Severity).

## See also

* [Table of tables](table-of-tables.md)
* [Schema reference](spec.md)
