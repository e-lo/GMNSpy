---
title: Build a GMNS network from OpenStreetMap
audience: users
kind: howto
summary: gmnspy build (or gmnspy.osm.build_network_from_osm) turns an OSM area into a validated GMNS node + link network.
---

# Build a GMNS network from OpenStreetMap

## When to use this

You need a GMNS network for a study area and don't have one yet. Point `gmnspy` at a place name, a bounding box, or a lat/lon + buffer and it fetches the OpenStreetMap road network and writes a validated GMNS `node` + `link` package — no `osmnx` or `osm2gmns` required.

Requires the optional extra: `pip install 'gmnspy[osm]'`.

## Quick example

Build the drivable network for a place and write it as CSV. The area is geocoded via Nominatim, the road network is fetched from Overpass, and the result is a GMNS package on disk:

```bash
gmnspy build --place "Leavenworth, WA" --network-type drive --source osm --format csv ./leavenworth-osm
```

The command prints a summary (`nodes`, `links`, `spec_version`); add `--json` for a machine-readable document.

## Step-by-step

### 1. Install the extra

```bash
pip install 'gmnspy[osm]'
```

### 2. Pick how you specify the area

One of three, mutually exclusive:

```bash
# A place name (city / county / neighborhood) — geocoded to a boundary polygon.
gmnspy build --place "Leavenworth, WA" ./net

# A bounding box: west,south,east,north (EPSG:4326).
gmnspy build --bbox -120.67,47.58,-120.64,47.61 ./net

# A point (lat,lon) plus a buffer in metres.
gmnspy build --point 47.596,-120.66 --buffer 800 ./net
```

### 3. Choose modes and output format

`--network-type` is one of `drive` / `walk` / `bike` / `all`. The output format is inferred from the destination extension, or set it explicitly with `--format` (`csv` / `parquet` / `duckdb` / `zip`):

```bash
gmnspy build --place "Leavenworth, WA" --network-type bike --format parquet ./bike-net
```

### 4. Validate what you built

The build already produces a schema-valid package; run `gmnspy validate` any time to confirm and to see the report:

```bash
gmnspy validate ./leavenworth-osm
```

## Python API

Programmatic equivalent — `gmnspy.osm.build_network_from_osm` returns a `Network` (a `datagrove` package) you can validate, scope, or write:

<!-- doctest: skip -->
```python
from gmnspy.osm import build_network_from_osm

net = build_network_from_osm("Leavenworth, WA", network_type="drive")
print(net.links.count(), net.nodes.count())
net.write("leavenworth-osm", format="csv", overwrite=True)
```

If you already have node/link records (e.g. from your own fetch, or to benchmark the build path without the network), assemble a `Network` directly with `gmnspy.osm.network_from_records`:

```python
from gmnspy.osm import network_from_records

nodes = [
    {"node_id": 1, "x_coord": -120.66, "y_coord": 47.60},
    {"node_id": 2, "x_coord": -120.65, "y_coord": 47.60},
]
links = [
    {"link_id": 1, "from_node_id": 1, "to_node_id": 2, "directed": True,
     "facility_type": "residential", "geometry": "LINESTRING (-120.66 47.6, -120.65 47.6)"},
    {"link_id": 2, "from_node_id": 2, "to_node_id": 1, "directed": True,
     "facility_type": "residential", "geometry": "LINESTRING (-120.65 47.6, -120.66 47.6)"},
]
net = network_from_records(nodes, links)
print(net.links.count())
```

## How the conversion works

* **Topology.** A GMNS node is created at every OSM intersection (a node shared by two or more ways) and at each way's endpoints. Intermediate shape points are dropped as nodes and kept as the link's WKT geometry; their OSM ids are retained on the link's `osm_node_ids` column for provenance, alongside `osm_way_id`.
* **Direction.** Every link is `directed=True`. A two-way street becomes **two** directed links (one per direction); a oneway street becomes one, honoring `oneway=-1` and implied-oneway (motorways, roundabouts).
* **Attributes.** `name`, `lanes`, `free_speed`, and `facility_type` are mapped from OSM tags via the maintained data file `gmnspy/osm/mappings/osm_to_gmns.yaml`. Pass `--extra-tags surface,bridge` (or `extra_tags=[...]`) to carry additional OSM tags through as extra columns. Edit the YAML to change or extend the mapping — no code change needed.

## Common variations

???+ note "Point + buffer"
    A circle of road around a coordinate (metres).

    ```bash
    gmnspy build --point 47.596,-120.66 --buffer 800 ./net
    ```

??? note "Carry extra OSM tags"
    Add columns to the link table verbatim.

    ```bash
    gmnspy build --bbox -120.67,47.58,-120.64,47.61 --extra-tags surface,bridge ./net
    ```

??? note "Pick the engine"
    The build runs on `ibis` (default), `pandas`, or `polars`.

    ```bash
    gmnspy build --place "Leavenworth, WA" --engine polars ./net
    ```

??? note "Benchmark the build across engines"
    The `scripts/bench_osm_build.py` harness times the convert + build path per engine.

    ```bash
    uv run python scripts/bench_osm_build.py --grids 10,40,120 --json
    ```

## Pitfalls

* **Units.** GMNS is unit-agnostic — units are declared per-dataset, so the build writes a `config` table stating them: `free_speed` is **mph** (faithful to US OSM `maxspeed` tags; unit-less values are treated as km/h and converted), `length` is geodesic **metres**, `crs` is `EPSG:4326`. Re-unit downstream if your convention differs.
* **Overpass limits.** The public Overpass endpoint rate-limits and times out on large areas. For regional extracts (e.g. a metro), point at a self-hosted endpoint (`endpoint=` in the Python API) rather than hammering the public server.
* **Nominatim policy.** Place-name geocoding uses the public Nominatim, which is not for bulk/automated use. Prefer `--bbox` for scripted/repeated runs.
* **Attribution.** OSM data is ODbL-licensed — attribute OpenStreetMap in anything you publish from these networks.
* **`gmnspy[osm]` required.** Without the extra the command exits with an install hint.

## See also

* [Run validation and read the report](validate-network.md) — interpret the report from `gmnspy validate`.
* [Run the bundled benchmarks](run-bench.md) — `gmnspy bench` for load/validate timings on an existing network.
