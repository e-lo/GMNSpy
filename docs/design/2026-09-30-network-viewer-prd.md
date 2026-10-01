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

- **Zoom-driven GMNS sub-table layers (map rendering, not just the table view):** the
  non-default GMNS tables become *map* layers gated by zoom, each with its own representation.
  Default off; toggled per layer (layer registry). Target behavior (user-specified, 2026-10-01):
  - **Zones** — visible at **almost any zoom** (polygons/centroids; the one sub-table that reads
    at regional scale).
  - **Turning movements, segments, lanes, segment_lanes** — **high (close-in) zoom only**, where
    there's room to draw them: movements as per-approach arrows at the intersection node; lanes /
    segment_lanes as parallel offset ribbons along the link; segments as sub-link extents.
  - **Signals** — an **abstract glyph at medium & close zoom** (a signal marker at the node), not
    a literal depiction; **click → panel** of the signal family's data (phases, timing, `signal_*`
    tables). Follows the same click-to-detail path links already use.
  - **TOD (`*_tod`)** — not a geometry layer; at **medium & close zoom annotate the owning link**
    ("this link has time-of-day values"), and surface the actual TOD rows **on link click** (and
    later a time slider — ties into "Time dimension generally" above).
  Implication: the layer registry entry needs a **zoom range** (minzoom/maxzoom) and a
  **representation kind** (glyph / arrow / offset-ribbon / polygon / link-annotation), and the
  click-detail panel must dispatch by feature class (link / node / signal / zone). Data already
  flows in lazily via the G1 table provider; these are *rendering* layers on top of it. The map
  binary (`buffers.py`) is link+node today — sub-table geometry would pack similarly, zoom-gated.

- **Editing (eventual — explicitly NOT near-term):** the viewer stays view+select for the
  foreseeable future, but the long-term direction is in-viewer editing (attributes, geometry,
  add/remove links & nodes) feeding the ProjectCard/edit track. Architectural implication now:
  the viewer already produces validated **selections/fragments**, which are exactly the input an
  edit layer would consume — so "select → edit → re-render" is a natural later extension, and
  the render path (binary attributes, restyle-on-buffer-update) already supports live redraw
  after a change. We do not build editing now; we just avoid precluding it.
- **NL interaction beyond selection:** today NL → structured *selection*. Later we'll want NL
  for styling ("color links by lanes"), filtering/query ("links where speed < 30"), navigation,
  and eventually editing — all as validated structured actions the viewer executes. Interaction
  model under review (see §12).

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
  subclasses the layer and injects its own offset shader (`LineOffsetLayer`), but that is a
  recurring maintenance cost across deck.gl majors **and SimWrapper is GPL-3.0, so we cannot copy
  its shader/layer code into Apache-2.0 GMNSpy** (§13). Use the extension's signed per-link
  `getOffset` (a binary attribute, MIT) first; if we ever need offset behavior the extension can't
  express, write our **own** offset shader from scratch (referencing SimWrapper only for the idea)
  and **offset the picking pass too** so clicks match what users see. `ScatterplotLayer`/`IconLayer`
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
- **Scale path — a proven two-track model (Overture explorer, all permissive licenses).**
  Overture (GeoParquet/DuckDB-native, the closest match to our stance) does NOT stream raw
  GeoParquet per-frame for the whole planet; it splits: (1) **PMTiles vector tiles** rendered by
  MapLibre for the *whole-network overview at scale* (single static file, HTTP range requests, no
  tile server), and (2) **GeoArrow → deck.gl** (via `geoarrow-rs`/`parquet-wasm`) for the
  *active/filtered/queried subset* and export. **`lonboard` (MIT)** is the reference for track (2)
  and validates our binary pipeline (GeoParquet→GeoArrow→deck.gl, no GeoJSON; ~50× over
  GeoJSON-based tools). Mapping to GMNS: **deck.gl-binary GeoArrow is the default** for the working
  network / selection (memory-bound, ~1–2M links, no tile build); add a **PMTiles overview track**
  only when a network is too big to hold resident. Both tracks share MapLibre + the same data
  origin, so consistency holds. Plus a cheap high-value **"export visible viewport"** (→ GeoParquet/
  GeoJSON) feature falls out of track (2).
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
  **⚠ GPL-3.0 — architecture/ideas reference ONLY; do not copy its source (see §13).**
