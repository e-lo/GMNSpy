---
title: When to use ibis vs pandas vs polars
audience: both
kind: concept
summary: Engine-choice decision guide for datagrove + gmnspy. ibis (DuckDB) is the default and handles regional-scale data including geographies via the DuckDB spatial extension. Switch to pandas or polars only when ibis can't express what you need.
---

# When to use ibis vs pandas vs polars

datagrove's [architecture](../architecture.md) calls itself "ibis-first" — every default API materialises through ibis with the DuckDB backend, and predicates push down to SQL whenever they can. That's the right default for most work, but it isn't the right answer for every quality rule, every report, every analysis. This page is the decision guide.

## What it is

Three engines ship with datagrove out of the box:

* **`IbisEngine`** — the default. Wraps [ibis](https://ibis-project.org/) over [DuckDB](https://duckdb.org/). Lazy expressions; predicates compile to SQL and execute inside DuckDB; only matching rows materialise.
* **`PandasEngine`** — wraps [pandas](https://pandas.pydata.org/). Eager DataFrames; every operation materialises in Python memory.
* **`PolarsEngine`** — wraps [polars](https://pola.rs/). Lazy by default; column-oriented; fast in-memory analytics.

All three implement the same `Engine` protocol, so the package surface (`Package.from_source`, `pkg.tables[name].filter(...)`, `pkg.validate()`) is identical regardless of which one you pick. Engine choice is a per-call kwarg, not a code rewrite.

## Why we have it

Three reasons one engine isn't enough:

1. **Different deploys want different tradeoffs.** A regional-scale validation pipeline running on a laptop wants ibis + DuckDB so it doesn't load 500MB into RAM. A small in-memory analysis wants pandas because the DataFrame API is what the next 100 lines of analysis code expects. A high-throughput batch wants polars because the columnar engine is faster than ibis's round-trip overhead for in-memory work.
2. **Some operations don't fit ibis.** Pure-Python parsing (shapely geometries, regex, fuzzy strings, ML models) needs values in Python memory. ibis pushdown can shrink the materialised set, but it can't itself parse a WKT into a shapely object.
3. **Compatibility escape valves.** When the default ibis path hits an edge case (today: [#163](https://github.com/e-lo/GMNSpy/issues/163), the null-typed-column round-trip on `replace_table`), users need a one-line switch to pandas — not a code refactor.

The Engine protocol is the seam that makes all three first-class without forking the API.

## Mental model

* **Default to ibis.** If your operation expresses as a predicate (`link.toll > 0`, `node.zone_id.isin([1, 2, 3])`, `link.geometry.intersects(bbox)`) or an aggregation (`link.length.sum()`), ibis pushes it down and you get the answer in milliseconds against a 200k-link network.
* **Switch to pandas for ergonomics, not speed.** `.iloc`, `.merge` with custom suffixes, `.pivot_table`, or because the surrounding 20 lines of code are already pandas.
* **Switch to polars for in-memory speed when you need it.** Profile first; the wins are real for some shapes (group-by-heavy, large in-memory joins) but ibis's pushdown is often faster end-to-end because the data never leaves DuckDB.
* **Never materialise the whole table just to filter in Python.** If the predicate is SQL-expressible, push it down. If it's not (shapely, regex), push down what you *can* first (e.g. coarse `facility_type == 'residential'` filter), then materialise the surviving rows.

## When to use which — decision table

| Situation | Engine | Why |
|---|---|---|
| Default for `Package.from_source` / `Network.from_source` | **ibis** | Lazy; pushes predicates to DuckDB. Right answer for ~80% of work. |
| Predicate is SQL-expressible (`>`, `<`, `isin`, `like`, `is null`) | **ibis** | Pushdown is free. |
| Geometry operation expressible in DuckDB spatial (`ST_Intersects`, `ST_Buffer`, `ST_GeomFromText`) | **ibis** | DuckDB spatial extension is fast. See [Geographies in ibis](#geographies-in-ibis) below. |
| You need shapely objects in Python (custom geometry logic, multi-geometry ops, projections) | **pandas + shapely** (after ibis pre-filter) | Push the coarse filter through ibis, materialise survivors, parse shapely from WKT. |
| Working with a small table (< 1k rows) | **pandas** | Materialise cost is trivial; DataFrame ergonomics win. |
| Heavy in-memory group-by / join / pivot | **polars** | Columnar engine; benchmark to confirm vs ibis pushdown. |
| Downstream code is already pandas | **pandas** | Avoid boundary conversions. |
| Downstream code is already polars | **polars** | Same. |
| Hit IbisEngine edge case (e.g. [#163](https://github.com/e-lo/GMNSpy/issues/163)) | **pandas** | One-line escape valve. |

## Geographies in ibis

Common misconception: "ibis can't do spatial — switch to pandas + shapely." Not true. ibis exposes DuckDB's spatial extension through `@udf.scalar.builtin`. The existing `datagrove.dataset.view.from_bbox` is the canonical pattern:

The example below builds the spatial predicate as pure ibis — `ST_Intersects(ST_GeomFromText(geom_wkt), ST_MakeEnvelope(minx, miny, maxx, maxy))` — and pushes it down to DuckDB. No shapely import; no Python iteration; partitioned-parquet sources prune partitions at scan time.

```python
import ibis
import ibis.expr.datatypes as dt
from ibis import udf


@udf.scalar.builtin(name="ST_GeomFromText")
def _st_geom_from_text(wkt: str) -> dt.binary:  # type: ignore[empty-body]
    ...


@udf.scalar.builtin(name="ST_Intersects")
def _st_intersects(left: dt.binary, right: dt.binary) -> bool:  # type: ignore[empty-body]
    ...


@udf.scalar.builtin(name="ST_MakeEnvelope")
def _st_make_envelope(minx: float, miny: float, maxx: float, maxy: float) -> dt.binary:  # type: ignore[empty-body]
    ...


def from_bbox(table, minx, miny, maxx, maxy, *, geometry_column="geometry"):
    return table.filter(
        _st_intersects(
            _st_geom_from_text(table[geometry_column]),
            _st_make_envelope(minx, miny, maxx, maxy),
        )
    )
```

### What's in DuckDB spatial

Most of what a transportation / GIS analyst needs:

* **Construction** — `ST_GeomFromText` (WKT), `ST_GeomFromWKB`, `ST_Point`, `ST_MakeEnvelope`, `ST_MakeLine`.
* **Predicates** — `ST_Intersects`, `ST_Contains`, `ST_Within`, `ST_Touches`, `ST_Disjoint`.
* **Measurement** — `ST_Area`, `ST_Length`, `ST_Distance`.
* **Buffer / scope** — `ST_Buffer`, `ST_Envelope`, `ST_Centroid`.
* **Set ops** — `ST_Intersection`, `ST_Union`, `ST_Difference`.
* **Conversion** — `ST_AsText`, `ST_AsBinary`.

Full list: [DuckDB spatial extension docs](https://duckdb.org/docs/extensions/spatial/overview.html).

### When to fall back to shapely

* Geometry constructors beyond WKT (e.g. building a `MultiPolygon` from a list of rings procedurally).
* Reprojection between CRSes (`pyproj` is the right tool; DuckDB spatial doesn't reproject).
* Operations that need shapely's full geometry model (`buffer().simplify().centroid().distance(...)` chains in Python).
* Per-row Python logic that can't be expressed as a SQL UDF.

The pattern when shapely is needed: **push the coarse filter through ibis first**, then materialise only the surviving rows, then parse shapely.

<!-- doctest: skip -->
```python
# Right: push the coarse filter, then shapely the survivors.
links = pkg.tables["link"].expr.filter(
    pkg.tables["link"].expr.facility_type == "residential"
)
arrow = links.to_pyarrow()  # only residential links materialise

from shapely import from_wkt
for row in arrow.to_pylist():
    geom = from_wkt(row["geometry"])
    # ... shapely logic per row
```

<!-- doctest: skip -->
```python
# Wrong: materialise everything, filter in Python.
links_df = pkg.tables["link"].to_pandas()  # whole table in RAM
for row in links_df.itertuples():
    if row.facility_type != "residential":
        continue
    geom = from_wkt(row.geometry)
    # ...
```

## How it relates to ...

### Quality rules — the canonical ibis-pushdown pattern

The data-quality rule pack in `gmnspy.quality` runs against every link, node, lane, etc. for many checks. Rules that express their predicate in SQL should push it down; rules that need shapely (sharp-angle bends, duplicate-near nodes) should pre-filter through ibis before materialising.

The right shape for a SQL-expressible rule:

<!-- doctest: skip -->
```python
def applies_to(self, package):
    link = package.tables.get("link")
    return link is not None and "toll" in link.columns()

def run(self, package, report, config=None):
    link = package.tables["link"].expr
    # Predicate pushed to DuckDB — only matching rows come back.
    offending = link.filter(link.toll > 0).select("link_id").to_pyarrow()
    for i, row in enumerate(offending.to_pylist()):
        report.add(
            severity=self.severity,
            category=Category.DATA_QUALITY,
            code=self.code,
            message=f"link {row['link_id']} has nonzero toll",
            table="link",
            row=i,
            fix_hint="set toll=0 or remove from project scope",
        )
```

vs the wrong shape (full materialise + Python loop), which is what some of the current GMNS rule pack does and what [#181](https://github.com/e-lo/GMNSpy/issues/181) tracks the refactor for:

<!-- doctest: skip -->
```python
# Wrong:
links = net.tables["link"].to_pandas()         # whole table to RAM
for row in links[links["toll"] > 0].itertuples():  # filter + iterate in Python
    yield Issue(...)
```

For low-row-count tables (under ~1k rows: `time_set_definitions`, `use_definition`) the full-materialise cost is trivial and the pandas readability wins. Default to ibis pushdown for everything else.

### Scope operations

`datagrove.dataset.view.from_bbox` / `from_polygon` / `from_geometry_buffer` are built on top of the spatial-pushdown pattern shown above. Same model: predicate compiles to DuckDB SQL; partitioned parquet sources prune partitions at scan time; full materialisation is the exception, not the rule. (`gmnspy.scope` adds *network-aware* scopes — `from_nodes`, `from_link`, `from_point`, `connected_component`, `from_zone` — on top, see [the scope cookbook](https://e-lo.github.io/GMNSpy/gmnspy/cookbook/scope-from-nodes/).)

### Engine switching at the call site

Per-call override on every public entry point that accepts an engine:

<!-- doctest: skip -->
```python
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.engines.polars_engine import PolarsEngine

pkg = Package.from_source(path, engine=PandasEngine())
# or
pkg = Package.from_source(path, engine=PolarsEngine())
```

For CLI users: `--engine ibis|pandas|polars` is wired on every command that materialises (`convert`, `bench`, `clean.*`).

## See also

* [Architecture §6.1 — engine + I/O](../architecture.md#61-engine--io) — for the design rationale of the default ibis + DuckDB choice.
* [Frictionless data packages](frictionless.md) — the schema/data model the engines all see.
* [DuckDB spatial extension](https://duckdb.org/docs/extensions/spatial/overview.html) — full list of ST_* functions you can use from ibis.
* [ibis docs](https://ibis-project.org/) — the underlying lazy-expression framework.
* [Quality rule pack refactor (#181)](https://github.com/e-lo/GMNSpy/issues/181) — the gmnspy.quality refactor that applies this guidance to the existing rules.
