---
title: Build a scope from seed nodes
audience: users
kind: howto
summary: Network-aware scope from a list of node ids — BFS path-between, FK pushdown, chainable set ops.
---

# Build a scope from seed nodes

## When to use this

You have a list of node ids (e.g. study-area boundary nodes, signalised intersections, a corridor's endpoints) and want the subgraph that connects them — every link on a shortest path, every dependent `lane` / `link_tod` / `signal_*` row, with foreign keys pre-filtered.

## Quick example

Build a scope from three seed nodes. With `path_between=True` (the default), BFS shortest paths between every pair of seeds determine what's included; `.apply()` materialises the result as a normal `Network`:

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth
from gmnspy.scope import from_nodes

net = Network.from_source(leavenworth.csv_dir())
sub = from_nodes(net, [1, 25, 50], path_between=True).apply()
print(f"scoped: {sub.links.count()} links, {sub.nodes.count()} nodes")
```

![Scoped Leavenworth subnetwork rendered on a folium map](../../assets/screenshots/leavenworth-scoped-map.png){ .screenshot }
*The scope from seed nodes 1, 25, and 50. Shortest paths between the seeds determine which interior links are kept; every dependent `lane`, `link_tod`, and signal row is FK-filtered automatically.*

## Step-by-step

### 1. Install the `[clean]` extra

`from_nodes` walks the network graph via igraph; that's in the `[clean]` extra. Without it you get an `ImportError` pointing at the missing dependency:

```bash
pip install 'gmnspy[clean]'
```

### 2. Decide `path_between=True` vs `False`

* `path_between=True` (default) — runs BFS shortest paths between every pair of seed nodes and includes all nodes + links on those paths. Gives you the *connected subgraph* containing the seeds.
* `path_between=False` — keeps just the seed nodes and their incident links. Useful when the seeds already describe a closed region and you don't want extra interior links.

### 3. Build the scope (lazy)

A `Scope` is a description of *which rows* belong to the subset, not the subset itself. `scope.provenance` records how it was built (operation, seeds, parameters) for audit / debugging:

```python
scope = from_nodes(net, [1, 25, 50], path_between=True)

print(f"nodes in scope:    {len(scope.node_ids)}")
print(f"links in scope:    {len(scope.link_ids)}")
print(f"provenance reason: {scope.provenance.reason}")
```

### 4. Apply to materialise a sub-network

`.apply()` returns a normal `Network` you can validate, run quality checks on, or write out. Every table is pre-filtered by FK chain — lane rows whose `link_id` isn't in scope are dropped, signal phases for missing signals are dropped, etc.:

```python
sub = scope.apply()
# Every table is pre-filtered by FK chain:
#   link             — only links in scope.link_ids
#   node             — only nodes in scope.node_ids
#   lane             — only lanes whose link_id ∈ scope.link_ids
#   link_tod         — same FK pushdown
#   signal_phase     — only phases for surviving signals
#   ...
```

### 5. Chain with set ops + buffers

Scopes compose with union / intersect / subtract and with network / spatial buffering. Build a corridor scope, union with a downtown scope, then add a half-mile network buffer in one expression:

```python
from gmnspy.scope import from_nodes, from_point

corridor = from_nodes(net, [1, 25, 50])
downtown = from_point(net, lon=-120.66, lat=47.59, spatial_buffer="500m")

combined = corridor.union(downtown).buffer_network("0.5mi")
# .intersect(other), .subtract(other), .buffer_spatial(metres) also available
sub = combined.apply()
```

### 6. CLI equivalent

The same operation runs from the shell. Add `--json` to any `gmnspy` (or `datagrove`) CLI command and the output becomes a single machine-readable JSON document on stdout — pipe into `jq`, save to a file, feed to a script or AI agent. Default output is human-readable rich panels:

```bash
gmnspy scope from-nodes packages/gmnspy/gmnspy/fixtures/leavenworth/csv 1 25 50 --json
```

Expected:

```json
{
  "operation": "from_nodes",
  "seed_node_ids": [1, 25, 50],
  "result_node_count": 18,
  "result_link_count": 31,
  ...
}
```

## Common variations

???+ note "Default — multi-node BFS with path_between"
    Most common pattern: a handful of seed ids, paths between them filled in automatically.

    ```python
    sub = from_nodes(net, [1, 25, 50], path_between=True).apply()
    ```

??? note "Single seed with a network-distance buffer"
    Expands outward from one node along network edges up to a budget.

    ```python
    from gmnspy.scope import from_node
    sub = from_node(net, 1, network_buffer="200m").apply()
    ```

??? note "Single link with a spatial buffer"
    Useful for corridor studies. Accepts either spatial (meters) or network (graph-distance) buffer.

    ```python
    from gmnspy.scope import from_link
    sub = from_link(net, 42, spatial_buffer="100m").apply()
    ```

??? note "Lat/lon point with auto-snapping"
    Snaps to the nearest link and buffers from there.

    ```python
    from gmnspy.scope import from_point
    sub = from_point(net, lon=-120.66, lat=47.59, spatial_buffer="500m").apply()
    ```

??? note "Whole connected component"
    Drops everything not reachable from the seed via the graph.

    ```python
    from gmnspy.scope import connected_component
    sub = connected_component(net, seed_node_id=1).apply()
    ```

??? note "A pre-defined zone polygon"
    Pulls geometry from the `zone` table and scopes by polygon.

    ```python
    from gmnspy.scope import from_zone
    sub = from_zone(net, zone_id=12).apply()
    ```

## Pitfalls

* **Auto-build threshold.** On networks > 50k nodes the first scope call silently builds the igraph adjacency, which can take a few seconds. Pre-build with `net.build_indexes(graph=True)` to control timing, or raise the bar with `GMNSPY_AUTO_INDEX_THRESHOLD=200000`.
* **`igraph` is in `[clean]`.** A pure `pip install gmnspy` won't import — you'll see `ImportError: gmnspy.scope requires the [clean] extra`.
* **`path_between=True` is O(seeds²)** in BFS calls. For 100s of seeds, prefer a region scope (`from_zone`, `from_polygon`) or build the graph index first.

## See also

* [Bounding-box and polygon scope](../../datagrove/cookbook/scope-bbox.md) — generic spatial scope on any package.
* [API reference](../reference/api.md) — `gmnspy.scope.from_nodes`, `Scope.apply`, `Scope.union`, ...
