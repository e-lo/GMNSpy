# Changelog — gmnspy

All notable changes to the `gmnspy` package. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is [Semver](https://semver.org/).

This file is for the **gmnspy** package only. The underlying generic engine `datagrove` keeps its own CHANGELOG at [`packages/datagrove/CHANGELOG.md`](../datagrove/CHANGELOG.md).

## [Unreleased]

(Reserved for changes between the most recent release and the next.)

## [1.0.0-beta.2] — TBD

Second public preview. The big theme: an **interactive map viewer** with
an integrated **edit log** so you can triage findings in a browser, apply
the fixes deterministically in Python, and save.

### Added

- **`gmnspy.map` module** — embeddable interactive network viewer.
  - `NetworkMap` — reusable component class. Any host page (validation
    report, notebook, custom dashboard) can include shared head assets
    (`NetworkMap.head_assets()`) once and drop in one or more per-instance
    body fragments (`instance.body_fragment()`). Each instance carries a
    UID so multiple maps coexist on one page.
  - `NetworkMap.to_html()` — full standalone HTML doc.
  - `NetworkMap._repr_html_()` — iframe-isolated Jupyter render.
  - `gmnspy.map.render_network_html(net, issues=None, ...)` — thin
    convenience over `NetworkMap.to_html()`.
  - `gmnspy.map.render_validation_html(net, report, ...)` — full
    validation report page composing a NetworkMap with the findings
    table.
  - Toggleable layers (links, nodes; extensible for zones / segments /
    movements). Hover tooltips on every element show its GMNS row
    columns. Popups on findings carry `Fix locally` / `Fix upstream
    (OSM) →` / `Show error in table`.
- **Edit log Phase 1** — `gmnspy.map.edits`:
  - `Edit`, `EditLog`, `AppliedEdit`, `SkippedEdit`, `ApplyResult`
    dataclasses.
  - `load_edit_log(path)` / `dump_edit_log(log, path)` — YAML round-trip.
  - `apply_edits(net, log) → ApplyResult` — deterministic replay with
    PK-indexed row lookup, drift check (`from_value` vs current), and
    per-edit `skipped` reasons.
  - **On-disk format is `network-wrangler` ProjectCard.** Each session
    serialises to a single ProjectCard with `changes[]` of
    `roadway_property_change` entries. GMNS `link_id` maps to
    `model_link_id` in the facility selector; per-cell values live under
    `property_changes.<column>.{existing, set}`. Node property changes
    emit with the same shape via `model_node_id` (gmnspy extension —
    standard ProjectCard has no first-class node-property-change type).
- **CLI output flags** on `gmnspy validate`:
  - `--html` writes the new map+table viewer (gracefully falls back to
    the datagrove table-only HTML when `[reports]` is missing, so
    `--html` always produces a file).
  - `--csv` writes a flat findings table.
  - `--xlsx` writes a single-sheet workbook (requires `[reports]`).
- **`gmnspy.osm` deep-link helpers** — `osm_edit_url(osm_id, *, kind,
  editor)`, `issue_osm_edit_url(issue, network, *, editor)`. Now
  detection is column-based (`osm_way_id` on link, `osm_node_id` on
  node), so ANY network carrying those columns gets Edit-in-OSM
  links — regardless of whether it was built via `gmnspy.osm.build`.
- **Bundled Leavenworth fixture rebuilt.** Built from the full OSM city
  polygon via `osmnx.graph_from_place("Leavenworth, Washington, USA")`
  instead of a 600m centroid buffer. Every link row now carries
  `osm_way_id`, every node row `osm_node_id`, so Edit-in-OSM works on
  the bundled fixture out of the box.
  - Row counts: node 75 → 121, link 214 → 339, lane 280 → 429.
  - Total fixture size ~700KB → ~2.7MB (still under the 5MB wheel cap).
- **New cookbook recipes**:
  - `view-your-network.md` — the standalone map, no validation.
  - `fix-findings.md` — the full triage → YAML → apply → save flow.

### Changed

- **`gmnspy.osm.__init__` is now lazy.** Importing the package no longer
  eagerly requires the `[osm]` extra. `osm_edit_url` /
  `issue_osm_edit_url` are dep-free helpers and load without
  `requests` / `pyyaml`. `build_network_from_osm` /
  `network_from_records` still need `[osm]` and surface the same
  helpful `ImportError`.
- **`[reports]` extra now includes `pyyaml>=6`** for the edit-log
  YAML round-trip.

### Deprecated

- `gmnspy.reports.render_network_html` / `render_validation_html` —
  moved to `gmnspy.map`. The old imports still work via re-export but
  emit a `DeprecationWarning`. `gmnspy.reports.write_findings_csv` /
  `write_findings_xlsx` stay put.

### Known limitations (Phase 2)

- Edit log only supports `kind: fix` (per-cell value changes). Row
  additions, row deletions, and schema changes are deferred. The YAML
  format reserves ProjectCard `kind: modification` for future use.
- No bulk-fix UI in the browser — bulk fixes go through Python
  directly.
- The map's marker layer has no clustering; past ~5k markers Leaflet
  will slow.

## [1.0.0-beta.1] — TBD

First public preview of GMNSpy v1.0. The entire codebase is a rewrite from v0.3.5 — there is no in-place upgrade path; see the [migration guide](docs/migration/v0.3-to-v1.0.md).

This is a **beta**: API surface is stable enough to build against and most user-facing rough edges have been smoothed, but we expect bug reports + small breaking changes before 1.0.0 GA.

### Headline changes vs v0.3.x

- **New architecture.** GMNS-specific code now sits on top of a generic Frictionless engine ([`datagrove`](https://github.com/e-lo/GMNSpy/tree/main/packages/datagrove)) shipped as a separate PyPI package. The intent: future spec toolkits (GTFSpy, etc.) reuse the engine.
- **Multi-version GMNS support out of the box.** Spec versions `0.95`, `0.96`, `0.97` ship side-by-side. `DEFAULT_SPEC = "0.97"`. Override per call: `gmnspy.read(..., spec_version="0.96")`.
- **Regional-scale performance.** Lazy ibis + DuckDB by default. Predicates push down to SQL. Validation and scope operations stream rather than materialising the whole network.
- **Three usage modes, one core.** CLI (`gmnspy <command>`), notebook (`Network._repr_html_`), and programmatic (`gmnspy.read`, `gmnspy.validate`) all share the same underlying objects.

### New features

- **`gmnspy.read(source)`** + **`gmnspy.validate(source)`** — the documented I/O front door. Accepts paths / URLs / loaded Networks.
- **`Network.from_source()`** with multi-version spec auto-load.
- **`gmnspy validate`** CLI with `--html <path>` for interactive single-file reports + `--spec` for version override.
- **`gmnspy quality`** — data-quality rule pack beyond spec compliance: high-speed-on-residential, disconnected components, lane-count mismatch, sharp-angle bends, implausible v/c, etc. Plugin-extensible via the `datagrove.quality.rules` entry point.
- **`gmnspy.scope`** — network-aware scope ops: `from_nodes`, `from_node`, `from_link`, `from_point`, `connected_component`, `from_zone`. Chainable. Returns a scoped `Network` with FK chain pre-filtered.
- **`gmnspy.osm` + `gmnspy build` CLI** — build a validated GMNS network from OpenStreetMap for a bounding box, place name (city/county), or a lat/lon point + buffer. Hand-rolled Overpass + Nominatim access (no `osmnx` / `osm2gmns` dependency); maintained tag-mapping data files; produces a self-describing network with a `config` table declaring units. Behind the `gmnspy[osm]` extra (`requests`, `pyyaml`).
- **`gmnspy.graph` + `gmnspy[graph]` extra** — scipy-CSR routing engine: connectivity (weak / strong components), isochrones, shortest paths, multi-source distance buffer, nearest-node snap. Builds from a `Network` or directly from parquet/duckdb/polars/in-memory sources. This is also the unified backend powering `gmnspy.semantics` + `gmnspy.scope` connectivity / network-distance ops (replacing the older `igraph`-based index).
- **`gmnspy[clean]` extra** — network editing with atomic rollback (`simplify_geometry`, `merge_close_nodes`, `remove_orphans`, `recompute_lengths`). Every edit returns an `EditResult` with diff + log entry; sessions stored as sidecar parquet.
- **`gmnspy[server]` extra** — self-hostable FastAPI server (`gmnspy server run`). Pluggable bearer-token auth. Ships `Dockerfile` + `docker-compose.example.yml`.
- **`gmnspy[mcp]` extra** — MCP server (`gmnspy mcp serve`) exposing read / describe / query / scope / validate / quality_check / edit_session tools to Claude Desktop / Claude Code.
- **`gmnspy[notebook]` extra** — interactive scope-builder ipywidget. (Basic `_repr_html_` ships in core.)
- **`gmnspy doctor`** — install diagnostic: Python version, extras installed, vendored specs, fixture loads, env vars.
- **`gmnspy bench`** — read/validate/connectivity timing.
- **Bundled Leavenworth, WA fixture** in four storage variants (CSV / parquet / DuckDB / zip-CSV) — see [`packages/gmnspy/gmnspy/fixtures/leavenworth/README.md`](gmnspy/fixtures/leavenworth/README.md) for provenance.

### AI surface

- **`--json` on every CLI command** for tool-call loops.
- **`llms.txt` + `llms-full.txt` + `ai/api-index.json`** auto-generated from docs + docstrings.
- **Five Claude Code Skills** in [`skills/`](../../skills/) — `datagrove-validate`, `gmns-author`, `gmns-validate`, `gmns-convert`, `gmns-clean`.

### Internal architecture

- **Single graph backend.** All connectivity + network-aware-scope ops (`gmnspy.semantics.connectivity`, `gmnspy.scope`, `gmnspy.quality.rules` disconnected-components, `Network.build_indexes(graph=True)`) now run on a shared `gmnspy.graph.GMNSGraph` (scipy CSR), cached once per network. The earlier `gmnspy.indexes.GraphIndex` (igraph) wrapper is retired; the `igraph` dependency is dropped (`[clean]` no longer pulls it in). `SpatialIndex` (STRtree) is unaffected.

### Quality + process

- 1285 tests passing; coverage ≥ 85% on each package (gated in CI).
- Two automated contract tests assert every documented `gmnspy.X` / `datagrove.X` symbol AND every documented `gmnspy <cmd> --flag` actually exists — prevents doc-vs-code drift.
- Per-package CI matrix (Python 3.11 / 3.12 / 3.13 × Linux / macOS), import-linter contracts, raw-SQL lint, doctest-modules sweep, htmlproofer.

### Breaking changes from v0.3.x

**Everything.** v1.0 is a clean rewrite — no `_legacy/` shims, no DeprecationWarning bridges. The [migration guide](docs/migration/v0.3-to-v1.0.md) maps the old API surface to the new. The biggest moves:

- `gmnspy.read_gmns_network(path)` → `gmnspy.read(path)` (auto-detects format) or `Network.from_source(path)`.
- `gmnspy.schema.read_schema(path)` → `gmnspy.load_gmns_spec(version="0.97")`.
- All single-file imports under `gmnspy.{schema,validation,utils}` → moved to `datagrove.spec`, `datagrove.validation`, `datagrove.utils.markdown`.
- Pandas DataFrames are no longer the lingua franca — operations are lazy ibis expressions; call `.to_pandas()` / `.to_polars()` at the boundary.

### Known limitations going into beta

- `gmnspy.bench` is CLI-only — no programmatic API yet (tracked for v1.1).
- HTML report doesn't yet embed a Vega-Lite map view for geo-located issues.
- `gmnspy.clean` lacks `split_link_at_node` and `snap_to_reference` (tracked for v1.1).

### Compatibility

- Python 3.11, 3.12, 3.13.
- macOS + Linux (Windows community-supported only; CI doesn't cover it).
- Optional extras: `osm`, `graph`, `clean`, `server`, `mcp`, `notebook`, `all`.

[Unreleased]: https://github.com/e-lo/GMNSpy/compare/gmnspy-v1.0.0-beta.1...HEAD
[1.0.0-beta.1]: https://github.com/e-lo/GMNSpy/releases/tag/gmnspy-v1.0.0-beta.1
