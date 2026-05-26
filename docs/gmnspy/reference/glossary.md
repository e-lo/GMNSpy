---
title: Glossary
audience: both
kind: reference
summary: GMNS-domain terms (link, lane, TOD, segment, …) and project conventions (sync state, scope, EditResult, Skill, MCP, …) defined in one place.
---

# Glossary

## Summary

Two sections: **GMNS domain** terms come from the spec itself and apply to any GMNS toolkit. **Project conventions** are GMNSpy + datagrove specific — names that appear in the API, CLI, and docs of this toolkit. Entries are alphabetical within each section.

## GMNS domain

**Allowed uses** — the set of `use_definition` ids permitted to traverse a link or lane (e.g., `{auto, truck, transit}`). Encoded as a comma-separated list referencing `use_definition.use_id` or as a `use_group.group_id`. Distinct from `prohibited_uses`, which is the inverse expression. See [`use_definition`](table-of-tables.md#dimension-tables).

**Capacity** — the maximum hourly throughput of a link or lane under prevailing conditions, in vehicles per hour. Carried on `link.capacity` (and overridable per period via `link_tod.capacity`). Units are vehicles per hour per lane unless the producer notes otherwise; GMNS is silent on the LOS model used to compute it.

**Curb segment** — a managed length of curb (parking, loading zone, no-stopping). One row per curb segment in `curb_seg`, keyed to a `link_id`. New in recent GMNS versions; supports curb-management modeling.

**Facility type** — categorical descriptor of a link's roadway class (e.g., `motorway`, `primary`, `tertiary`, `residential`, `service`). Drives default values for capacity, free speed, and lane count when those fields are absent. The exact vocabulary is in `shared_categories.json` under `facility_type_categories`.

**Free speed** — the posted or signed speed limit, or the speed at which vehicles travel under uncongested conditions. Carried on `link.free_speed` in `link.free_speed_units` (typically `mph` or `kph`). Distinct from any modeled travel speed.

**Geometry** — a row in the optional `geometry` table holding a WKT LineString, referenced by `link.geometry_id`. When absent, the link is implicit straight-line from `from_node` to `to_node`. The geometry table exists so multiple links can share one shape (e.g., a divided highway represented as two opposing links sharing a centerline).

**GMNS** — General Modeling Network Specification. The Zephyr Foundation's open standard for routable transportation networks in tabular Frictionless Data Package form. See [What is GMNS?](../what-is-gmns.md).

**Lane** — a sub-element of a link with its own lane number, optional turn restrictions, and allowed uses. One row per travel lane per link in the `lane` table; `lane.lane_id` is keyed to `link.link_id`. A link with `lanes=3` typically has three corresponding `lane` rows.

**Link** — a directed edge in the routable network, from `from_node_id` to `to_node_id`. The required spine table; carries facility type, lanes, free speed, length, allowed uses. Undirected networks are represented by paired links (one per direction).

**Movement** — a turning movement at a node, from an inbound link to an outbound link. One row per allowed turn in the `movement` table; carries movement type (left/through/right/u-turn) and permitted uses. Used by signal-control tables to map phases to movements.

**Node** — a vertex in the routable network — intersection, dead-end, zone centroid. The required vertices table; carries x/y coordinates and optional `ctrl_type` (signal, stop, yield, no-control).

**Segment** — a sub-division of a link where attributes change mid-link (e.g., a lane drop, a facility-type change). One row per segment in the `segment` table; segments tile a link end-to-end. Used when link-level attributes are too coarse.

**Spec version** — the GMNS spec release the data conforms to. GMNSpy vendors 0.95, 0.96, and 0.97. Validation reports always include the spec version. The default is 0.97; override via `Network.from_source(path, spec_version="0.96")`.

**TOD (time-of-day)** — per-time-period overrides on link / lane / segment / movement attributes. Keyed by `timeday_id` into `time_set_definitions`. A period like `weekday_am_peak` (Mon-Fri 07:00-09:00) is defined once and referenced from every `*_tod` row that varies by that period.

**Zone** — a traffic analysis zone (TAZ) for demand modeling. Nodes carry an optional `zone_id`. The `zone` table holds polygon or centroid geometry; not every network has zones (routing-only networks often don't).

## Project conventions

**ApprovalRequired** — exception raised when a gated operation's cost estimate exceeds the approval threshold (default 180 seconds) and the caller has not set `approve=True`. See the cost-model section of [Architecture](../../shared/architecture.md#65-pooled-operations-cost-model).

**Auto-build threshold** — the network size (in nodes) above which `gmnspy.scope` ops silently build the spatial + graph indexes on first call. Default 50,000 nodes. Configurable via the `GMNSPY_AUTO_INDEX_THRESHOLD` environment variable. Pre-build explicitly with `net.build_indexes(graph=True, spatial=True)` to control timing.

**DATAGROVE_AUTO_APPROVE** — environment variable (`DATAGROVE_AUTO_APPROVE=1`) that bypasses the cost-model approval prompt for gated operations. Equivalent to CLI `--yes` or programmatic `approve=True`. Intended for batch / CI use.

**EditResult** — the value returned by every `gmnspy.clean` op. Carries the diff per affected table, the log entry for the operation, and a `_repr_html_` visual summary for notebook rendering. Integrated with `datagrove.editing.Session` for rollback.

**Engine** — the materialisation backend. `IbisEngine` is default (lazy expressions over DuckDB); `PandasEngine` and `PolarsEngine` are alternatives. Per-call override: `Network.from_source(path, engine=PandasEngine())`. See the engine ABC at `datagrove.engines`.

**GMNSPY_AUTO_INDEX_THRESHOLD** — see *Auto-build threshold*.

**Lazy expression** — a `Table.expr` that has not been materialised. Operations on a lazy expression return a new lazy expression. Materialisation happens explicitly via `.to_pandas()`, `.to_polars()`, `.collect()`, `.head()`, or `.count()`.

**MCP (Model Context Protocol)** — the open protocol Claude and other AI agents use to discover and call tools. GMNSpy ships an MCP server via `pip install 'gmnspy[mcp]'`; start it with `gmnspy mcp serve`. Tools exposed: `read_network`, `describe_network`, `query_table`, `scope`, `validate`, `quality_check`, `convert`, `edit_session`. See [Architecture §6.9](../../shared/architecture.md#69-ai-accessibility).

**Network buffer** — a Dijkstra-bounded expansion in **graph distance** (using `link.length`). Used by `gmnspy.scope.from_node(id, network_buffer="200m")`. Distinct from spatial buffer.

**OutOfSyncWarning** — warning raised before `write()` or `validate(strict=True)` when any tracked foreign-key's source or target table hash has changed since the last validation. Indicates the in-memory FK graph may no longer match the data. Promote to an error with `strict=True`.

**Scope** — a `NetworkScope` is a (node_ids, link_ids) pair that, when applied via `.apply()`, returns a filtered `Network` with every other table pre-filtered by FK chain. Scopes are composable and chainable: `net.scope.from_nodes([1,2,3]).buffer_network("0.5mi").buffer_spatial(30)`. See [Architecture §6.2](../../shared/architecture.md#62-memory-efficient-scoping).

**Session** — context manager around one or more `EditResult`s with atomic rollback. Open with `with Session(net) as s: ...`; rollback with `s.rollback()` or `s.rollback(to=session_id_or_timestamp)`. Audit log persists with the network as a sidecar `_history.parquet`.

**Severity / Category / Issue** — see [API reference](api.md#datagrove.reports.Severity). `Severity` is one of `Error`, `Warning`, `Info`, `DataQuality`. `Category` discriminates rule families. `Issue` is the per-finding record carried in a `ValidationReport`.

**Skill (Claude Code Skill)** — a packaged set of instructions and prompts a Claude Code agent can load on demand. GMNSpy ships several (`gmns-author`, `gmns-validate`, `gmns-convert`, `gmns-clean`, `datagrove-validate`) under `skills/` in the repo. Install with `claude code skill add <git-url>#path=skills/<name>`. See [Architecture §6.9](../../shared/architecture.md#69-ai-accessibility).

**Spatial buffer** — a shapely-bounded expansion in **CRS units** (degrees for WGS84, meters for projected CRSs). Used by `gmnspy.scope.from_link(id, spatial_buffer_m=...)` and the `buffer_spatial()` chain method. Distinct from network buffer.

**Sync state** — content-hash tracking on every table via `DirtyTracker` (in `datagrove.validation.sync_state`). Records source + target hashes per FK at validation time so the validator can detect when a previously-checked FK has gone stale. Direct DataFrame mutations bypass the tracker — call `net.invalidate("link")` to force.

## See also

* [Table of tables](table-of-tables.md) — catalog of every GMNS resource referenced above.
* [Schema reference](spec.md) — field-level reference for the vendored spec.
* [Architecture](../../shared/architecture.md) — design rationale for the project-convention terms.
