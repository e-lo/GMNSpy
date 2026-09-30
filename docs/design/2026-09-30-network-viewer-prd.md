# PRD — GMNS network viewer (`gmnspy.viz`)

**Status:** Draft for review. Capability-first; tech is "considerations," not locked.
**Author:** Elizabeth Sall (easall@gmail.com) with Claude.
**Related:** [[gmnspy.select]] (NL selection), existing `gmnspy.map` (static Leaflet report
viewer — this supersedes it for interactive use), the `gmnspy select-serve` prototype.

---

## 1. Summary

A fast, interactive web viewer for GMNS networks. One renderer serves both a **partial
network / selection** (today) and the **full network** (future) — the same code path, so
what we build now scales up rather than getting replaced. Users toggle layers, style by
attribute, highlight paths/links/nodes, inspect attributes (tooltip + detailed table), and
eventually compare two networks (QA/QC + scenario diff) and view multimodal + transit (GTFS)
layers. Rendering approach follows SimWrapper: **deck.gl binary layers over a MapLibre
basemap**, fed by typed arrays derived cheaply from GeoParquet.

## 2. Motivation

- The NL-selection feature needs a trustworthy visual confirm ("did it pick the right links?").
- Modelers need to **inspect and QA** networks (are attributes right? is connectivity sane?),
  which today means ad-hoc GIS exports.
- Scenario work needs to **see differences** between networks.
- GMNS is multimodal (roads, lanes, transit, and — via extension — bike/ped); the viewer
  should be architected for that from the start even if modes land incrementally.
- We want **one** viewer, not a throwaway selection map plus a separate "big network" tool.

## 3. Goals / Non-goals

**Goals**
- One rendering path for partial selection and full network (consistency is a first-class goal).
- Fast: smooth pan/zoom on regional networks (target: hundreds of thousands of links).
- Minimal data processing from GeoParquet → screen.
- Attribute inspection at two depths (hover tooltip; full detail table).
- Attribute-driven styling and layer control.
- Extensible layer model so new feature classes (bike/ped/transit) slot in without a rewrite.

**Non-goals (now)**
- Editing geometry/attributes in the viewer (view + select only; editing is a separate track).
- Rendering bike/ped/transit *yet* — but the architecture must not preclude them.
- Server-side heavy GIS analytics; the viewer visualizes, gmnspy computes.
- Planet-scale streaming (billions of features); regional-model scale is the target.

## 4. Users & primary use cases

1. **Selection confirm** — type/inspect a `gmnspy.select` result; see highlighted links + gore/
   merge anchors; correct if wrong. (Exists in prototype.)
2. **Network QA/QC** — load a network, color by attribute (facility_type, lanes, speed),
   click links/nodes to verify attributes, spot connectivity/geometry errors.
3. **Scenario / version diff** — load two networks; see added/removed/changed links & nodes and
   changed attributes.
4. **Exploration/communication** — pan a network on a basemap, style it, screenshot/share.

## 5. Capabilities (functional requirements)

