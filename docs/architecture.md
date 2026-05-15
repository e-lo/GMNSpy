# Software architecture — GMNSpy v1.0 + datagrove v0.1

This document is the **single source of truth** for the software design of the v1.0 refactor. It exists so that any contributor — human or AI sub-agent — landing in the repo can pick up cold and make decisions consistent with the rest of the work.

For the **GMNS data model** (link/node/lane/etc. ER diagrams), see [gmns-data-model.md](gmns-data-model.md). For the full PRD with personas, requirements traceability, and roadmap, see [PRD.md](PRD.md) (written in Phase 4 task 4.15).

---

## 1. Mission

GMNSpy is a Python toolkit for the [General Modeling Network Specification (GMNS)](https://github.com/zephyr-data-specs/GMNS), the Zephyr Foundation's open standard for routable transportation network data. v1.0 is a major rewrite of the v0.3.x alpha to deliver:

- **Regional-scale performance** — load + scope + validate Bay-Area-class networks without melting RAM or CPU
- **Modern formats** — Parquet (default persistent), DuckDB (default API download), zipped CSV, CSV; remote URLs with credentials
- **Foreign-key validation with sync-state awareness** — warn on writes when a network is mid-edit and FKs are stale
- **Network-aware scoping** — bbox + polygon + BFS-induced subgraph + network-distance buffer + spatial buffer from any link/point/node, with eager spatial+graph indexes for fast repeat queries (memory-for-compute tradeoff)
- **Data-quality warnings** beyond the spec (high-speed-residential, disconnected components, etc.) via configurable plugin pattern
- **Editing with atomic rollback + audit log** (`gmnspy[clean]`)
- **Self-hostable API server** (`gmnspy[server]`) — FastAPI + auto-OpenAPI; we ship the package + Dockerfile, not a service
- **AI accessibility** — Claude Code Skills (in-repo, git-URL install) + MCP server (`gmnspy[mcp]`); zero hosting commitment
- **Three usage surfaces** — interactive CLI, Jupyter notebook, programmatic API
- **Awesome docs** — for both human and AI consumers

Full requirements list (29 items) traces to phase tasks via the GitHub issue tree.

## 2. Repo layout (monorepo, two PyPI packages)

```
GMNSpy/                                       # git repo
├── pyproject.toml                            # uv workspace root + shared dev tooling
├── uv.lock
├── packages/
│   ├── datagrove/                            # PyPI package #1 — generic engine
│   │   ├── pyproject.toml
│   │   └── datagrove/
│   └── gmnspy/                               # PyPI package #2 — GMNS-specific (depends on datagrove)
│       ├── pyproject.toml
│       └── gmnspy/
│           └── spec/{0.95,0.96,0.97}/        # vendored upstream spec versions
├── skills/                                   # Claude Code Skills (git-URL install)
├── docs/                                     # mkdocs site (covers both packages + GMNS itself)
├── scripts/
└── .github/workflows/                        # tests / publish-datagrove / publish-gmnspy / docs / spec-sync / bench
```

**Per-package release tags:** `datagrove-vX.Y.Z`, `gmnspy-vX.Y.Z`. PyPI trusted publishing fires per-tag.

**Branch model:** `develop` is the integration branch; `refactor/v1.0` is the long-lived branch for this rewrite; per-task short branches (`refactor/v1.0/<phase>-<task>-<slug>`) merge into `refactor/v1.0` via PR. At GA: `refactor/v1.0` → `develop` → `main`.

## 3. Two packages, one principle

`datagrove` holds **generic primitives / frameworks**. `gmnspy` holds the **GMNS-specific assembly** that composes those primitives with domain knowledge. The same composition pattern applies to every cross-cutting concern:

| Concern | datagrove (generic) | gmnspy (GMNS-specific) |
|---|---|---|
| editing | `editing/` (Edit/Diff/Session/Rollback framework) | `clean/` (simplify_geometry, merge_close_nodes, …) |
| HTTP server | `api/` (FastAPI primitives, routers, OpenAPI helpers) | `server/` (assembled app, GMNS endpoints, Dockerfile) |
| MCP | `mcp/` (server primitives, tool decorators) | `mcp/` (GMNS tool registrations) |
| CLI | `cli/` (validate, convert, info, scope-spatial, describe; entry: `datagrove`) | `cli/` (read, spec, quality, clean, scope-network, index; entry: `gmnspy`) |
| Quality | `quality/` (Rule base class, plugin discovery; **no domain rules**) | `quality/` (GMNS rule pack via entry point) |
| Notebook | `notebook/` (`_repr_html_` for Package/Table/ValidationReport/EditResult) | `notebook/` (Network repr + scope widgets) |
| Validation | `validation/` (schema, structural, FK, sync-state) | (uses datagrove validation as-is) |
| Engines | `engines/` (Engine ABC + ibis/polars/pandas) | (uses) |
| I/O | `io/` (FormatAdapter ABC + csv/parquet/duckdb/zipcsv/remote) | (uses) |
| Dataset | `dataset/` (lazy `Package`, `Table`, `View`) | `network.py` (`Network` = `Package` + GMNS accessors) |
| Spec | `spec/` (Pydantic Frictionless models, multi-version loader) | `spec/<version>/` (vendored GMNS schemas) |

**Hard rule (lint-enforced via import-linter):** `datagrove` may not import from `gmnspy`. Optional-extra submodules in gmnspy (`clean`/`server`/`mcp`) may not be imported from gmnspy core modules. **No raw SQL strings** anywhere except inside `datagrove.engines.ibis_engine`.

Promotion criterion to extract `datagrove` to a separate repo: a second consumer (e.g., GTFSpy) has consumed it for ≥1 month with no breaking-change requests. Until then, monorepo.

## 4. Module map — datagrove

```
datagrove/
├── spec/         # Pydantic v2 models for Frictionless DataPackage/Resource/Schema/Field/ForeignKey/MissingValues/SharedCategory + loader (resolves $ref, shared_categories) + multi-version
├── engines/      # Engine ABC + ibis (default, duckdb backend) / polars / pandas adapters
├── io/           # FormatAdapter ABC + csv / parquet (partitioned) / duckdb / zipcsv / remote (fsspec) + credentials cascade
├── validation/   # ValidationReport + Issue (Error/Warning/Info/DataQuality) + schema_check + foreign_keys + structural + sync_state (DirtyTracker)
├── operations/   # cost_model + gating (>30s estimate, >3min approval) + pool/batch + progress (rich, notebook-aware)
├── dataset/      # Package / Table (lazy ibis-backed) / View (geographic scope)
├── reports/      # rich console / JSON / interactive single-file HTML renderers (Jinja2 + DataTables + Vega-Lite)
├── docgen/       # markdown + llms.txt + machine-readable api-index.json
├── editing/      # generic Edit / Diff / Session / Rollback framework (no domain semantics)
├── api/          # FastAPI primitives (routers, deps, OpenAPI helpers)
├── mcp/          # MCP server primitives (tool decorators, server scaffold)
├── cli/          # generic typer CLI: validate / convert / info / scope (bbox|polygon|geometry-buffer) / describe
├── quality/      # generic rule framework (Rule base class, threshold config, entry-point plugin discovery)
├── notebook/     # generic _repr_html_ for Package/Table/ValidationReport/EditResult
└── utils/        # logging / paths / hashing (blake3 for content fingerprints)
```

## 5. Module map — gmnspy

```
gmnspy/
├── spec/<version>/    # Vendored GMNS spec JSONs per supported version (0.95/, 0.96/, 0.97/, …)
├── network.py         # Network = datagrove.Package + GMNS-aware accessors (.links, .nodes, .segments, …) + add_*/update_* routed through DirtyTracker
├── semantics/         # connectivity, geometry assembly from geometry_id, TOD resolution
├── scope/             # network-aware scope ops: from_nodes, from_node, from_link, from_point, connected_component, from_zone
├── indexes/           # spatial (shapely STRtree) + graph (igraph adjacency) build/cache/load; sidecar parquet keyed on content hash
├── quality/           # GMNS rule pack: high-speed-on-residential, disconnected components, lane-count mismatch, …
├── clean/             # OPTIONAL [clean] — simplify_geometry, merge_close_nodes, snap_to_reference, …; uses datagrove.editing for rollback
├── server/            # OPTIONAL [server] — assembled FastAPI app on top of datagrove.api primitives
├── mcp/               # OPTIONAL [mcp] — assembled MCP server on top of datagrove.mcp primitives
├── cli/               # GMNS commands registered onto the datagrove typer app
├── notebook/          # Network._repr_html_ + scope-builder ipywidget; extends datagrove.notebook
└── fixtures/leavenworth/  # bundled tiny GMNS network for tests + docs
```

## 6. Defaults & key design decisions

### 6.1 Engine + I/O

- **Default engine: ibis (duckdb backend).** Lazy expressions throughout. `.to_pandas()` / `.to_polars()` are cheap converters. Per-call override: `gmnspy.read(..., engine="polars")`.
- **No raw SQL strings** anywhere except inside `datagrove.engines.ibis_engine`. Lint-enforced.
- **I/O front door:** `datagrove.read(source, *, format=None, credentials=None, engine=None, scope=None, spec=None)`. `gmnspy.read(...)` wraps with `spec=GMNS_DEFAULT`.
- **Format detection:** explicit `format=` overrides; else extension sniff (`.parquet`, `.csv`, `.csv.zip`, `.zip`, `.duckdb`); else `FormatAdapter.probe()` chain.
- **Defaults:** API/URL downloads default to **DuckDB**; persistent local writes default to **partitioned Parquet** (partition by H3 cell or zone_id, configurable).
- **Credentials cascade:** kwarg → `GMNSPY_CRED_<host>_TOKEN` env → `keyring` → `.netrc`. fsspec underneath.
- **Recommended persistent layout:**
  ```
  mynet.gmns/
    datapackage.json
    link/h3=8829a0c00b/part-0.parquet
    node/part-0.parquet
    ...
    _gmnspy_meta.json   # spec version, write timestamp, dirty flags, content hash per file
  ```

### 6.2 Memory-efficient scoping

- **Lazy by default.** `gmnspy.read(...)` returns a `Network` whose tables are unmaterialized ibis expressions. Materialization on `.to_pandas()` / `.collect()` / `.head()` / explicit consumer.
- **Spatial scopes (generic, in `datagrove.dataset.view`):** `from_bbox`, `from_polygon`, `from_geometry_buffer`.
- **Network-aware scopes (in `gmnspy.scope`):** `from_nodes(ids, path_between=True)` (BFS / shortest-path induced subgraph), `from_node(id, network_buffer="0.5mi")` (Dijkstra), `from_link(id, spatial_buffer_m | network_buffer)`, `from_point(xy, spatial_buffer_m)` (snaps + buffers), `connected_component(seed)`, `from_zone(zone_ids)`.
- **Composite + chainable:** `net.scope.from_nodes([1,2,3]).buffer_network("0.5mi").buffer_spatial(30)`.
- **Eager-index opt-in (memory-for-compute):** `net.build_indexes(spatial=True, graph=True)` builds STRtree + igraph adjacency once; subsequent scopes use them. Indexes cached as sidecar parquet keyed on content hash (auto-invalidated on edit). Auto-build heuristic: trigger when network exceeds N nodes (configurable; default 50k) AND user calls a network-aware scope op.
- **Predicate pushdown** to all other tables by FK chain (links → TOD tables, nodes → zone references, etc.). For partitioned parquet, bbox scope becomes true partition prune via duckdb pushdown — verified via `EXPLAIN` snapshot tests.
- **Partial loads:** `net.tables(["link", "node"])`. FK validation degrades gracefully with warnings on unverifiable FKs.

### 6.3 Validation + sync state

`ValidationReport` is the single object returned by all validation paths (schema + structural + FK + sync + data-quality). Severity levels: Error / Warning / Info / DataQuality. `category` field discriminates rule families. Renderers: rich console / JSON / **interactive single-file HTML** (Jinja2 + DataTables + Vega-Lite map view for geo-located issues; severity ranking; filter by table/severity/rule/category; click-to-expand row context).

**Sync state model:**
- `DirtyTracker` (in `datagrove.validation.sync_state`) records content hashes per table.
- FK validations stamp source+target hashes at validation time.
- Before any `write()` or `validate(strict=True)`: walk FK graph; if any FK's recorded hashes don't match current hashes, raise `OutOfSyncWarning` (warning by default; error under `--strict`).
- Direct DataFrame mutations bypass tracker — documented; user calls `net.invalidate("link")`.
- Auto-detection on read via `_gmnspy_meta.json` hash check.

**Data-quality framework (`datagrove.quality`):**
- `Rule` base class with `apply(net) → list[Issue]`.
- Threshold/config via Pydantic settings.
- Entry-point plugin discovery — packages register their rule packs under `datagrove.quality.rules` group.
- Run via `datagrove.quality.run(net, rules=None)` (None = all registered).
- gmnspy ships the GMNS rule pack: high-speed-residential, disconnected components, lane-count mismatch, near-duplicate nodes, sharp-angle bends, implausible v/c, missing critical-but-optional fields. Configurable thresholds; warnings not errors by default.

### 6.4 Editing + rollback

`datagrove.editing` provides the framework: `EditResult` (diff per table + log entry + visual summary), `Session` (chronological log + atomic rollback to a sidecar `_history.parquet`), `Rollback` primitives.

`gmnspy.clean` (optional `[clean]` extra) provides domain ops: `simplify_geometry(net, mode="redundant_only" | "douglas_peucker", tolerance=...)`, `merge_close_nodes(threshold_m=5)`, `remove_orphans()`, `split_link_at_node(...)`, `connect_disconnected_components(...)`, `recompute_lengths()`, `snap_to_reference(other_net)`. Each returns `EditResult` integrated with `datagrove.editing.Session`.

Edits inside `with net.session() as s:` produce a chronological log; `net.rollback(to=session_id_or_timestamp)` reverses. Audit log persists with the network.

### 6.5 Pooled operations + cost model

**Pool/batch:** `with net.batch(): ...` defers + coalesces ops, validates once on `__exit__`. Atomic on exception (state unchanged on raise). CLI `gmnspy edit` wraps an implicit batch with `:save` / `:abort`.

**Cost model (heuristic):** `est_seconds(op, n_rows, n_tables, fmt)` per op. Coefficients calibrated on the Leavenworth fixture + a synthetic ~regional fixture. Nightly bench job re-fits on Python/duckdb minor releases.

**Gating:**
- `<30s` → run silently
- `30s ≤ est < 180s` → emit estimate + run with progress bar
- `est ≥ 180s` → require user approval

CLI `--yes`, env `GMNSPY_AUTO_APPROVE=1`, programmatic `approve=True` skip prompts. CLI surfaces actual time after each gated op so the model self-improves over time. Documented as heuristic — not authoritative.

### 6.6 CLI

`typer` + `rich`. Two entry points:

- `datagrove …` — generic commands on any Frictionless package: `validate`, `convert`, `info`, `scope` (bbox/polygon/geometry-buffer only), `describe`.
- `gmnspy …` — extends the datagrove typer app with GMNS commands: `read`, `spec {sync|list|diff}`, `quality`, `clean`, `scope from-nodes|from-link|...`, `index {build|status|drop}`, `bench`, `doctor`, `edit` (REPL — stretch).

`--json` flag on every command emits structured JSON for AI agent consumption. Claude Code-style short interactive prompts; default in brackets; summary before destructive ops.

### 6.7 Notebook

`_repr_html_` on `Package`, `Table`, `ValidationReport`, `EditResult` (in datagrove); on `Network` (in gmnspy). Rich progress with `force_terminal=False` for inline rendering. Optional ipywidget for interactive scope construction (gated behind `gmnspy[notebook]` extra).

### 6.8 Self-hostable API server

`gmnspy.server` (optional `[server]` extra) ships a FastAPI app with auto-generated OpenAPI at `/docs`. Endpoints:
- `GET /networks` — list configured networks
- `GET /networks/{id}` — metadata + spec version + table list + last-validated timestamp
- `GET /networks/{id}/tables/{table}?bbox=...&zone_ids=...&columns=...&format=parquet|csv|duckdb|json` — scoped table download
- `GET /networks/{id}/spec` — return resolved spec (Frictionless JSON)
- `POST /networks/{id}/validate` — run validation, return `ValidationReport` JSON (or HTML if Accept header)
- `GET /networks/{id}/quality` — data-quality report

Pluggable auth: none / bearer-token / OAuth2 (config-driven). Default download format = DuckDB. Config-file driven; backend points at any `datagrove.read()`-compatible source. Ships `Dockerfile` + `docker-compose.yml` example. **We don't host.**

### 6.9 AI accessibility

- **`docs/llms.txt`** + **`docs/llms-full.txt`** at site root (auto-generated from mkdocs nav).
- **`docs/ai/`** subtree: `cookbook.md`, `api-index.json` (machine-readable public API), `glossary.md` (GMNS terms).
- **Doctests in every public function** (Google-style docstrings with `Examples:` block), run in CI.
- **`--json` flag on every CLI command**.
- **Claude Code Skills** in `skills/` directory: `datagrove-validate`, `gmns-author`, `gmns-validate`, `gmns-convert`, `gmns-clean`. Installable via `claude code skill add <git-url>#path=skills/<name>`.
- **MCP server** — `gmnspy[mcp]` ships `gmnspy mcp serve` (and `datagrove mcp serve` for the generic case). Tools: `read_network`, `describe_network`, `query_table` (ibis predicate, not SQL), `scope`, `validate`, `quality_check`, `convert`, `edit_session` (with rollback).

## 7. Spec sync strategy

- Each supported GMNS spec version vendored under `packages/gmnspy/gmnspy/spec/<version>/` (e.g., `0.97/datapackage.json`, `0.97/link.schema.json`, `0.97/shared_categories.json`).
- `gmnspy.SUPPORTED_SPECS = ["0.95", "0.96", "0.97"]`; `DEFAULT_SPEC = "0.97"`.
- User override: `gmnspy.read(..., spec_version="0.96")`.
- `.github/workflows/spec-sync.yml` runs daily, checks upstream releases at zephyr-data-specs/GMNS, opens a PR labeled `spec-sync` against `develop` with the new version added side-by-side. Maintainer reviews; default-version bump goes in a minor release.
- Validation reports always include `spec_version` in the header.

## 8. Quality bar

- **Coverage targets (gated at Phase 5):** datagrove ≥85%, gmnspy ≥75%.
- **Test pyramid:** unit (per-module) → contract (engine/adapter conformance) → fixture (Leavenworth) → perf (synthetic regional fixture, `pytest-benchmark`).
- **CI matrix:** Python 3.11 / 3.12 / 3.13 × Linux + macOS smoke. Engines tested per-engine.
- **No raw SQL, no `pandas` in datagrove core paths** (allowed via `to_pandas()` converter at the edge only).
- **Doctests run in CI** — public-API examples must execute.

## 9. Conventions

- **Docstrings:** Google style. Every public function has an `Examples:` block usable as a doctest.
- **Logging:** `logging.getLogger(__name__)` per module. Library never configures the root logger; only the CLI does.
- **Pydantic:** v2, strict on datagrove core types.
- **Type hints:** required on all public APIs. `pyright` strict on `datagrove`, basic on `gmnspy`.
- **Errors:** structured exceptions in a per-module `errors.py`. Use specific subclasses, not bare `ValueError`.
- **Backwards compat:** v0.3.x is a clean break — no shims. Migration guide ([docs/migration/v0.3-to-v1.0.md](migration/v0.3-to-v1.0.md), Phase 4 task 4.14) explains old → new mappings.
- **Per-package semver.** `datagrove` and `gmnspy` version independently. Tags: `datagrove-vX.Y.Z`, `gmnspy-vX.Y.Z`.

## 10. Phase plan summary

Five phases, ~14–16 weeks to v1.0 GA. Full task tree in the [GitHub issue tree](https://github.com/e-lo/GMNSpy/issues/115) (Epic).

| Phase | Focus | Duration |
|---|---|---|
| 0 | Repo prep — workspace, vendored specs, dev tooling, CI, issue tree, **module skeletons** | done |
| 1 | datagrove foundation — spec model, engines, IO adapters, Leavenworth fixture | weeks 1–4 |
| 2 | Validation + dataset surface — schema/FK/structural/sync, lazy Package/Table, generic edit framework, interactive HTML reports | weeks 4–7 |
| 3 | Operations + GMNS bindings + quality + clean — cost model, GMNS Network, semantics, indexes, scope, quality framework + GMNS rule pack, clean ops | weeks 7–11 |
| 4 | Surfaces — CLI (datagrove + gmnspy), notebook, server, MCP, Skills, awesome docs, migration guide, full PRD | weeks 11–14 |
| 5 | Hardening + beta + GA — coverage gate, perf bench, spec-sync bot, releases | weeks 14–16+ |

**Sub-agent friendly tasks** are tagged `subagent-friendly` in the issue tree. Phase 1–4 mid-batches have 5–10 truly parallel tasks (no file overlap, no inter-deps).

## 11. How to contribute (short version)

1. Pick an issue labeled `subagent-friendly` (or any task on the current phase).
2. Branch from `refactor/v1.0` as `refactor/v1.0/<phase>-<task>-<slug>`.
3. Write the code per the issue's Deliverable + Acceptance criteria.
4. Add tests under `packages/<pkg>/tests/`.
5. Run `uv run ruff check`, `uv run ruff format`, `uv run lint-imports`, `uv run pytest` locally.
6. Open PR against `refactor/v1.0`. Use the issue body's acceptance checklist as your self-review.

Full contributor workflow: [CONTRIBUTING.md](../CONTRIBUTING.md).

---

*This document is updated as architectural decisions evolve. When updating, also update the [GitHub issue tree](https://github.com/e-lo/GMNSpy/issues/115) and (post-Phase-4) [docs/PRD.md](PRD.md). Authoritative source for any conflict: this file > PRD > issue body > inline code comments.*
