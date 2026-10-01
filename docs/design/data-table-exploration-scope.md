# Data-table exploration view — scoping doc

Status: **Phase 0 + Phase 1 BUILT** (+ early Phase-2 cross-linking) · Date: 2026-09-30 · Owner: viz

> **Implemented (2026-10-01).** Server-side paged/sorted/filtered table access
> (`gmnspy/viz/tables.py`, no raw SQL — passes `lint_no_sql`) behind new endpoints
> `/api/tables`, `/api/table/{name}/schema`, `/api/table/{name}/rows`
> (offset/limit/sort/dir/filter/ids). `build_app(..., tables=…)` takes extra GMNS
> frames; `gmnspy viz` auto-exposes lanes/segments/zones/movements/link_tod when
> present. Frontend: header **Map / Split / Table** segmented control (persisted in
> `localStorage`), left rail of tables with row counts, a hand-rolled paged grid
> (sortable headers, per-column `contains` filters, Prev/Next pager, geometry
> excluded). **Cross-linking (Phase 2 start):** click a link row → highlight +
> `fitSelection` on the map + fill the detail panel; click a node row → anchor +
> flyTo; a "Filter to map selection" toggle passes `CUR.linkIds`/anchor node ids as
> `ids`. Tests: `test_viz_tables.py` (11) + 8 endpoint tests in `test_viz_server.py`.
> **G1 + G2 now DONE (2026-10-01).** Engine push-down is wired: `datagrove.Table`
> gained `order_by`/`limit(offset)` (all engines) and `dataset.filter.filter_rows`
> (ibis-first attribute filter, no raw SQL); `viz.tables.page_table` accepts a lazy
> `Table` and pushes filter/sort/page/count to the engine (duckdb over parquet
> materialises only the one page), with the pandas-frame path kept as fallback. The
> viz CLI now passes the large child tables (lanes/segments/zones/movements/link_tod)
> as lazy Tables; link/node stay pandas for the map binary. Proven at parity with the
> pandas path on the ibis/duckdb engine.
> Still to do: shared `SELECTION` store + bidirectional hover (full Phase 2), the
> structured query builder / guarded SQL console (Phase 3), draggable split divider,
> and the zoom-driven GMNS sub-table *map* layers (turning movements/segments/lanes/
> zones/signals/TOD) — see the viewer PRD §6 "Zoom-driven GMNS sub-table layers".

Goal: let a user flip between the deck.gl map and the underlying GMNS tables
(`link`, `node`, `lane`, `segment`, …), inspect / sort / filter large tables,
and cross-link the two (table row → highlight on map; map selection → filter
the table). Think CARTO linked widgets / a data grid, over the DuckDB/parquet
data gmnspy already loads.

This doc evaluates the options, recommends an approach + concrete tech, and
lays out a phased plan. **No code is changed by this doc.**

---

## 1. What we have today (grounding)

- **Viewer stack.** `viz/server.py::build_app(links, nodes, …)` is a FastAPI app
  that serves the network as a binary typed-array payload (`/api/network.bin`),
  index-aligned tooltip attrs (`/api/network.attrs.json`), a per-link detail
  row (`/api/link/{id}`), styleable columns (`/api/properties`,
  `/api/property/{name}`), and NL selection (`/api/select`). The frontend
  (`viz/templates/index.html`) is a **single vanilla-JS page**, deck.gl +
  MapLibre from CDN, no build step, no framework.
- **The viz server only sees two materialized pandas frames.** `cli/commands/viz.py`
  does `net.links.to_pandas()` / `net.nodes.to_pandas()` and passes those to
  `build_app`. It does **not** currently receive the `Network`/`Package` or the
  live engine, so it has no access to `lane`, `segment`, `zone`, the signal
  family, etc., and no lazy DuckDB handle to page against.
- **Data layer is engine-agnostic and lazy.** `Network` (subclass of
  `datagrove.dataset.Package`) exposes named accessors for every canonical GMNS
  table (`links`, `nodes`, `lanes`, `segments`, `segment_lanes`, `zones`,
  `movements`, `signal_*`, `link_tod`, …). Each returns a datagrove `Table`
  wrapping a lazy expr. `Table` already offers, **across ibis/duckdb, pandas and
  polars engines**: `.filter(predicate)`, `.select(*cols)`, `.head(n)`,
  `.count()`, `.columns`, `.to_pandas()` / `.to_polars()`. The default engine is
  ibis-on-duckdb (`IbisEngine`), which owns a duckdb connection and can
  `read_parquet` / `read_duckdb_table`.
