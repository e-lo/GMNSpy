# Changelog — gmnspy

All notable changes to the `gmnspy` package. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is [Semver](https://semver.org/).

This file is for the **gmnspy** package only. The underlying generic engine `datagrove` keeps its own CHANGELOG at [`packages/datagrove/CHANGELOG.md`](../datagrove/CHANGELOG.md).

## [Unreleased]

(Reserved for changes between the most recent release and the next.)

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
- Optional extras: `clean`, `server`, `mcp`, `notebook`, `all`.

[Unreleased]: https://github.com/e-lo/GMNSpy/compare/gmnspy-v1.0.0-beta.1...HEAD
[1.0.0-beta.1]: https://github.com/e-lo/GMNSpy/releases/tag/gmnspy-v1.0.0-beta.1
