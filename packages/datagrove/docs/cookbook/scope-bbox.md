---
title: Bounding-box and polygon scope
audience: users
kind: howto
summary: Spatial scope by bbox, polygon, or geometry-buffer — works on any Frictionless package with a WKT geometry column.
---

# Bounding-box and polygon scope

## When to use this

You have a spatial filter — a bounding box from a map UI, a polygon from a planning area, or a buffered route — and want only the rows whose geometry falls inside it. Works on any geometry-bearing table; not GMNS-specific.

## Quick example

Load the bundled Leavenworth fixture, build a bbox view over the links table, and count the rows that fall inside:

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth
from datagrove.dataset.view import from_bbox

net = Network.from_source(leavenworth.csv_dir())
view = from_bbox(net.links, minx=-120.67, miny=47.58, maxx=-120.65, maxy=47.60)
print(f"{view.count()} links in bbox")
```

The view is lazy — no rows materialise until you call `.to_pandas()` or iterate.

## Step-by-step

### 1. Bounding box (any table)

`from_bbox` is generic — it works on any `Table` whose schema declares a WKT geometry column. No shapely required for bbox; the predicate is pure coordinate math:

```python
from datagrove.dataset.view import from_bbox

view = from_bbox(net.links, minx=-120.67, miny=47.58, maxx=-120.65, maxy=47.60)
df = view.to_pandas()
```

### 2. Polygon (shapely or WKT)

For non-rectangular regions, pass a shapely `Polygon`. Shapely is in the `[clean]` extra:

```python
from datagrove.dataset.view import from_polygon
from shapely.geometry import Polygon

poly = Polygon([
    (-120.67, 47.58),
    (-120.65, 47.58),
    (-120.65, 47.60),
    (-120.67, 47.60),
    (-120.67, 47.58),
])
view = from_polygon(net.links, poly)
```

If shapely isn't installed, pass a WKT string instead — the function parses it directly:

```python
view = from_polygon(net.links, "POLYGON((-120.67 47.58, -120.65 47.58, ...))")
```

### 3. Buffered geometry

Buffer a geometry (in metres, regardless of CRS — the helper reprojects) and filter to anything inside. Useful for "everything within 100 m of this corridor":

```python
from datagrove.dataset.view import from_geometry_buffer
from shapely.geometry import LineString

corridor = LineString([(-120.67, 47.58), (-120.65, 47.60)])
view = from_geometry_buffer(net.links, corridor, distance_m=100)
```

### 4. Predicate pushdown

When the underlying source is partitioned Parquet, the spatial predicate compiles to a single DuckDB `WHERE` clause. Partitions whose statistics fall entirely outside the bbox are pruned before reading. Typical speed-up on a regional network is 10–50× vs full scan:

```python
net = Network.from_source("s3://my-bucket/regional/links.parquet")
# Only the parquet partitions overlapping the bbox are read off S3.
view = from_bbox(net.links, minx=-120.67, miny=47.58, maxx=-120.65, maxy=47.60)
```

Inspect the compiled predicate via `view.explain()` — useful when debugging "why is this slow?" against an S3 source. The explain output names every partition that was kept or pruned.

### 5. Compose with other filters

Spatial views compose with the rest of the `View` API. The bbox + facility-type predicate fuse into a single SQL pass — no intermediate materialisation:

```python
inside = from_bbox(net.links, -120.67, 47.58, -120.65, 47.60)
arterials = inside.filter(net.links.facility_type == "arterial")
arterials.to_pandas()
```

## Common variations

???+ note "Default — bbox filter on a single table"
    Returns a lazy `View` over the matched rows.

    ```python
    view = from_bbox(net.links, minx, miny, maxx, maxy)
    ```

??? note "Filter the whole network with FK pushdown"
    For GMNS networks, use the gmnspy scope ops instead — they walk the FK graph and produce a fully consistent sub-network.

    ```python
    from gmnspy.scope import from_polygon
    scope = from_polygon(net, poly)
    sub = scope.apply()
    ```

??? note "WGS84 bbox against a projected source"
    `from_bbox` compares numbers; it does not reproject. Reproject the bbox to the source CRS first.

    ```python
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:4326", net.spec.crs, always_xy=True)
    minx, miny = t.transform(-120.67, 47.58)
    maxx, maxy = t.transform(-120.65, 47.60)
    view = from_bbox(net.links, minx, miny, maxx, maxy)
    ```

??? note "Buffered point (everything within 500 m of a location)"
    `from_geometry_buffer` accepts any shapely geometry — `Point`, `LineString`, `Polygon`.

    ```python
    from shapely.geometry import Point
    view = from_geometry_buffer(net.links, Point(-120.66, 47.59), distance_m=500)
    ```

## Pitfalls

* **CRS mismatch is silent.** `from_bbox` compares numbers — degrees-vs-metres mismatches produce empty results, not errors. Check `net.spec.crs` first.
* **`distance_m` only works if CRS is known.** If the source declares no CRS, `from_geometry_buffer` raises. Set `crs=` on the source, or pre-buffer in the geometry's native units and pass via `from_polygon`.
* **Shapely needed for polygon input** (not bbox). `pip install gmnspy[clean]` brings it in.
* **Single-table scope is *not* FK-aware.** If you bbox-filter `link` and want only the dependent `lane` rows too, use the network-aware scope helpers in `gmnspy.scope` (`from_nodes`, `from_link`, `connected_component`) instead — those walk the FK graph.

## See also

* [Build a scope from seed nodes](https://e-lo.github.io/GMNSpy/gmnspy/cookbook/scope-from-nodes/) — network-graph scope (vs spatial).
* [API reference](../reference/api.md) — `datagrove.dataset.view.from_bbox`, `from_polygon`, `from_geometry_buffer`.