- **Selection model.** The frontend keys everything on `link_id`: `ID2IDX`
  maps id→buffer index, `CUR.linkIds` drives the highlight `PathLayer`, and
  `fitSelection()` zooms to it. `node_id` anchors are already rendered. This is
  the cross-linking substrate we reuse.
- **Hard architectural rule.** `scripts/lint_no_sql.py` (CI) forbids raw SQL
  string literals anywhere under `packages/*/…` **except** `ibis_engine.py`,
  because raw SQL locks the project into a dialect and bypasses lazy-ibis
  composition. This is decisive for the SQL-console option (§4b).

Two gaps fall out immediately, independent of which grid we pick:

- **G1 — the view needs the whole package, not two frames.** To browse arbitrary
  GMNS tables and page server-side, `build_app` must receive the `Network`
  (or a small table-provider handle), not pre-materialized `links`/`nodes`.
- **G2 — `Table` has `filter`/`select`/`head`/`count` but no `order_by` or
  `offset`.** Server-side sort + paging needs those two primitives added to the
  engine-agnostic `Table` surface (small, high-value, benefits the whole
  library — not viz-specific).

---

## 2. Options at a glance

| Option | What | Verdict |
|---|---|---|
| (a) Virtualized data-grid panel per table, fed by a **server-side paged/sorted/filtered** endpoint | primary UX | **Recommended** |
| (b) SQL console over the loaded network | power-user escape hatch | **Phase 3, opt-in, guarded, ibis-engine only** |
| (c) Linked / cross-filtered table ↔ map on the existing `link_id`/`node_id` model | the "linked widgets" payoff | **Recommended, phased in with (a)** |
| duckdb-wasm (query parquet in the browser) | alternative architecture | **Not primary; keep for a future static-export mode** |
| Datasette | drop-in table explorer | **Rejected** (separate SQLite-centric app, wrong fit) |
| lonboard / anywidget | notebook path | **Complementary, not this view** |

---

## 3. Option (a) — server-side paged grid  ★ recommended core

### 3.1 Endpoints (new, additive)

All engine-agnostic — built on the datagrove `Table` API, **no raw SQL**, so
they work whether the active engine is ibis/duckdb, pandas, or polars. DuckDB
does the paging/sorting/filtering under the hood when ibis is active, so a
million-row `lane` table never fully crosses into the browser.

```
GET /api/tables
    → [{ "name": "link", "rows": 812_345, "columns": [...] }, ...]
      (canonical GMNS tables present in this Network; count is lazy .count())

GET /api/table/{name}/schema
    → { "name", "columns": [{ "name", "dtype", "kind": "num|str|bool|geom" }],
        "primary_key": "link_id", "rows": <int> }

GET /api/table/{name}/rows
      ?offset=0&limit=100
      &sort=facility_type&dir=asc            # server-side sort
      &filter=<compact filter spec>          # see 3.2
      &ids=<id,id,...>                        # cross-filter from map (opt.)
      &bbox=minx,miny,maxx,maxy              # cross-filter from viewport (opt.)
    → { "name", "offset", "limit", "total": <filtered count>,
        "columns": [...], "rows": [[...], [...]] }   # column-oriented or row arrays
```

Response is compact (arrays, not per-row objects with repeated keys), mirroring
the existing binary/attrs philosophy of `buffers.py`. `total` is the filtered
row count so the grid can render a correct scrollbar/pager without holding the
data.

Implementation sketch (server-side, engine-agnostic):

```python
tbl = network.table(name)              # datagrove Table (lazy)
if filter_spec: tbl = tbl.filter(compile_predicate(filter_spec))
if ids:         tbl = tbl.filter(lambda t: t[pk].isin(ids))
total = tbl.count()                    # lazy count, pushed to duckdb
page = tbl.order_by(sort, dir).offset(offset).limit(limit).to_pandas()
```

`order_by` / `offset` are the two primitives to add to `Table` (G2). They map
cleanly to ibis (`expr.order_by`, `expr.limit(n, offset=k)`), pandas
(`sort_values` + `iloc`), and polars (`sort` + `slice`) — a thin wrapper per
engine, consistent with the "hand-roll thin wrappers over heavy deps" memory.

### 3.2 Filter spec (engine-agnostic, no SQL)

A small JSON/querystring predicate language the server compiles to `Table.filter`
lambdas — never a SQL string, so `lint_no_sql` stays green and every engine
supports it:

```
[{ "col": "facility_type", "op": "eq",  "val": "motorway" },
 { "col": "lanes",         "op": "gte", "val": 3 },
 { "col": "name",          "op": "contains", "val": "Miami" }]
```

