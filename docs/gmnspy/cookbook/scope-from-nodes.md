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

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth
from gmnspy.scope import from_nodes

net = Network.from_source(leavenworth.csv_dir())
sub = from_nodes(net, [1, 25, 50], path_between=True).apply()
print(f"scoped: {sub.links.count()} links, {sub.nodes.count()} nodes")
```

## Step-by-step

### 1. Install the `[clean]` extra

```text
$ pip install 'gmnspy[clean]'
```

`from_nodes` walks the network graph via igraph; that's in the `[clean]` extra. Without it you get an `ImportError` pointing at the missing dependency.

### 2. Decide `path_between=True` vs `False`

* `path_between=True` (default) — runs BFS shortest paths between every pair of seed nodes and includes all nodes + links on those paths. Gives you the *connected subgraph* containing the seeds.
* `path_between=False` — keeps just the seed nodes and their incident links. Useful when the seeds already describe a closed region and you don't want extra interior links.

### 3. Build the scope (lazy)

```python
scope = from_nodes(net, [1, 25, 50], path_between=True)

print(f"nodes in scope:    {len(scope.node_ids)}")
print(f"links in scope:    {len(scope.link_ids)}")
print(f"provenance reason: {scope.provenance.reason}")
```

A `Scope` is a description of *which rows* belong to the subset, not the subset itself. `scope.provenance` records how it was built (operation, seeds, parameters) for audit / debugging.

### 4. Apply to materialise a sub-network

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

`sub` is a normal `Network` — validate it, run quality checks, write it out.

### 5. Chain with set ops + buffers

Scopes compose:

```python
from gmnspy.scope import from_nodes, from_point

corridor = from_nodes(net, [1, 25, 50])
downtown = from_point(net, lon=-120.66, lat=47.59, spatial_buffer="500m")

combined = corridor.union(downtown).buffer_network("0.5mi")
# .intersect(other), .subtract(other), .buffer_spatial(metres) also available
sub = combined.apply()
```

### 6. CLI equivalent

```text
$ gmnspy scope from-nodes packages/gmnspy/gmnspy/fixtures/leavenworth/csv 1 25 50 --json
{
  "operation": "from_nodes",
  "seed_node_ids": [1, 25, 50],
  "result_node_count": 18,
  "result_link_count": 31,
  ...
}
```

## Common variations

| You have... | Use |
|---|---|
| A single seed + max distance | `from_node(net, 1, network_buffer="200m")` |
| One link + buffer | `from_link(net, 42, spatial_buffer="100m")` (or `network_buffer=`) |
| A lon/lat point | `from_point(net, lon, lat, spatial_buffer="500m")` (snaps to nearest link) |
| A whole connected component | `connected_component(net, seed_node_id=1)` |
| A zone polygon | `from_zone(net, zone_id=12)` |

## Pitfalls

* **Auto-build threshold.** On networks > 50k nodes the first scope call silently builds the igraph adjacency, which can take a few seconds. Pre-build with `net.build_indexes(graph=True)` to control timing, or raise the bar with `GMNSPY_AUTO_INDEX_THRESHOLD=200000`.
* **`igraph` is in `[clean]`.** A pure `pip install gmnspy` won't import — you'll see `ImportError: gmnspy.scope requires the [clean] extra`.
* **`path_between=True` is O(seeds²)** in BFS calls. For 100s of seeds, prefer a region scope (`from_zone`, `from_polygon`) or build the graph index first.

## See also

* [Bounding-box and polygon scope](../../datagrove/cookbook/scope-bbox.md) — generic spatial scope on any package.
* [API reference](../reference/api.md) — `gmnspy.scope.from_nodes`, `Scope.apply`, `Scope.union`, ...