### 5.1 Map & navigation
- Pan/zoom/rotate over a real **basemap** (streets + optional satellite/light/dark).
- Fit-to-network and fit-to-selection.
- Works on a partial network (a selection's neighborhood) or a whole network with the same UX.

### 5.2 Layers & layer control
- Feature classes render as **independent, toggleable layers**: nodes, links (roadway),
  selection-highlight, O/D markers, and — reserved — lanes, bike, ped/sidewalk, trails,
  transit stops, transit routes, transit vehicles, zones.
- A **layer panel**: show/hide each layer, reorder/opacity, and per-layer style controls.
- Layers are declarative + registry-driven so a new mode = a new layer definition, not new
  plumbing.

### 5.3 Styling (attribute-driven)
- **Color by property**, three modes:
  - *categorical* (e.g. `facility_type`, mode) → discrete palette + legend;
  - *continuous/value-based* (e.g. `lanes`, `free_speed`, volume) → color ramp + legend;
  - *selection/membership-based* (in-selection vs not; in diff-set A/B).
- **Width by property** (e.g. lanes, volume) and a manual override.
- Editable palettes; sensible defaults; colorblind-safe ramps; light/dark aware.
- Style changes are cheap (update a GPU attribute buffer, no reload).

### 5.4 Selection & highlighting
- Highlight a **path** (ordered link set from `gmnspy.select`).
- Highlight arbitrary **link sets** (e.g. "selected links", a query result).
- Highlight **nodes** with roles (e.g. origin/destination markers, gore/merge anchors).
- Multiple concurrent highlight sets, each independently styled (color/width), toggleable.
- Selection is a *styling state on the same links layer* where possible (not a separate data
  copy), so it stays consistent and cheap.

### 5.5 Attribute inspection — two depths
- **Tooltip (hover):** a few high-level attributes (id, name/ref, facility_type, key metric).
  Cheap — carried in the layer.
- **Detail table (click / panel):** the full, extensive attribute row(s) for the clicked
  feature(s) — all GMNS columns, related rows (a link's lanes, TOD entries, etc.).
  Fetched on demand (not held in the GPU layer). Virtualized for large attribute sets.
- Table supports multi-select (inspect several links at once), sort, and copy/export.

### 5.6 Directionality
- Directed links (two carriageways, or opposing one-way links on one alignment) are drawn with
  a **lateral offset by direction** so both are visible and individually clickable.
- Optional arrowheads / direction indicators.
- **Offset must apply to picking too:** an offset shifts pixels, not the underlying geometry, so
  a naive click can select the un-offset centerline or the wrong direction. Whatever offset
  mechanism we use must offset the pick pass as well (or compensate with hit-radius + cycle).

### 5.7 Overlapping / stacked features
- Geometrically overlapping links (tunnel under a street, double-decker bridge, stacked
  freeway+arterial) must be **disambiguable and selectable** — the user can reach the one they
  mean. Layered approach (all compatible with binary attributes):
  1. **Lateral offset** (§5.6) handles the common two-way / side-by-side case.
  2. **Vertical z / elevation (2.5D)** from a grade-separation attribute (`z_coord` / layer /
     grade tag) separates tunnel-below / bridge-above under a pitched camera.
  3. **Click-to-cycle** through all features under the cursor (multipass picking) for exactly
     coincident geometry where offset/z aren't enough.
  4. **Layer/mode filtering** (§5.2) as the cheapest disambiguation — isolate a class so stacks
     thin out.
- Picking must map a tessellated path segment back to its **source link id**, not an instance id.

### 5.8 Network diff / comparison (later phase, design now)
- Load two networks (versions or scenarios); compute and render:
  - **added / removed** links & nodes (distinct styles);
  - **changed** links (attribute deltas) with a way to see which attributes changed;
  - unchanged as context (muted).
- Toggle between "A", "B", and "diff" views, plus **overlay-with-filters** and a **swipe /
  side-by-side** mode.
- Conventional GIS diff semantics: **green = added, red = removed, amber = modified**;
  changed-attribute magnitude as a diverging ramp on the "modified" layer.
- **Diff is a data step, not a rendering trick:** join A/B GeoParquet on `link_id`/`node_id` →
  a `status` column + changed-attribute deltas (offline/server-side); the viewer just renders
  three toggleable membership layers. Keeps QA/QC reproducible and engine-agnostic.
- Serves both QA/QC (did my edit do only what I intended?) and scenario comparison.

### 5.9 Selection / search integration
- Enter a natural-language utterance (via `gmnspy.select`) → resolved selection highlighted +
  fragment shown (the current prototype, folded into this viewer).
- Later: attribute queries ("all links where lanes ≥ 3") as ad-hoc selections.

### 5.10 Export
- Export the current view (image), the current selection (GMNS fragment / ProjectCard), and
  the detail table (CSV).

## 6. Future scope (architect for, don't build yet)

- **Multimodal layers:** sidewalks, bike paths, trails, transit *facilities* — each a feature
  class with its own layer definition + style; the layer registry must accept them without
  core changes.
- **Transit service (GTFS):** two layers — (a) a static routes+stops layer (PathLayer +
  Scatterplot/Icon) styled by mode and by **headway/frequency** (from aggregated `stop_times`/
  `frequencies`); (b) an **animated-vehicle** layer (deck.gl `TripsLayer`) driven by a
  **time slider** (`currentTime`, `trailLength`). The GTFS→geometry+time transform (cut each
  `shape` at successive stop distances via linear referencing, interpolate timestamps along the
  coordinates between stop times → per-trip `[lng, lat, t]` paths) is **precomputed offline in
  Python** (shapely / gtfs-lib) and stored binary; the browser only animates. Reference recipe:
  Kyle Barron "All Transit"; Conveyal's route data model (alignments, frequencies, dwell,
  speeds) for the attributes to carry.
- **Time dimension generally:** TOD attributes (GMNS `*_tod` tables), volumes by period,
  animated flows. The viewer should reserve a time-control concept.

These future modes influence the tech approach now: a **per-feature-class layer registry**, a
**time-aware data/animation path**, and a **data model that treats "a layer" abstractly**
(geometry source + attribute table + style spec + optional time), not "roads, hard-coded."

## 7. Data model & inputs

- **Primary input:** a GMNS network as GeoParquet/Parquet (via `gmnspy.Network`) — `node`,
  `link`, and related tables (`lane`, `segment`, `geometry`, `zone`, signals, `*_tod`).
- **Geometry:** node `x_coord`/`y_coord` (EPSG:4326); link geometry as WKT today (optionally a
  coordinate-native GeoParquet/GeoArrow geometry column — see §8).
- **Selections:** from `gmnspy.select` (`SelectionResult` / fragment) and ad-hoc queries.
- **Diffs:** computed over two `Network`s (added/removed/changed) — reuse `datagrove.editing`
  / a diff helper.
- **Future:** GTFS feed(s); extension tables for bike/ped/trails.

## 8. Tech considerations (informed by SimWrapper; NOT final)

- **Renderer: MapLibre (basemap) + deck.gl (network), interleaved via `@deck.gl/mapbox`.**
  This is SimWrapper's exact stack and the standard pairing (deck.gl has no basemap; MapLibre
  has no fast big-network layer). One renderer for partial + full satisfies the consistency
  goal.