Ops: `eq, ne, lt, lte, gt, gte, in, contains, isnull, notnull`. This is enough
for column header filters and covers the common "show me the arterials with ≥3
lanes" case. It also gives us server-side validation (reject unknown columns/ops)
for free — no injection surface, unlike a raw-SQL box.

### 3.3 Grid library — choice + licenses

The endpoint does the heavy lifting (the browser holds ~one page, 50–200 rows),
so we do **not** need a million-row client virtualizer for the common path. The
existing page is vanilla JS with no build step, and the project's memory is
explicit: **avoid over-engineering, lean deps, hand-roll thin wrappers.**

Candidates (all permissive / Apache-2.0-compatible unless noted):

| Lib | License | Model | Fit here |
|---|---|---|---|
| **TanStack Table** (+ TanStack Virtual) | **MIT** | headless, framework-agnostic (vanilla/React/Vue/Svelte) | Best headless option; no framework required, you render the DOM. Virtual is a separate MIT pkg. |
| **glide-data-grid** | **MIT** | canvas, React-only | Fastest for huge client-side tables (Streamlit uses it); but pulls in React — off-pattern for this page. |
| **Perspective** (FINOS) | **Apache-2.0** | WASM + Arrow, own `<perspective-viewer>` web component, pivot/agg | Powerful analytical grid+charts, license ideal; heavy C++/WASM payload, more than we need for row browsing. |
| **AG Grid Community** | **MIT** | full grid, framework wrappers | Capable, but the **Server-Side Row Model is Enterprise (commercial)** — Community only has the client/infinite row model. Heavier; avoid the enterprise trap. |
| Handsontable | **non-permissive** (commercial for business use) | — | **Rejected** on license. |

**Recommendation:** for **Phase 1**, a **thin hand-rolled table component**
(~150 lines) rendering the paged endpoint: sortable headers (fire endpoint
re-fetch), per-column filter inputs, a pager/"load more". Because paging is
server-side, this is genuinely simple and matches the lean-deps ethos. **Adopt
TanStack Table (headless, MIT) in Phase 2** only if/when client-side niceties
(column resize/reorder/pinning, grouping) justify it — it drops into the vanilla
page without a framework. Keep **Perspective (Apache-2.0)** on the shelf as the
Phase-3 option if users want in-browser pivot/aggregation over a page of Arrow.

This staging means we never take a dependency until the UX demands it, and every
candidate we'd escalate to is MIT or Apache-2.0.

### 3.4 Large-table performance strategy

- **Server-side everything** (page/sort/filter/count) via lazy ibis→duckdb; the
  browser never receives more than one page. This is the single most important
  decision and it's free given the engine already loaded the data into duckdb.
- **Lazy counts, cached.** `total`/row-count per table via `Table.count()`;
  memoize per (table, filter) with `functools.lru_cache` like the existing
  `_bin()`/`_attrs()` caches in `server.py`.
- **Projection.** Only fetch requested/visible columns (`Table.select`) — GMNS
  `lane`/`segment_lane_tod` can be wide.
- **Keyset (seek) paging** for very large offsets: order by primary key and
  page with `pk > last_seen` instead of large `OFFSET` (DuckDB handles moderate
  offsets fine; add keyset only if profiling shows deep-page cost).
