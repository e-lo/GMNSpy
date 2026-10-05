# Overture Maps → GMNS network pipeline — scoping doc

Status: design only (no code). Author: design pass, 2026-09-30.

Adds an **Overture Maps** transportation source to netstead alongside the existing
OpenStreetMap (Overpass) source, exposing a `build_network_from_overture(...)`
entry point whose signature mirrors `build_network_from_osm(...)` as closely as
the data model allows, so users can swap sources with minimal friction.

Mirrors the existing OSM pipeline shape:
`netstead/osm/{build,query,convert,tags}.py` + maintained YAML under
`netstead/osm/mappings/`.

---

## 1. Background — what Overture transportation is

Overture publishes a **transportation theme** built from OpenStreetMap plus TomTom
and other authoritative sources, distributed as **GeoParquet**, on a roughly
monthly release cadence (date-versioned, e.g. `2026-09-23.1`). The theme has just
two feature types:

- **`segment`** — a LineString path (road / rail / water). Carries all the rich
  attribution (class, names, routes, speed limits, lanes, access rules, flags).
- **`connector`** — a Point marking where two or more segments physically connect
  (an intersection, or a future connection point). Connectors carry **no
  attributes** beyond geometry + standard Overture feature props.

The crucial routing-topology mechanism: each segment has a **`connectors[]`**
array of `{connector_id, at}` entries, where `at` is a **normalized linear
reference** in `[0,1]` along the segment. Two segments are connected **iff they
share a referenced connector id** — geometric overlap alone does **not** imply
connection. Every segment has at least two connectors (one at each end, `at=0`
and `at=1`) and may have interior connectors (`0 < at < 1`).