- **Layers: built-in deck.gl `LineLayer`/`PathLayer` + the built-in `PathStyleExtension`
  (`getOffset`) for directional offset — prefer this over a custom shader.** SimWrapper
  subclasses the layer and injects its own offset shader (`LineOffsetLayer`), but a hand-rolled
  `getShaders()` override is a recurring maintenance cost across deck.gl majors. Use the
  extension's signed per-link `getOffset` (a binary attribute) first; drop to a SimWrapper-style
  custom shader only for per-vertex/width-coupled offset the extension can't express — and if so,
  **offset the picking pass too** so clicks match what users see. `ScatterplotLayer`/`IconLayer`
  for nodes/stops; `TripsLayer` for transit animation; aggregation layers for density.
- **Data path: GeoParquet → typed arrays is a cheap gather, not heavy processing.**
  - *Straight* links render from **node coordinates** (`from`/`to` → source/dest `Float32Array`)
    with **no geometry parsing** — the fastest, most seamless path from Parquet.
  - *Polyline* geometry needs coordinates; store geometry **coordinate-native
    (GeoParquet/GeoArrow)** to avoid WKT parsing, or parse WKT once (server or worker) and cache.
  - deck.gl consumes **binary attributes** (`{value: Float32Array, size}`) directly to GPU —
    zero per-feature JS per frame (the reason it's fast).
  - Build the typed arrays **server-side from the Parquet frames** (pyarrow/DuckDB → contiguous
    arrays → Arrow IPC / raw binary over HTTP), or in-browser via `parquet-wasm`/GeoArrow.
    Prefer server-built binary for a thin frontend; keep the option open. **Do not ship GeoJSON
    for the network** (that was the prototype's stopgap).
- **Tooltip vs table split:** tooltip attributes travel in the layer (a few columns); the full
  detail table is fetched on click via a **DuckDB-backed endpoint** (`SELECT * ... WHERE
  link_id = ?` + related rows). Keeps GPU buffers lean, attributes authoritative.
- **Styling:** color/width are **GPU attribute buffers**; restyle = recompute one buffer, not a
  reload. Categorical/continuous/membership all map to per-feature color/width arrays computed
  from a column + a scale (d3-scale).
- **Overlapping/stacked:** lateral offset (extension) for two-way; per-vertex **z/elevation**
  from a grade-separation attribute for tunnel/bridge under a pitched view; **`pickMultipleObjects`
  click-to-cycle** for exactly coincident links; layer/mode filtering as the cheap fallback.
- **Diff:** precompute a `status` column + attribute deltas server-side (A/B join on id); render
  three membership layers (green/red/amber) over muted context; overlay+filter and swipe modes.
  No special renderer needed.
- **Cross-cutting principle:** offsets, z, diff `status`, trip timestamps, and headway are all
  **per-feature scalar/vector attributes** — precompute offline (Python/GeoParquet), pass as
  binary, never per-feature JS in the browser. Prefer **stock deck.gl layers + extensions** over
  custom shaders; push heavy transforms (WKT parse, shape-cutting, diff join) to the backend.
- **Scale path:** whole network resident as typed arrays (~1–2M links, memory-bound) is the
  default (SimWrapper-style). Escape hatches that keep the *same* deck.gl layer: server-side
  **bbox streaming** (send only viewport links) and, only if truly needed, **PMTiles** vector
  tiles. Consistency preserved because the layer/data-format stays constant.
- **Backend:** FastAPI (reuse `datagrove.api` composition), consistent with `gmnspy
  select-serve`; endpoints: network binary buffers, attribute detail, selection resolve, diff.
- **Frontend footprint:** deck.gl + luma + MapLibre + a small offset-shader layer + a
  virtualized table. Heavier than the current one-file MapLibre+GeoJSON page — the cost of the
  consistent, scalable path.

## 9. Module layout (proposal)

`gmnspy/viz/` (new submodule; absorbs the `gmnspy.select` webapp, supersedes `gmnspy.map`'s
interactive role):
- `server.py` — FastAPI app factory (network buffers, attribute detail, selection, diff).
- `buffers.py` — Parquet frames → typed-array buffers (positions/colors/widths; Arrow IPC).
- `layers.py` — layer registry / layer specs (per feature class; style spec; time-aware hook).
- `diff.py` — network A/B diff sets.
- `static/` + `templates/` — deck.gl + MapLibre frontend (offset layer, panels, table).
- CLI: `gmnspy viz <network>` (and the existing `select-serve` folds in).

## 10. Phasing (rough)

- **P1 — Viewer core (consistency foundation):** MapLibre+deck.gl, links from node coords as
  binary, nodes layer, hover tooltip, fit; port the current selection highlight onto this path.
- **P2 — Inspect & style:** layer panel (toggle/opacity), attribute styling (categorical/
  continuous/membership), detail table (DuckDB endpoint), O/D node highlighting, directional
  offset.
- **P3 — Diff:** two-network load, diff sets, A/B/diff views.
- **P4 — Multimodal + GTFS:** bike/ped/trails layers; GTFS routes/stops + vehicle animation +
  time slider. Polyline geometry via GeoArrow; overlapping-feature disambiguation.

## 11. Open questions

- Geometry representation: adopt a **coordinate-native (GeoArrow) geometry** column in the GMNS
  parquet to make the render path zero-parse? (Affects gmnspy I/O, not just the viewer.)
- Straight-vs-polyline default: render links straight (node-to-node) for speed, with true
  geometry as an opt-in layer? For most GMNS links straight is visually fine and fastest.
- Server-built binary vs in-browser parquet-wasm/GeoArrow — which as the primary path?
- Does the viewer live in `gmnspy.viz`, or extend `gmnspy.map`? (Naming/consolidation.)
- Diff granularity: attribute-level deltas vs link-level added/removed/changed only, for P3.

*(Resolved by the renderer survey: use `PathStyleExtension.getOffset` for directional offset,
not a custom shader; overlap default = offset + z + `pickMultipleObjects` cycle; diff = green/
red/amber membership layers off a precomputed `status` column; GTFS = static layer + `TripsLayer`
with offline shape-cutting.)*

## 12. Prior art / references

- **SimWrapper** — the reference architecture (deck.gl + MapLibre + workers; `LineOffsetLayer`
  offset shader; per-dataset layer symbology). https://github.com/simwrapper/simwrapper
- **deck.gl** — `PathStyleExtension` (`getOffset`), `TripsLayer`, `pickMultipleObjects`
  (overlapping-object picking). https://deck.gl/docs
- **Kyle Barron, "All Transit"** — GTFS → `TripsLayer` shape-cutting + timestamp interpolation.
  https://kylebarron.dev/blog/all-transit/
- **Conveyal Analysis / r5** — transit route data model (frequencies, dwell, alignments) and a
  multimodal street taxonomy. https://www.conveyal.com/analysis
- **QGIS diff conventions** — green=added / red=removed / amber=modified (Mergin Maps changes
  viewer; LayerDiffViewer). Establishes the diff palette + separate-layer-per-change pattern.
