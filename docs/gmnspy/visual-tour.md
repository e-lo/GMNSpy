---
title: Visual tour
audience: users
kind: tutorial
summary: Walk through the bundled Leavenworth fixture end-to-end — map, validation report, quality report, simplify-geometry diff, scope visualisation — all in one notebook session.
---

# Visual tour

## What you'll see

You'll work through the bundled Leavenworth, WA network from one notebook and produce, in order:

1. A folium / matplotlib map of the full network.
2. A validation report rendered as an HTML card.
3. A data-quality report grouped by severity.
4. A simplify-geometry edit, rendered as a before/after diff (then rolled back).
5. A scoped subgraph around a single node, rendered as a second map next to the first.

Total runtime: under two minutes on a laptop. The fixture is ~5 MB and ships inside the gmnspy wheel.

## Prerequisites

```shell-session
$ pip install 'gmnspy[clean,notebook]'
```

The `[clean]` extra brings in `shapely` + `igraph` for the geometry simplification and scope operations. The `[notebook]` extra brings in `ipywidgets` so the `_repr_html_` cards render in classic Jupyter as well as JupyterLab.

For the map step, `folium` is recommended but optional. Either of these works:

```shell-session
$ pip install folium       # interactive Leaflet map
$ pip install matplotlib   # static fallback
```

The steps below show both paths.

## Steps

### 1. Load the fixture

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth

net = Network.from_source(leavenworth.csv_dir())
print(f"{net.spec_version}: {net.links.count()} links, {net.nodes.count()} nodes")
```

You should see:

```text
0.97: 214 links, 75 nodes
```

The fixture is loaded lazily through the default ibis + duckdb engine. Nothing has been materialised yet — `net.links` is still an ibis expression.

### 2. Render the network as a map

The `link` table is keyed to `geometry` by `geometry_id`; the `geometry.geometry` column carries the WKT LineString per link. To plot, materialise both:

```python
import pandas as pd
from shapely import wkt

links = net.links.to_pandas()
geoms = net.tables["geometry"].to_pandas().set_index("geometry_id")
links = links.join(geoms[["geometry"]], on="geometry_id")
links["shape"] = links["geometry"].map(wkt.loads)
```

With folium (interactive):

```python
import folium

# Centroid of the network — average node y/x
nodes = net.nodes.to_pandas()
center = [nodes["y_coord"].mean(), nodes["x_coord"].mean()]

m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron")
for shape in links["shape"]:
    coords = [(y, x) for x, y in shape.coords]  # folium wants (lat, lon)
    folium.PolyLine(coords, color="#1f77b4", weight=2, opacity=0.8).add_to(m)
m  # in a notebook, this renders the map inline
```

You should see the downtown Leavenworth grid — a compact, walkable core wrapped around Highway 2 / Front Street, surrounded by a few residential tertiary streets.

Without folium (static fallback):

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(8, 8))
for shape in links["shape"]:
    xs, ys = shape.xy
    ax.plot(xs, ys, color="#1f77b4", linewidth=1.0, alpha=0.8)
ax.set_aspect("equal")
ax.set_title(f"Leavenworth GMNS fixture — {len(links)} links")
plt.show()
```

Either way: a recognisable Bavarian-themed downtown core in roughly 600 m of OSM-derived street network.

### 3. Validate + display the report

```python
report = net.validate()
report  # in a notebook, the _repr_html_ renders a styled card
```

You should see a green header ("0 errors") with a summary of the four passes the validator runs — structural (all required tables present), schema (field types + constraints), foreign-key (cross-table integrity), and sync-state (have any FKs gone stale since the last edit?). The Leavenworth fixture is clean by construction.

In a non-notebook context:

```python
print(f"{report.spec_version}: {len(report.issues)} issues")
for issue in report.issues[:5]:
    print(f"  {issue.severity.value:9} {issue.code:30} {issue.message[:60]}")
```

### 4. Run quality + display

The data-quality pack flags things the spec is silent on but every real network has — disconnected components, lane-count mismatches, high speeds on residential facilities, near-duplicate nodes.