- **Geometry column** excluded from grid payloads by default (it's WKT and huge);
  show a "geometry present" chip, render it on the map instead.
- **Debounce** filter typing (~250 ms) and cap `limit` (e.g. ≤ 500) server-side.

---

## 4. Option (b) — SQL console

### 4.1 The tension

A free-text SQL box is the most flexible power-user tool, but it fights two
project invariants:

1. **`lint_no_sql`** forbids SQL string literals in source. A *runtime*
   user-typed query is not a source literal, so the lint doesn't technically
   fire — but the spirit of the rule (don't dialect-lock, don't bypass the
   engine abstraction) means a raw-SQL console is inherently **duckdb-only** and
   must be **disabled when the active engine is pandas/polars**.
2. Engine-agnosticism: results would only be reproducible on the ibis/duckdb
   engine.

### 4.2 If we do it — safety model (read-only)

Run through the one sanctioned SQL path (`IbisEngine`'s duckdb backend / `.sql()`),
never string-built elsewhere, and gate hard:

- **Read-only connection.** Open the duckdb connection for the console with
  `access_mode=READ_ONLY` (or a fresh read-only ATTACH of the parquet/duckdb
  source); no writes reach the working data.
- **Statement allowlist.** Parse and permit only `SELECT` / `WITH` / `PRAGMA`
  (single statement); reject `INSERT/UPDATE/DELETE/ATTACH/COPY/INSTALL/LOAD/
  CREATE/PRAGMA disable_…`. DuckDB's `INSTALL/LOAD` and `COPY (… TO 'file')` are
  the dangerous ones — deny explicitly.
- **Forced `LIMIT`** wrapper (`SELECT * FROM (<user query>) LIMIT 1000`) and a
  **statement timeout** / interrupt.
- **Localhost bind only.** The console is enabled only when the server is bound
  to `127.0.0.1` (the viz default) and behind an explicit `--enable-sql` flag,
  **off by default**. Never exposed on a public bind (datagrove already has an
  `is_public_bind` check to reuse).
- **No parameters from untrusted callers**; the query is the user's own, typed
  locally.

### 4.3 Engine-agnostic alternative (preferred long-term)

A **structured query builder** — pick table, columns, filters (§3.2), group-by,
aggregations — that **compiles to ibis expressions**, not SQL text. This gives
80% of the console's value, stays engine-agnostic, reuses the filter spec, and
needs no allowlisting because the user can't express anything unsafe. Recommend
building this before/instead of a raw-SQL box, and treating raw SQL as the
final, clearly-labeled "advanced, duckdb-only" escape hatch.

---

## 5. Option (c) — linked / cross-filtered table ↔ map  ★ recommended

Reuse the existing `link_id` / `node_id` selection model — no new selection
concept needed.

**Table row → map highlight.** Row exposes its pk. On click:
- `link` table row → set `CUR.linkIds = [link_id]`, `refresh()`, `fitSelection()`
  (all already exist in `index.html`). Also load `/api/link/{id}` into the
  existing detail panel.
- `node` table row → add a `node_id` anchor (anchors layer already renders).
- child tables (`lane`, `segment`, `movement`, …) carry a `link_id`/`node_id`
  foreign key → highlight the parent link/node. (`segment` has from/to; map to
  the owning link.)

**Map selection → table filter.** When the map has a selection (NL `/api/select`
result, a clicked link, or a future lasso/bbox), pass its ids to the grid:
`/api/table/{name}/rows?ids=…`, or `?bbox=…` from the current viewport
(`map.getBounds()`), and the table shows exactly those rows. A "filter table to
map selection" toggle wires `CUR.linkIds` → the active grid's `ids` param.

**Shared selection store.** Introduce one small `SELECTION = { linkIds, nodeIds,
bbox }` object in the frontend that both the map layers and the grid subscribe
to, so map↔table stays in sync in both directions (this is the "linked widget"
core). Bidirectional highlight (hovering a row flashes the link, hovering a link
flashes the row) is a Phase-2 polish on the same store.

---

## 6. Rejected / complementary architectures

- **duckdb-wasm (MIT).** Query parquet directly in the browser, no server paging.
  Genuinely attractive for a *static export* (host the parquet + HTML, no Python
  process). But for the live `gmnspy viz` server it **duplicates the engine**
  already running in Python, ships a multi-MB WASM bundle, and diverges from the
  server-authoritative ibis/duckdb we already loaded. **Decision:** server-side
  (reuse the loaded duckdb via ibis) is primary; keep duckdb-wasm as a future
  "export static viewer" mode where there is no server.
- **Datasette (Apache-2.0).** A full, excellent table-explorer app — but it's a
  separate SQLite-centric server with its own UI; embedding it beside the deck.gl
  SPA means two apps, and it doesn't natively target duckdb/parquet. **Rejected**
  for this view (worth citing as prior art for the SQL/table UX).
- **lonboard / anywidget (both MIT).** The notebook path: lonboard renders deck.gl
  in Jupyter via anywidget, pairs naturally with a pandas/Arrow table cell.
  **Complementary** — a good story for `gmnspy` in notebooks, not a replacement
  for the standalone web view. Worth a small `notebook` helper later.

**License summary (all fit Apache-2.0):** TanStack Table/Virtual — MIT;
glide-data-grid — MIT; Perspective — Apache-2.0; AG Grid **Community** — MIT
(**Enterprise/Server-Side Row Model — commercial, avoid**); duckdb-wasm — MIT;
Datasette — Apache-2.0; lonboard — MIT; anywidget — MIT; Arquero (JS dataframe,
if ever needed) — BSD-3. **Avoid:** Handsontable (non-permissive), AG Grid
Enterprise.

---

## 7. UX for flipping map ↔ table

Reject a floating overlay (bad for wide/tall tables). Recommend a **top-level
view mode** in the header — a segmented control:

```
[ Map ]  [ Split ]  [ Table ]        <- header, next to the utterance box
```

- **Map** — today's full-bleed map (unchanged default).
- **Table** — full-width data view: a **left rail listing GMNS tables** present
  in this Network (`/api/tables`, with row counts) + the grid for the selected
  table; the utterance/selection state persists.
- **Split** — map on top, grid docked below (draggable divider, remembered
  height). This is the "linked widgets" mode where cross-filtering shines.

Rationale: the current layout is a CSS grid (`#app`), so adding a bottom docked
region / view-mode swap is a contained change to `index.html` — no framework.
The side panel (details/anchors/fragment/diagnostics) stays as the inspector in
all modes. Persist the chosen mode + split height in `localStorage`.

---

## 8. Recommendation (summary)

1. **Primary: server-side paged/sorted/filtered grid (§3)** on new endpoints
   built over the **engine-agnostic datagrove `Table` API — no raw SQL**. DuckDB
   pages under the hood; the browser holds one page.
2. **Grid: hand-rolled thin table first (lean deps); escalate to TanStack Table
   (headless, MIT) only when client-side interactions demand it.** Perspective
   (Apache-2.0) reserved for pivot/agg later.
3. **Cross-linking (§5)** on the existing `link_id`/`node_id` model via a small
   shared `SELECTION` store — the payoff feature.
4. **SQL: no raw-SQL box in v1.** Ship an engine-agnostic **structured query
   builder** that compiles to ibis. If a raw console is later demanded, it's
   **opt-in (`--enable-sql`), localhost-only, read-only, SELECT/WITH allowlist,
   forced LIMIT + timeout, ibis/duckdb engine only.**
5. **UX: header view-mode segmented control (Map / Split / Table)** + left rail
   of GMNS tables; no overlay. Persist in `localStorage`.
6. Reserve **duckdb-wasm** for a future static-export viewer; **lonboard** for
   the notebook story.

### Prerequisite refactors (small, reusable)

- **G1:** pass the `Network` (or a thin table-provider) into `viz.build_app`
  instead of pre-materialized `links`/`nodes`, so the view can reach every GMNS
  table lazily. Keep the existing binary/attrs endpoints (they can materialize
  `links`/`nodes` from the Network internally).
- **G2:** add `order_by(col, dir)` and `offset(n)` (or `limit(n, offset=k)`) to
  the datagrove `Table` API — one thin wrapper per engine. Benefits the whole
  library, not just viz.

---

## 9. Phased plan

**Phase 0 — enablers (prereq).**
- G1: `Network`-aware `viz.build_app`.
- G2: `Table.order_by` + `Table.offset`/`limit(offset=…)` across engines + tests.
- Filter-spec compiler (`§3.2`) → `Table.filter`, with column/op validation.

**Phase 1 — read-only table view (MVP).**
- `/api/tables`, `/api/table/{name}/schema`, `/api/table/{name}/rows`
  (offset/limit/sort/filter), lazy cached counts.
- Header view-mode control (Map / Table); left rail of GMNS tables; hand-rolled
  paged grid with sortable headers + per-column filters.
- Geometry excluded from grid payloads.

**Phase 2 — linked widgets.**
- Split view; shared `SELECTION` store.
- Row → map highlight (reuse `CUR.linkIds`/anchors/`fitSelection`); map selection
  / NL result / viewport `bbox` → table `ids`/`bbox` filter.
- Bidirectional hover highlight. Foreign-key mapping for child tables.
- Adopt TanStack Table (MIT) if column resize/reorder/pin/group is wanted.

**Phase 3 — power tools (opt-in).**
- Structured query builder (group-by/agg, compiles to ibis).
- Optional guarded raw-SQL console (localhost, read-only, allowlist, LIMIT,
  ibis-engine only) behind `--enable-sql`.
- Consider Perspective (Apache-2.0) for in-browser pivot over a page of Arrow.
- CSV/parquet export of the current filtered view (reuse engine `write_*`).

**Later / optional.**
- duckdb-wasm static-export viewer (no server).
- lonboard/anywidget notebook helper.

---

## 10. Open questions

- **Foreign-key map** GMNS child table → parent link/node for cross-highlight:
  derive from the vendored GMNS spec (`gmnspy.spec`) rather than hardcoding?
- **Composite/nonexistent PKs** (e.g. `lane` keyed by `link_id`+`lane_id`): the
  `ids` cross-filter needs a per-table pk definition (extend `/schema`).
- **Count cost** on very large tables on the pandas engine (no push-down) — cap
  or show "≥N" when count exceeds a threshold?
- **Keyset paging** — implement now or defer until profiling shows deep-`OFFSET`
  cost on real DuckDB data?
