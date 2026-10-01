# ADR — Geometry encoding: WKT on-disk-CSV, binary in-memory + GeoParquet at rest

Status: **accepted, implementing** · Date: 2026-10-01 · Owner: datagrove/gmnspy

## Context

GMNS geometry is a geometry per feature (links especially, as a `LINESTRING`). The GMNS **config**
([spec](https://zephyr-data-specs.github.io/GMNS/spec/config/)) already declares how it is encoded, via two
fields typed `any` (no enumerated values — any geopandas-readable encoding is allowed):

- **`geometry_field_format`** — the geometry encoding (example: `WKT`).
- **`crs`** — coordinate system (a pyproj-acceptable string / EPSG code).

So geometry encoding is **a config-declared, per-dataset property** — not something gmnspy should hard-code
or invent a parallel convention for. Today the code hard-codes the assumption "geometry is a WKT string in
EPSG:4326" and re-parses that WKT text (`gmnspy._wkt._parse_linestring_points`, a regex) every time it needs
coordinates — once per viewer load, once per binary-buffer pack, again for any spatial op.

## Decision

1. **Config is the source of truth.** Read `geometry_field_format` + `crs` from the GMNS config on load and
   honor them when decoding; write them when writing a store. Default `geometry_field_format=WKT`,
   `crs=EPSG:4326` when absent (back-compat with today's data).

2. **Encode per container** (matches each format's native strength):
   - **CSV / ascii store** → `WKT` (unchanged).
   - **Parquet store** → **GeoParquet** = WKB-encoded geometry column + the `geo` file metadata (geometry
     column, encoding, CRS, bbox). Not a bare WKB string column — GeoParquet is what GDAL/geopandas/QGIS/
     DuckDB read natively, and it records the CRS.

3. **Parse once, then binary everywhere (the optimization).** At CSV ingest, convert WKT → a native
   **DuckDB `GEOMETRY`** column once (`ST_GeomFromText`), lazily in the scan projection. In memory and in the
   engine, geometry is binary from then on:
   - spatial ops run on native `GEOMETRY` (pushdown; DuckDB spatial is already used by `dataset/view.py`);
   - Parquet write is `ST_AsWKB` → GeoParquet (no text re-parse);
   - the viewer reads coordinates from WKB/GeoArrow, not regex.
   `ST_AsText` is used only where something genuinely needs WKT (CSV write, a WKT-only consumer).

4. **Boundary formats:**
   - **Inside the engine:** DuckDB `GEOMETRY` (enables spatial pushdown).
   - **Arrow / `to_pandas` boundary:** **WKB bytes** (portable; geopandas `from_wkb`; ~½ the size of WKT).
   - **Viewer / transport:** **GeoArrow** (native coordinate arrays, zero-parse) — *staged for later*, since
     DuckDB↔GeoArrow support is still maturing; start by reading coords from WKB.

5. **CRS:** honor `crs` from config (default `EPSG:4326`), record it in GeoParquet, and round-trip it.
   gmnspy stays lon/lat-centric but no longer *assumes* 4326.

6. **No hard geopandas dependency.** "geopandas-readable" is the compatibility *target*; DuckDB spatial does
   the encode/decode internally (lean-deps: geopandas drags in GEOS/shapely/pyproj). We emit formats
   geopandas can read (GeoParquet, WKB, WKT) without importing it.

## Consequences

- The **logical model is unchanged** — still one geometry per feature. This is a *physical-storage* choice
  the GMNS config already sanctions, **not a fork of the GMNS geometry convention.**
- `to_pandas()` geometry changes from a WKT string to **WKB bytes** — a behavior change for any downstream
  code that expected WKT. Consumers that currently regex-parse WKT (viz buffers, `select/_geojson`,
  map/geo_resolver, semantics/geometry, indexes/spatial) migrate to read coordinates from the binary form;
  `gmnspy._wkt` stays as the no-DuckDB / pure-CSV fallback.
- Requires the **DuckDB spatial extension** at ingest — already an architectural assumption (`view.py`
  `_ensure_spatial`), so no new dependency; gate conversion on extension-available + geometry-present.
- **Round-trip guarantee:** CSV(WKT) ↔ Parquet(WKB/GeoParquet) must be geometry- and CRS-lossless (modulo
  WKT float formatting). Pinned by test.

## Rejected / deferred
- A bespoke WKB-in-a-string column (rejected: loses GeoParquet metadata + CRS + ecosystem interop).
- Frictionless field-metadata convention for encoding (rejected: GMNS config `geometry_field_format`
  supersedes it).
- GeoArrow as the in-memory representation *now* (deferred: DuckDB↔GeoArrow still maturing; WKB boundary
  first, GeoArrow for the viewer later).

## Plan (slices)
1. **Config reader** — `geometry_field_format` + `crs` from the datapackage/config, with defaults.
2. **Ingest conversion** — WKT→`GEOMETRY` at CSV scan (spatial-gated, geometry-present-gated); lazy.
3. **Parquet adapter** — write GeoParquet (WKB + `geo` meta + CRS); set config `geometry_field_format=WKB`;
   read GeoParquet back to `GEOMETRY`. CSV adapter stays WKT.
4. **Migrate geometry consumers** to the binary path (coords from WKB); keep `_wkt` fallback.
5. **Tests** — CSV↔Parquet round-trip lossless (incl. CRS); geometry parsed exactly once at ingest;
   GeoParquet readable by the generic reader.
6. **Later** — GeoArrow for the viewer's binary packer; honor non-4326 CRS end-to-end.