```python
from datagrove.quality import run_quality

qreport = run_quality(net)
qreport  # _repr_html_ renders severity-grouped findings
```

You should see a card with WARNING / INFO findings (no ERRORs). Leavenworth's tertiary streets carry posted speeds in the 25-30 mph range with `facility_type=residential`, which triggers `quality.high_speed_residential` if you've configured a low threshold — useful for seeing what a real finding looks like.

To see one in detail:

```python
for issue in qreport.issues[:3]:
    print(f"  {issue.severity.value:9} {issue.code:35} {issue.message}")
```

### 5. Simplify geometry + render before/after

The `simplify_geometry` op in `gmnspy.clean` removes redundant vertices from link geometries. Wrap it in a `Session` so you can roll back:

```python
from datagrove.editing import Session
from gmnspy.clean import simplify_geometry

with Session(net) as s:
    edit = simplify_geometry(net, s, mode="redundant_only", tolerance=1.0)
    edit  # in a notebook, _repr_html_ shows the diff (vertices removed per link)
```

You should see a diff card listing the number of vertices removed per affected link. `mode="redundant_only"` removes only colinear vertices and is loss-free; `mode="douglas_peucker"` is the lossy alternative with an explicit tolerance.

To visualise before/after, snapshot the geometry before opening the session and overlay both on one map:

```python
links_before = links[["link_id", "shape"]].copy()
# (run the simplify edit above inside the Session)
links_after_geoms = net.tables["geometry"].to_pandas().set_index("geometry_id")
links_after = links.copy()
links_after["shape"] = links_after["geometry_id"].map(
    lambda gid: wkt.loads(links_after_geoms.loc[gid, "geometry"])
)

m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron")
for shape in links_before["shape"]:
    folium.PolyLine([(y, x) for x, y in shape.coords],
                    color="#888", weight=4, opacity=0.4).add_to(m)
for shape in links_after["shape"]:
    folium.PolyLine([(y, x) for x, y in shape.coords],
                    color="#d62728", weight=1.5, opacity=0.9).add_to(m)
m
```

Grey underneath = before; red on top = after. On Leavenworth most links don't change (the OSM source is already minimal), but a handful of curved tertiary links visibly simplify.

To restore the original state:

```python
s.rollback()
```

The session's chronological log reverses every edit atomically — the network returns to byte-identical to step 1.

### 6. Build a scope from a single node and render

```python
from gmnspy.scope import from_node

scoped = from_node(net, node_id=1, network_buffer="200m").apply()
print(f"scoped: {scoped.links.count()} links, {scoped.nodes.count()} nodes")
```

That's a 200 m **network-distance** (Dijkstra-bounded) buffer around node 1, with every other table — `lane`, `link_tod`, `movement`, etc. — pre-filtered by FK chain.

Render it side-by-side with the original:

```python
scoped_links = scoped.links.to_pandas().join(geoms[["geometry"]], on="geometry_id")
scoped_links["shape"] = scoped_links["geometry"].map(wkt.loads)

m = folium.Map(location=center, zoom_start=15, tiles="cartodbpositron")
# Full network, faint
for shape in links["shape"]:
    folium.PolyLine([(y, x) for x, y in shape.coords],
                    color="#bbb", weight=1, opacity=0.5).add_to(m)
# Scope, highlighted
for shape in scoped_links["shape"]:
    folium.PolyLine([(y, x) for x, y in shape.coords],
                    color="#2ca02c", weight=3, opacity=0.95).add_to(m)
m
```

You should see a small green subgraph centred on one intersection, with the rest of the network greyed out as context. The scope respects the routable graph — links reachable only via long detours fall outside the 200 m buffer even if they're spatially close.

## Next steps

* [Cookbook](cookbook/index.md) — task-oriented recipes for any of the workflows above.
* [API reference](reference/api.md) — every symbol you used in this tour.
* [Architecture](../shared/architecture.md) — design rationale for sessions, scopes, and the lazy-by-default engine.
* [Table of tables](reference/table-of-tables.md) — what other GMNS tables you can pull from `net.tables[...]`.