Sources: [Transportation guide](https://docs.overturemaps.org/guides/transportation/),
[Segments and connectors](https://docs.overturemaps.org/guides/transportation/segments-and-connectors/),
[Segment schema reference](https://docs.overturemaps.org/schema/reference/transportation/segment/),
[Roads guide](https://docs.overturemaps.org/guides/transportation/roads/),
[Scoping rules & travel modes](https://docs.overturemaps.org/guides/transportation/scoping-and-travel-modes/),
[Getting data](https://docs.overturemaps.org/getting-data/).

### 1.1 How this maps to GMNS (the key insight)

| Overture | GMNS | Notes |
|---|---|---|
| `connector` (Point) | **`node`** | Connector id → `node_id`; point geom → `x_coord`/`y_coord`. Nodes are **given**, not synthesized. |
| `segment` (LineString) between two consecutive connectors | **`link`** (directed, per travel direction) | A segment with interior connectors is **split** at each connector into multiple links — same split logic as the OSM converter, but the split points are explicit rather than inferred. |
| segment `class` / `subclass` | `link.facility_type` | Via maintained YAML mapping. |
| segment `names.primary` | `link.name` | |
| segment `routes[].ref` | `link.name` extra / route column | Route numbers (I-40, US-1). |
| segment `speed_limits[].max_speed` | `link.free_speed` | Value+unit parsed → mph (config unit). |
| segment lane count (from `road_flags`/lane rules) | `link.lanes` | See §5.5 — lanes are less first-class than in OSM. |
| segment `access_restrictions[]` + `prohibited_transitions[]` | `link.allowed_uses`, direction, and (future) GMNS `movement` turn restrictions | |
| **scoped attributes** (`between: [s,e]` sub-ranges) | GMNS **`segment` / `segment_lane` tables** | Overture's line-referenced sub-ranges map naturally onto GMNS's own segment concept (a sub-range of a link). Phase 2+. |

The single most important structural win: **Overture gives us topology for free.**
The OSM converter has to *infer* which shape points are intersections (`_kept_nodes`
counts how many ways share a node). Overture states it explicitly via shared
connector ids, so node identity and connectivity are authoritative, not heuristic.

---

## 2. Recommended data-access method

**Recommendation: DuckDB reading GeoParquet directly from S3 with bbox pushdown,
as the default; keep it engine-consistent with netstead's duckdb/parquet-first
ethos and hand-roll the thin query wrapper (no heavy new dep).**

Overture GeoParquet carries a top-level **`bbox` struct** (`bbox.xmin/xmax/ymin/ymax`)
on every row and is **hive-partitioned** by `theme=` / `type=`. DuckDB with the
`spatial` + `httpfs` extensions can push a bbox filter down to row-group level and
transfer only the matching data over the wire — no full-planet download.

Sketch of the core read (transportation theme, both types):

```sql
INSTALL spatial; LOAD spatial;
INSTALL httpfs; LOAD httpfs;
SET s3_region = 'us-west-2';

-- segments in bbox
SELECT id, subtype, class, subclass, names, routes,
       speed_limits, access_restrictions, road_flags, connectors,
       ST_AsText(geometry) AS wkt
FROM read_parquet(
  's3://overturemaps-us-west-2/release/2026-09-23.1/theme=transportation/type=segment/*',
  hive_partitioning = 1)
WHERE bbox.xmin BETWEEN :west AND :east
  AND bbox.ymin BETWEEN :south AND :north
  AND subtype = 'road';

-- connectors in bbox (same predicate)
SELECT id, ST_X(geometry) AS x, ST_Y(geometry) AS y
FROM read_parquet(
  's3://overturemaps-us-west-2/release/2026-09-23.1/theme=transportation/type=connector/*',
  hive_partitioning = 1)
WHERE bbox.xmin BETWEEN :west AND :east
  AND bbox.ymin BETWEEN :south AND :north;
```

Why this over the alternatives:

| Option | Verdict |
|---|---|
| **DuckDB + `read_parquet` over S3 (bbox pushdown)** | ✅ **Chosen default.** DuckDB is already netstead's default engine; no new heavy dep (duckdb + its spatial/httpfs extensions). Full control over the exact columns/predicate. Bbox pushdown = only pay for the area. Same engine that later validates/stores the network. |
| `overturemaps-py` CLI/lib | Nice for one-off downloads and a good **reference implementation** for release discovery, but it's an extra dep (MIT — permissive, fine) that mostly shells out to pyarrow/DuckDB anyway. Optional convenience path, not the core. |
| Sedona / Wherobots | Spark cluster overhead; wrong scale for a lean single-node library. ❌ |
| Azure mirror | Same data on Azure (`abfss://…`); support later as an `endpoint`/`s3_region`-style knob. Default to the AWS `us-west-2` bucket. |

**bbox convention alignment.** netstead's OSM code already standardizes on
`(west, south, east, north)` EPSG:4326 bboxes and reuses `resolve_area()` for
place-string geocoding (Nominatim) and point+buffer. The Overture query module
should **reuse `netstead.osm.query.resolve_area()`** (or a shared `geo`/`area`
helper lifted out of it) so a place string / point / bbox resolves identically for
both sources. This is the biggest single lever for "swap sources with minimal
friction."

Release/version handling: default to a **pinned, known-good release string**
baked into the module (a maintained constant, updatable in one place), with an
`overture_release=` override, mirroring how OSM pins `OVERPASS_URL`. Optionally add
a tiny "latest release" discovery helper later, but pinning keeps builds
reproducible (a modeler re-running a build gets the same network).

---

## 3. Proposed API (mirrors OSM)

```python
def build_network_from_overture(
    area: str | Sequence[float],
    *,
    buffer_m: float = 0.0,
    network_type: str = "drive",          # drive/walk/bike/all — same vocab as OSM
    extra_tags: list[str] | None = None,  # extra Overture segment columns → link columns
    spec_version: str = DEFAULT_SPEC,     # "0.97"
    engine: Any = None,                   # corral engine; default ibis/duckdb
    # --- Overture-specific (sensible defaults; power users only) ---
    overture_release: str = OVERTURE_RELEASE,   # pinned release, e.g. "2026-09-23.1"
    s3_region: str = "us-west-2",
    data_root: str | None = None,         # override base URI (Azure mirror / local snapshot)
    con: Any = None,                      # injectable duckdb connection (tests / reuse)
    timeout: int = 180,
) -> Network:
    ...
```

Design notes on the mirror:

- **Identical positional + shared keyword args**: `area`, `buffer_m`,
  `network_type`, `extra_tags`, `spec_version`, `engine`. A user swaps
  `from_osm` → `from_overture` and keeps the same call in the common case.
- **`extra_tags` semantics reinterpreted**: for OSM these are OSM tag keys; for
  Overture they're **segment column/property names** (e.g. `"road_surface"`,
  `"subclass"`). Same *purpose* (carry extra provenance/attrs onto links), same
  parameter name, source-appropriate values. Document the difference.
- **`network_type`** keeps the `drive/walk/bike/all` vocabulary but filters on
  Overture `class`/`subtype` + travel-mode access rules instead of OSM `highway`
  (see §5.2), via a maintained filter YAML — exactly parallel to
  `osm_network_filters.yaml`.
- **Overture-specific args are all keyworded with defaults** so they don't
  intrude on the common path. `endpoint`/`session`/`user_agent`/`retries` from
  the OSM signature (HTTP-fetch concerns) are replaced by the DuckDB-flavored
  `overture_release`/`s3_region`/`data_root`/`con` (object-store read concerns).
- Also mirror the **records half**: a `network_from_records(...)` already exists
  and is source-agnostic — reuse it verbatim. Overture's `build` produces the
  same `(node_records, link_records)` contract and calls the shared assembler.

CLI: add `netstead build --source overture ...` alongside the existing OSM build
command (see `netstead/cli/commands/build.py`), gated on the same area/network-type
options.

---

## 4. Module layout (`netstead/overture/…`)

Mirrors `netstead/osm/` one-for-one so the two sources read the same:

```
netstead/overture/
  __init__.py        # lazy exports + [overture] extra guard (duckdb, pyyaml)
  build.py           # build_network_from_overture(); reuses osm.build.network_from_records
  query.py           # area resolve (reuse osm.query.resolve_area) + DuckDB S3 read → (segments, connectors)
  convert.py         # pure: segments+connectors → GMNS node/link records (split at connectors, directed expand)
  attrs.py           # value-level transforms + mapping application (parallel to osm/tags.py)
  mappings/
    overture_to_gmns.yaml       # segment property → GMNS link field (mirrors osm_to_gmns.yaml)
    overture_network_filters.yaml  # network_type → allowed class/subtype (mirrors osm_network_filters.yaml)
```

Responsibilities, matched to the OSM modules:

- **`query.py`** = the only module doing I/O (like `osm/query.py`). Resolves the
  area to a bbox (reusing OSM's resolver), runs the two DuckDB reads, returns
  `(segments, connectors)` as plain Python records — the pure/`convert` boundary
  stays clean and unit-testable with fixtures (no S3).
- **`convert.py`** = pure `segments + connectors → (node_records, link_records)`
  (like `osm/convert.py`). Node records come straight from connectors used by
  in-bbox segments; links come from splitting each segment at its ordered
  connectors and expanding to directed links by travel direction.
- **`attrs.py`** = `TRANSFORMS` registry + `apply_mapping()` + network-type filter
  helpers, loading the two YAMLs (like `osm/tags.py`). Overture speed values carry
  explicit units ("60 km/h" / "45 mph"), so `parse_speed` is *simpler* than OSM's
  (no km/h-default guessing).
- **`build.py`** = orchestration, delegating assembly to the **existing**
  `netstead.osm.build.network_from_records` (rename/relocate that to a neutral
  `netstead._build_common` or `netstead.network` helper in a small refactor, since it
  is already source-agnostic — it only touches engine + GMNS spec). This avoids
  duplicating the Network-assembly + config-table logic.

Packaging: add an **`[overture]` extra** (`duckdb`, `pyyaml`; `duckdb` may already
be a core dep via corral — if so the extra is nearly empty) with the same lazy
`__getattr__` import-guard pattern `netstead/osm/__init__.py` uses, so the heavy
read path only imports when actually called.

---

## 5. Attribute mapping approach (Overture → GMNS)

Keep the **maintained-YAML** philosophy: which Overture property feeds which GMNS
field is *data*, edited in `overture_to_gmns.yaml`, not code. Value-level logic
that can't be data (unit parse, scoped-rule reduction, direction) lives in
`attrs.py` transforms.

### 5.1 Baseline YAML (mirrors `osm_to_gmns.yaml`)

```yaml
# Overture segment property -> GMNS link field (maintained data; edit here).
# Each entry: <gmns_field>: { source: <segment property path>, transform: <name in attrs.TRANSFORMS> }

name:          { source: names.primary,   transform: direct }
facility_type: { source: class,           transform: direct }        # motorway/primary/residential/...
free_speed:    { source: speed_limits,    transform: max_speed_mph }  # reduce scoped rules -> single mph
lanes:         { source: road_flags,      transform: lane_count }     # see 5.5 (best-effort)
# route number (I-40, US-1) carried as an extra/provenance column:
route_ref:     { source: routes,          transform: primary_ref }
```

Because several Overture attributes are **arrays of scoped rules**, the
`source` value is a property *path* and the `transform` does the reduction
(pick the unscoped/whole-segment rule, else the widest `between` range) — a
richer transform contract than OSM's flat-tag lookup, but the same shape.

### 5.2 facility_type / network_type filtering

Overture road `class` values (OSM-lineage): `motorway`, `trunk`, `primary`,
`secondary`, `tertiary`, `residential`, `living_street`, `unclassified`,
`service`, `pedestrian`, `footway`, `sidewalk`, `crosswalk`, `path`, `track`,
`cycleway`, `steps`, `bridleway`, `unknown`
([Roads guide](https://docs.overturemaps.org/guides/transportation/roads/)).
These map to `facility_type` directly and drive the `network_type` allow-lists in
`overture_network_filters.yaml` (parallel to `osm_network_filters.yaml`). Prefer
**pushing the class filter into the DuckDB `WHERE`** (`class IN (...)`) so we don't
transfer footways for a `drive` build.

`network_type` should additionally honor **travel-mode access rules** (Overture
models per-mode access: a bus-only lane, a foot-forbidden motorway). Phase 1 can
use class-only filtering (matches OSM behavior); Phase 2 refines with
`access_restrictions[].when.mode`.

### 5.3 Speed limits (scoped → scalar)

`speed_limits[]` entries are `{max_speed: {value, unit}, between:[s,e], when:{...}}`.
`max_speed_mph` transform: take the rule with no `between` (whole segment) or the
dominant range, read `value`+`unit`, normalize to mph (config unit). Units are
**explicit** in Overture, so this is more reliable than OSM's unit-less default.
Scoped variation (speed changes mid-segment) is preserved losslessly only via the
GMNS `segment` table (§5.6, Phase 2); Phase 1 reduces to one `free_speed` per link.

### 5.4 Direction / one-way

Overture encodes direction through **`access_restrictions[].when.heading`**
(`forward` / `backward`) rather than a single `oneway` tag. The `attrs.py`
`overture_direction(segment)` transform inspects access rules to classify a
segment as `both` / `forward` / `backward`, then `convert.py` expands to directed
GMNS links exactly like the OSM converter's `oneway_direction` → orientations
logic (every GMNS link `directed=True`; two-way → two links). This is the fiddliest
transform and the main correctness risk (§7).

### 5.5 Lanes

Overture lane information is less first-class than OSM's `lanes=` tag — it lives in
lane rules / `road_flags` and can be direction- and range-scoped. Phase 1:
best-effort scalar `lanes` (null when unavailable), same "unknown rather than
guess" stance as OSM's `parse_int`. Full lane fidelity → GMNS `lane` /
`segment_lane` tables in a later phase.

### 5.6 Scoped / line-referenced attributes → GMNS `segment` table

Overture's `between:[start,end]` sub-ranges are the same concept as GMNS's own
**`segment`** resource (a sub-range of a link with overriding attributes) and
`segment_lane`. netstead already vendors `segment.schema.json` /
`segment_lane.schema.json` and exposes `.segments` on `Network`. The natural,
faithful mapping is:

- whole-segment attributes → `link`
- `between`-scoped attributes (a speed zone on part of the segment, a lane drop) →
  `segment` rows referencing the link, with `ref_node`/offset from the normalized
  `at` × geodesic length.

This is a **Phase 2** feature (it's where Overture's richness exceeds a flat OSM
export), and it's a genuine argument *for* the Overture source: it can populate
GMNS tables that the OSM path currently leaves empty.

### 5.7 Node ids / topology

Connector ids are stable Overture GERS-style strings. Two choices for `node_id`:
(a) keep the connector id string as `node_id` (GMNS `node_id` is `any`-typed, so a
string is legal and preserves provenance/joinability across releases), or
(b) mint compact integer ids and keep the connector id in an
`overture_connector_id` provenance column (mirrors how OSM keeps `osm_node_ids`).
**Recommend (b)** for consistency with the OSM output (integer ids, provenance
column) and smaller downstream tables, with (a) available via a flag. Likewise
carry `overture_segment_id` on each link (parallel to `osm_way_id`).

Endpoint connectors referenced by an in-bbox segment but whose point falls just
outside the bbox: fetch connectors with a **slightly padded bbox** (or a second
id-based fetch) so no link is left with a dangling `to_node_id`. This mirrors the
OSM converter's fail-fast check that every referenced node exists.

---

## 6. Dependencies + license notes

| Component | License | Concern for Apache-2.0 netstead |
|---|---|---|
| **Overture transportation DATA** | **ODbL** + "© OpenStreetMap contributors" (includes TomTom) | ⚠️ **Share-alike DATA license, not code.** Same status as the existing OSM/Overpass path (also ODbL). Does **not** affect netstead's Apache-2.0 code license. Must **attribute** in derived products and propagate ODbL on redistributed *data*. Add an attribution string to the generated `config`/provenance, mirroring the ODbL note already in `osm/query.py`'s docstring. |
| `duckdb` (+ `spatial`, `httpfs` extensions) | MIT | ✅ Permissive. Likely already present via corral's duckdb engine. |
| `pyyaml` | MIT | ✅ Already used by the OSM mapping loader. |
| `overturemaps-py` (optional convenience) | MIT | ✅ Permissive if adopted; recommend **not** taking it as a core dep (lean-deps ethos) — hand-roll the thin DuckDB read instead. |
| `geoarrow`/`geopandas`/`shapely` | Apache-2.0 / BSD | ✅ Permissive **if** needed, but avoid: DuckDB `ST_AsText`/`ST_X`/`ST_Y` gives WKT + coords without a geometry-library dep, keeping the pipeline pandas/geopandas-free like the OSM one. |

Net: **no new non-permissive code deps.** The only share-alike obligation is
ODbL on the **data**, which the OSM source already carries — so this adds no *new*
licensing category to the project. Flag it clearly in docs and stamp attribution
into build output.

Sources:
[Overture attribution/licensing](https://docs.overturemaps.org/attribution/),
[overturemaps-py](https://github.com/OvertureMaps/overturemaps-py) (MIT),
[DuckDB](https://duckdb.org/) (MIT).

---

## 7. Easier / harder vs OSM

**Easier with Overture**

- **Topology is authoritative, not inferred.** Connectors give node identity and
  connectivity explicitly (shared connector id). No `_kept_nodes` heuristic
  guessing which shape points are intersections.
- **Efficient area fetch** via GeoParquet bbox pushdown over S3 — no Overpass
  rate limits, no self-hosting an Overpass instance for large extracts, no
  Nominatim etiquette constraints for the data read (still used for place→bbox).
- **Units are explicit** on speeds → simpler, less error-prone speed parsing.
- **Cleaner, deduplicated, QA'd data** (TomTom + conflation) vs raw OSM tag soup.
- **Reproducibility**: pinned release string = deterministic builds.
- **Richer GMNS output possible**: scoped attributes can populate GMNS
  `segment`/`segment_lane`/lane tables the OSM path leaves empty.

**Harder with Overture**

- **Direction/one-way is implicit** in per-mode `access_restrictions[].when.heading`
  rather than a single `oneway` tag — more parsing, main correctness risk.
- **Scoped-rule reduction**: many attributes are arrays of `between`/`when` rules;
  collapsing to a scalar link attribute needs a documented, tested policy.
- **Lanes / turn restrictions less first-class** than OSM tags in some regions.
- **Coverage/latency**: monthly release cadence (vs OSM near-real-time); newest
  edits lag. Coverage is OSM-derived so broadly comparable, but the schema
  normalization can drop or reshape niche OSM tags a power user expected.
- **Larger dependency surface for reads** (DuckDB spatial/httpfs, S3 access,
  credentials/region config) vs a plain HTTP POST to Overpass.
- **Bigger data model to learn** (scoped/line-referenced attributes, GERS ids).

---

## 8. Risks / unknowns

1. **Direction parsing correctness** (§5.4). Getting one-way wrong silently
   produces a broken routable graph. Needs fixture-based tests against known
   one-way streets. *Highest-severity risk.*
2. **Connector-at-bbox-edge dangling nodes** (§5.7). Mitigate with padded
   connector fetch + the same fail-fast "every referenced node exists" guard the
   OSM converter has.
3. **Scoped-rule reduction policy** (§5.3/5.6): which rule wins when a segment has
   multiple speed/access rules and we're forced to a scalar. Needs an explicit,
   documented rule (unscoped-first, else widest range) and a Phase-2 path to the
   GMNS `segment` table for lossless capture.
4. **Release-string drift / schema evolution**: Overture schema is still maturing;
   property paths in the YAML may need updates across releases. Pinning + a single
   maintained constant + YAML-as-data limits the blast radius. Consider a smoke
   test that the pinned release's columns still resolve.
5. **S3 access / credentials**: anonymous public read works for the AWS bucket, but
   region/endpoint config and corporate proxies can bite. Provide `s3_region` /
   `data_root` overrides and a local-snapshot path for offline/CI.
6. **DuckDB spatial/httpfs availability**: extension auto-install needs network at
   first run; document and allow a pre-provisioned connection (`con=`).
7. **Perf on large bboxes**: even with pushdown, a metro-scale pull is sizeable.
   Reuse/borrow the OSM path's "too big → narrow the area" guidance.
8. **`network_from_records` relocation**: it currently lives in `netstead.osm.build`.
   Moving it to a neutral home is a small refactor touching the OSM import path —
   coordinate so the OSM source keeps working (re-export for back-compat).

---

## 9. Phased plan

**Phase 0 — spike (validate the read).** Prove the DuckDB-over-S3 bbox read for
`theme=transportation` segment+connector on a small bbox (e.g. the existing
`rdu_i40` / `leavenworth` fixture areas). Confirm columns, bbox pushdown, and
anonymous S3 access. No netstead wiring yet. *De-risks §2, §8.5–8.6.*

**Phase 1 — MVP parity with OSM (drive network).**
- `netstead/overture/{query,convert,attrs,build}.py` + two YAML mappings.
- Reuse `resolve_area()` and `network_from_records()`.
- Map: `name`, `facility_type` (class), `free_speed` (scalar), `lanes`
  (best-effort), directed-link expansion from `access_restrictions.heading`.
- `network_type` = class-based filter (drive/walk/bike/all), pushed into SQL.
- Node ids = minted integers + `overture_connector_id`/`overture_segment_id`
  provenance columns.
- `build_network_from_overture(...)` public API (§3); `[overture]` extra; lazy
  imports; ODbL attribution stamped into output.
- Tests: pure `convert`/`attrs` on fixtures (no network); one integration test
  behind a network/opt-in marker.
- CLI: `netstead build --source overture`.

**Phase 2 — richness beyond OSM.**
- Scoped attributes → GMNS `segment` / `segment_lane` tables (speed zones, lane
  drops) via the normalized `at` linear references (§5.6).
- Route numbers, destinations, per-mode access → allowed_uses + `movement` turn
  restrictions from `prohibited_transitions[]`.
- Travel-mode-aware `network_type` filtering (§5.2).

**Phase 3 — polish / ops.**
- Optional "latest release" discovery; Azure mirror support (`data_root`).
- Local-snapshot / offline path for CI and reproducible research.
- Docs: source-comparison guide (OSM vs Overture), attribution guidance,
  migration note for `extra_tags` semantics.

---

## 10. Open questions for the maintainer

- **`network_from_records` home**: OK to relocate the source-agnostic assembler out
  of `netstead.osm.build` into a shared module (with back-compat re-export)?
- **Default release policy**: pin-and-bump-manually (recommended, reproducible) vs
  auto-latest (fresher, non-deterministic)?
- **node_id policy**: minted ints + provenance (recommended, matches OSM) vs
  keep GERS connector strings as `node_id` (better cross-release joins)?
- **Scope of Phase 1**: is drive-network parity with OSM the right MVP bar, or is
  the `segment`-table richness (Phase 2) the actual motivating use case that
  should come first?