- **deck.gl** — `PathStyleExtension` (`getOffset`), `TripsLayer`, `pickMultipleObjects`
  (overlapping-object picking). https://deck.gl/docs
- **Kyle Barron, "All Transit"** — GTFS → `TripsLayer` shape-cutting + timestamp interpolation.
  https://kylebarron.dev/blog/all-transit/
- **Conveyal Analysis / r5** — transit route data model (frequencies, dwell, alignments) and a
  multimodal street taxonomy. https://www.conveyal.com/analysis
- **QGIS diff conventions** — green=added / red=removed / amber=modified (Mergin Maps changes
  viewer; LayerDiffViewer). Establishes the diff palette + separate-layer-per-change pattern.

**2nd prior-art pass (reviewed — folded into §8, §14, §15):**
- **Overture Maps explorer** (https://explore.overturemaps.org/) — GeoParquet + duckdb ecosystem;
  closest match to our storage stance for "render whole network from GeoParquet fast."
- **conveyal/transitive.js** — schematic/stylized transit rendering ideas (dated tech).
- **GUI/UX capability review:** CARTO, Conveyal (analysis + scenario editor), Mapbox (GL JS /
  Studio), Felt (https://felt.com/about — approachable, collaborative map GUI).
- **NL interaction approaches:** Monarcha.ai (https://monarcha.ai/) and Felt AI — reviewing the
  interaction model (NL → structured map/query/style/edit actions) to inform our NL layer;
  goal is approach, not a commercial-product build.

## 13. License & legal considerations

**GMNSpy is Apache-2.0** (permissive). Rule of thumb: we may depend on, bundle, and even copy code
from **permissive** licenses (MIT / BSD-2 / BSD-3 / Apache-2.0) with proper attribution; we must
**not copy source from copyleft** projects (GPL / AGPL / LGPL-with-static-linking) into GMNSpy, as
that can force relicensing. **Functionality, UX patterns, and APIs are not copyrightable** — we can
freely learn from any tool (including commercial ones); the line is *copying code or assets*.

**Tech-stack libraries — all verified permissive & Apache-2.0-compatible:**

| Library | License | Use |
|---|---|---|
| deck.gl, @deck.gl/* | MIT | ✅ depend/use |
| MapLibre GL JS | BSD-3-Clause | ✅ depend/use (the open fork — **not** Mapbox GL JS v2+) |
| luma.gl | MIT | ✅ (via deck.gl) |
| @geoarrow/deck.gl-layers | MIT | ✅ |
| parquet-wasm, geoarrow-rs | Apache-2.0 | ✅ |
| lonboard | MIT | ✅ (notebook path) |
| PMTiles (protomaps) | BSD-3 (spec CC0) | ✅ |
| tippecanoe (felt) | BSD-2 | ✅ tile build |
| tylertoo | Apache-2.0 | ✅ tile build |
| DuckDB / duckdb-wasm | MIT | ✅ |
| transitive.js, conveyal/r5, analysis-ui | MIT | ✅ (mostly ideas anyway) |

**Restrictions to honor:**
- **SimWrapper is GPL-3.0.** Reference for architecture/ideas only. **Do not copy** its shaders,
  layers, or any source into GMNSpy. Our offset uses MIT `PathStyleExtension`; any custom shader we
  write from scratch. (This is why the §8 recommendation is what it is.)
- **Mapbox GL JS v2+ is proprietary** (Mapbox BSL / commercial terms). Do not use it or its code —
  we use **MapLibre** (BSD-3). Mapbox's expression spec/Studio are inspiration, not code to copy.
- **Basemap tiles are a *service*, not a code license, and we keep them keyless.** Default is
  **OpenFreeMap's vector Positron** (`tiles.openfreemap.org/styles/positron`, no API key, OSM/
  OpenMapTiles data, crisp at any zoom) so the network pops; `--basemap esri` switches to Esri
  World Light Gray (raster, capped at z16 so MapLibre overzooms instead of hitting Esri's "map data
  not yet available" placeholder). **Carto's CDN now requires an API key** (watermarks otherwise),
  and its `?api_key=` raster form did not authenticate in testing — so we avoid it; **no basemap
  option embeds or requires a secret.** If a keyed provider is ever wanted, inject the key at
  runtime via a config endpoint from an env var — never commit it. Always show attribution; a
  production deployment should confirm the provider's terms or self-host tiles.
- **Network *data* licenses.** GMNS networks built from OSM (`osm2gmns` / `gmnspy.osm.build`) carry
  **ODbL** obligations — attribution + share-alike on derived databases; our bundled fixtures
  already state ODbL. **Overture** data is CDLA-Permissive-2.0 for most themes and **ODbL** for
  OSM-derived transportation — attribution required; check per-theme before redistributing.
- **Commercial products reviewed for approach** (CARTO, Felt, Mapbox Studio, Monarcha): borrow
  *concepts/UX* only. Do **not** copy proprietary code, assets, or verbatim proprietary grammars —
  e.g. Felt's "Style Language" is Felt's; we design our **own** declarative style spec inspired by
  the idea. Felt's MCP tool catalog informs our action-schema *approach*, not any copied schema.
- **AI/NL layer:** no third-party license implicated by the *approach* (validated structured intent
  + tool-use); the action schema and prompts are our own. Keep it LLM-provider-pluggable.

**Net:** the recommended architecture (MapLibre + deck.gl + GeoArrow/GeoParquet + DuckDB, optional
PMTiles) is entirely permissive and clean for an Apache-2.0 project. The only copyleft in view is
SimWrapper, handled by treating it as an ideas reference and not copying its code.

## 14. GUI / UX patterns to adopt (prior-art review)

Ranked, each with the product that demonstrates it (all realistic for an OSS parquet/duckdb +
deck.gl tool; realtime multi-user collab and cloud-warehouse coupling are explicitly out of scope):

1. **End-to-end binary pipeline, GeoArrow → deck.gl, never GeoJSON** (lonboard). Foundational;
   confirms §8. GeoParquet on disk + DuckDB for query.
2. **Two-track rendering:** PMTiles overview for the whole network + GeoArrow/deck.gl for the
   active/filtered subset (Overture). The realistic "render the whole network fast" path (§8).
3. **Linked stats widgets with cross-filtering** — histogram/category/formula panels that both
   summarize and *filter* the map (and each other) by field + viewport (CARTO). Highest-value
   analytical UX; back it with DuckDB SQL over Parquet. → new capability for §5.
4. **Accessor/expression style-by-attribute + `feature-state`-style hover/select** (Mapbox GL):
   per-feature styling via deck.gl `getColor`/`getWidth` + `updateTriggers`; cheap highlight via
   picking state without mutating source (fits §5.3/§5.4).
5. **Auto-generated, live legend from a declarative, text-serializable style spec** where category
   order = legend + draw order (Felt Style Language *idea* — we write our own spec, §13). Shareable
   as a config file; fits the parquet/config ethos.
6. **List-view (author) vs Legend-view (present) split, with all layer visibility in one place**
   (Felt; Conveyal's split-visibility is the anti-pattern to avoid).
7. **Route/line bundling + node consolidation + "highlight one, dim the rest"** for busy corridors
   (transitive.js *concepts*, implemented on deck.gl PathLayer offsets — not schematic reprojection).
8. **"Export visible viewport" (→ GeoParquet/GeoJSON) and SQL-defined layers** (Overture + CARTO) —
   turns the viewer into a lightweight query/extract tool.

## 15. NL interaction model (prior-art review)

Keep our spine — **LLM emits a validated structured intent; deterministic code executes it** — which
is exactly what the credible product (Felt, via its MCP tool catalog) converges on. Generalize it:

- **Action schema (discriminated union of validated models), not generated code** for common ops.
  `SelectIntent` (have it) is the primitive; add `StyleAction` (target + attribute + method + palette),
  `FilterAction` (a **constrained predicate** validated against the GMNS field set — *not* free-form
  NL→spatial-SQL, which the GeoSQL research shows hallucinates spatial functions), `NavigateAction`
  (bbox/place/selection; geocoding is the one sanctioned external lookup). Later: `EditAction`,
  `DiffAction`.
- **Interaction surface:** a docked **chat panel** (keyboard-accessible) that composes these actions
  over multi-turn context ("now color the selection by speed instead"), with a command-bar entry
  feeding the same schema for power users.
- **Trust/safety patterns to adopt (Felt):** (a) **execution transparency** — echo the structured
  action + what changed; (b) **draft-before-apply** for anything mutating (essential once editing/
  diffing land); (c) **`@`-references** to disambiguate layers/selections ("style @selection by
  lanes"); (d) **scoped grounding** — feed the loaded layers + GMNS schema into the prompt so field/
  op validation is deterministic; (e) **self-correction loop** — re-prompt with the validation error
  rather than surfacing a raw failure.
- **Reserve generated code/SQL** for an explicit, always-**reviewable-draft** "advanced" escape hatch
  (Felt does this) — never the silent default.
- **Avoid:** Monarcha's opaque "just describe it / 50+ tools, trust us" black-box framing (bad for
  OSS auditability); free-form NL→spatial-SQL as the default; coupling the NL layer to one LLM
  provider (keep the action schema plain JSON-schema tool defs → works across Anthropic/OpenAI/local).

## 16. Selection-engine roadmap (from real usage)

Driving the viewer on a full metro network surfaced that the v1 selection engine is a deliberate
slice; these are the capabilities to grow it into "an utterance just handles open-ended requests."
Two layers matter: **(P) parser flexibility** (LLM vs the offline stub) and **(R) resolver/schema
capability** (what a structured intent can express + execute). The LLM gives flexible *phrasing*;
the schema+resolver decide what can actually be *asked and resolved*.

- **16.1 Live LLM parser (P).** Default the viewer to the `ClaudeParser` (provider-pluggable;
  Anthropic/OpenAI/local) so phrasing is flexible ("from A to B", casual wording). The stub stays
  the offline/test fallback. Key from env, never committed (§13).
- **16.2 Richer intent schema (R).** Expand `SelectionIntent` (and the LLM tool schema) beyond
  "facility + required from/to":
  - facility by **name OR ref** (surface arterials, not just motorway/trunk);
  - **optional anchors** → whole-facility select ("Electra Ave" = all of it, connected);
  - **attribute predicate** ("where lanes = 2", "where speed < 30") as a validated structured
    filter over GMNS fields (NOT free-form SQL — hallucination risk, §15);
  - later: multiple facilities / multi-hop routes.
- **16.3 Surface + at-grade anchor resolution (R).** For arterial facilities, resolve `from/to`
  to **at-grade intersection** nodes (node on the facility incident to a link named by the anchor) —
  simpler than the freeway gore/merge path — and handle a freeway-interchange anchor on a surface
  street (where the arterial meets the ramps).
- **16.4 Conversational disambiguation (P+R+UI).** When a name/anchor matches multiple candidates
  ("Harrison Ave" vs "North Harrison Ave"; several interchanges), return ranked candidates, **render
  them on the map**, and ask the user to pick — a multi-turn clarify loop in the chat panel (§15).
  Today ambiguity is only flagged passively.
- **16.5 Interactive link selection (UI, new phase).** Build a selection set **directly on the map**
  — click links to add/remove, box/lasso select, shift-click ranges — independent of NL. The result
  is the same selection object (highlight, emit fragment, zoom-to-selection). Complements NL
  selection and feeds the future edit track.

**Phasing:** slot as P5 (16.1–16.3 richer NL + surface/whole/filter), P6 (16.4 conversation),
and a dedicated **Pi — Interactive selection** (16.5) that can land early since it's self-contained
and high-value for QA.
