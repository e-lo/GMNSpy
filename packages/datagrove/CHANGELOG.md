# Changelog — datagrove

All notable changes to the `datagrove` package. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is [Semver](https://semver.org/).

This file is for the **datagrove** package only. `gmnspy` (which depends on datagrove) keeps its own CHANGELOG at [`packages/gmnspy/CHANGELOG.md`](../gmnspy/CHANGELOG.md).

## [Unreleased]

(Reserved for changes between the most recent release and the next.)

## [0.1.0-beta.1] — TBD

First public preview of datagrove. This is a **beta**: API surface is stable enough to build against but we expect bug reports + small breaking changes before 0.1.0 GA.

### What this release covers

- Generic Frictionless Data Package engine with three interchangeable backends — ibis (DuckDB-backed; default), polars, pandas. Switch per call.
- I/O front door: `datagrove.read(source, *, engine=None, spec=None, ...)`. Auto-detects CSV / Parquet / DuckDB / zip-CSV from local paths or `s3://` / `https://` / `duckdb://` URLs.
- Four-pass validator returning a single `ValidationReport`: structural, schema, foreign-key, sync-state. Rich console / JSON / interactive single-file HTML output.
- Generic `editing/` framework with atomic rollback + audit log — used by `gmnspy.clean`.
- Spatial scope primitives in `datagrove.dataset.view`: `from_bbox` / `from_polygon` / `from_geometry_buffer`. Predicates push down to DuckDB SQL where possible.
- Self-hostable FastAPI primitives (`datagrove.api`) and MCP server primitives (`datagrove.mcp`) — assembled into concrete apps by gmnspy.
- Generic data-quality rule framework + entry-point plugin discovery.
- `datagrove` CLI (`validate`, `info`, `convert`) with `--json` on every command for agent / pipeline consumption.
- Cost-model gating on long operations with `--yes` / `DATAGROVE_AUTO_APPROVE=1` bypass for non-interactive use.
- AI artifacts: `llms.txt`, `llms-full.txt`, `ai/api-index.json` regenerate on every docs build.

### Architectural defaults

- Lazy by default. `Package.from_source(...)` returns a Package whose tables are unmaterialised ibis expressions until you `.collect()` / `.to_pandas()` / write.
- No raw SQL outside `datagrove.engines.ibis_engine` (enforced by `scripts/lint_no_sql.py` in CI).
- datagrove never imports gmnspy (enforced by `import-linter`).

### Known limitations going into beta

- `Package.from_source()` mis-dispatches `.csv.zip` to the CSV adapter — use `csv_dir()` or `parquet_dir()` for now. Fix tracked.
- `datagrove.quality.run()` is named `run_quality()` — alias coming.
- HTML report renderer doesn't yet embed map view for geo-located issues.

### Compatibility

- Python 3.11, 3.12, 3.13.
- Optional extras: `polars`, `pandas`, `s3`, `gcs`, `azure`, `keyring`, `mcp`.

### Migration from pre-1.0 GMNSpy

datagrove is a new package; nothing to migrate from. See [`packages/gmnspy/docs/migration/v0.3-to-v1.0.md`](../gmnspy/docs/migration/v0.3-to-v1.0.md) if you're moving from old GMNSpy.

[Unreleased]: https://github.com/e-lo/GMNSpy/compare/datagrove-v0.1.0-beta.1...HEAD
[0.1.0-beta.1]: https://github.com/e-lo/GMNSpy/releases/tag/datagrove-v0.1.0-beta.1
