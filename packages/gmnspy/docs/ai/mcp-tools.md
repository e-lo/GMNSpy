---
title: MCP tools reference
audience: both
kind: reference
summary: Complete reference for the seven MCP tools the gmnspy server exposes — four generic datagrove tools plus three GMNS-aware ones.
---

# MCP tools reference

## Summary

`gmnspy mcp serve` runs a stdio MCP server that exposes seven tools: four generic Frictionless-package tools inherited from `datagrove.mcp`, plus three GMNS-aware tools. Every tool is **stateless** — each call takes a `source` (path or URL) and loads the package fresh. No session, no cache, no cross-call mutation. The deferred-tools issue tracks the stateful surface (editing sessions, indexed scope ops).

All tools return JSON-shaped dicts (or lists of strings); shapes are stable inside a major version. For wiring the server into Claude Desktop or Claude Code, see [Wire the MCP server](../cookbook/serve-mcp.md).

## Tools

### `describe_package(source)`

Generic package overview. Available on any Frictionless package, not just GMNS.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `source` | string | Filesystem path or URL to a package directory / `datapackage.json` |

**Returns** — `dict`:

```json
{
  "source": "<echoed input>",
  "name": "<package name from spec>",
  "engine": "DuckDBIbisEngine",
  "table_count": 9,
  "tables": [
    {"name": "link", "rows": 214, "columns": ["link_id", "from_node_id", ...]},
    {"name": "node", "rows": 75,  "columns": ["node_id", "x_coord", ...]}
  ]
}
```

`rows` / `columns` may be `null` for an individual table if its count fails (e.g. unreadable file).

**Example**

```json
{"name": "describe_package", "arguments": {"source": "packages/gmnspy/gmnspy/fixtures/leavenworth/csv"}}
```

### `validate_package(source)`

Run the full validation pipeline (structural + schema + foreign-key + sync-state) and return the report.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `source` | string | Path or URL to the package |

**Returns** — `dict`:

```json
{
  "issues": [
    {
      "severity": "error | warning | info",
      "category": "structural | schema | fk | sync | data_quality",
      "code": "fk.missing_target",
      "message": "...",
      "table": "lane",
      "column": "link_id",
      "row": 42,
      "fix_hint": "..."
    }
  ],
  "spec_version": "0.97"
}
```

An empty `issues` list means the package is fully valid.

**Example**

```json
{"name": "validate_package", "arguments": {"source": "s3://my-bucket/regional/datapackage.json"}}
```

### `list_tables(source)`

Cheap variant of `describe_package` — returns just the sorted list of table names with no row counts. Useful as a first call when the agent doesn't know what's in a package.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `source` | string | Path or URL |

**Returns** — `list[str]`:

```json
["lane", "link", "link_tod", "node", "signal_phase", "signal_phase_mvmt", "signal_timing_plan", "use_definition", "zone"]
```

**Example**

```json
{"name": "list_tables", "arguments": {"source": "packages/gmnspy/gmnspy/fixtures/leavenworth/csv"}}
```

### `describe_network(source)`

GMNS-aware version of `describe_package`. Surfaces the GMNS-specific fields an agent typically wants up front (spec version, link/node counts) without iterating tables.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `source` | string | Path or URL to a GMNS network |

**Returns** — `dict`:

```json
{
  "source": "<echoed input>",
  "name": "leavenworth",
  "spec_version": "0.97",
  "engine": "DuckDBIbisEngine",
  "links": 214,
  "nodes": 75,
  "table_count": 9,
  "tables": ["lane", "link", "link_tod", "node", "signal_phase", ...]
}
```

`links` / `nodes` may be `null` if the network doesn't have those tables or the count fails.

**Example**

```json
{"name": "describe_network", "arguments": {"source": "packages/gmnspy/gmnspy/fixtures/leavenworth/csv"}}
```

### `quality_check(source)`

Run the GMNS data-quality rule pack (high-speed-residential, duplicate-near-nodes, sharp-angle bends, etc.).

**Parameters**

| Name | Type | Description |
|---|---|---|
| `source` | string | Path or URL to a GMNS network |

**Returns** — same `ValidationReport` shape as `validate_package`:

```json
{
  "issues": [
    {
      "severity": "warning",
      "category": "data_quality",
      "code": "quality.high_speed_residential",
      "message": "link 42: speed_limit=45 > 35 mph on residential",
      "table": "link",
      "row": 42,
      "fix_hint": "verify speed limit or reclassify"
    }
  ],
  "spec_version": "0.97"
}
```

Default-pack issues are WARNING / INFO — the GMNS spec is silent on these checks, but they catch common data-quality misses. Customise thresholds via the Python API ([Customise the data-quality rule pack](../cookbook/customise-quality.md)).

**Example**

```json
{"name": "quality_check", "arguments": {"source": "packages/gmnspy/gmnspy/fixtures/leavenworth/csv"}}
```

### `connected_components(source)`

Count weakly-connected components in the network graph. Requires the `[clean]` extra (igraph) on the server side.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `source` | string | Path or URL to a GMNS network |

**Returns** — `dict`:

```json
{
  "source": "<echoed input>",
  "component_count": 1,
  "sizes": [75]
}
```

`component_count == 1` means the network is fully connected. `sizes` is the descending list of node counts per component — `[75]` for a fully-connected 75-node network; `[60, 12, 3]` for a three-component network with the largest having 60 nodes.

**Example**

```json
{"name": "connected_components", "arguments": {"source": "packages/gmnspy/gmnspy/fixtures/leavenworth/csv"}}
```

### `scope_from_nodes(source, node_ids, path_between)`

Build a network-aware scope from a list of seed node ids and return the resulting node + link sets.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `source` | string | — | Path or URL to a GMNS network |
| `node_ids` | list[int] | — | Seed node ids |
| `path_between` | bool | `true` | If true, includes all nodes/links on shortest paths between every pair of seeds. If false, keeps only the seeds + their incident links. |

**Returns** — `dict`:

```json
{
  "source": "<echoed input>",
  "seed_node_ids": [1, 25, 50],
  "path_between": true,
  "result_node_count": 18,
  "result_link_count": 31,
  "node_ids": [1, 5, 8, 14, 25, ...],
  "link_ids": [101, 102, 105, ...]
}
```

The returned ids are sorted. For chaining (union / intersect / buffer), drop into the Python API — the MCP surface only exposes the leaf operation.

**Example**

```json
{"name": "scope_from_nodes", "arguments": {"source": "packages/gmnspy/gmnspy/fixtures/leavenworth/csv", "node_ids": [1, 25, 50], "path_between": true}}
```

## See also

* [Wire the MCP server to Claude Code / Claude Desktop](../cookbook/serve-mcp.md) — host configuration + transport details.
* [AI surface](https://e-lo.github.io/GMNSpy/datagrove/ai/) — how MCP fits with `llms.txt`, `api-index.json`, and the Claude Code Skills.
* [API reference](../reference/api.md) — the underlying Python symbols each tool wraps.
