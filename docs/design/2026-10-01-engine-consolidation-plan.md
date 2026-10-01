# Option B implementation plan — DuckDB-one-engine consolidation

Status: **plan / ready to execute** · Date: 2026-10-01 · Depends on: `2026-10-01-engine-strategy-reevaluation.md` (decision)

Goal: collapse datagrove's three-engine compute abstraction to **one compute engine (ibis-on-DuckDB)**,
with **pandas / polars / pyarrow as input/output formats only**. Keep the ibis expression API. This is
overwhelmingly *subtraction*; the ibis expression code (validation, FK, spatial, filter, editing) is
untouched.

## Branch & guardrails
- New branch **off `refactor/v1.0`** (NOT `feat/nl-selection`): e.g. `refactor/duckdb-one-engine`.
- TDD throughout; every phase ends green and is independently committable.
- Only one phase (Phase 2) changes runtime behavior; it's reversible.
- Non-goals (explicitly out of scope): Option C / dropping ibis; renaming `IbisEngine` (optional alias
  only); rewriting gmnspy's independent `graph/source.py`; removing `Table.engine`/`Package.engine`
  (kept as a single-engine singleton to avoid gratuitous churn — see Phase 5 note).

## End state
- `engines/`: **one** engine class (ibis-on-duckdb). `pandas_engine.py`, `polars_engine.py` deleted.
- `Engine` protocol: either kept with one impl, or thinned to a concrete `DuckDBStore`. Registry /
  `resolve_engine` / `--engine` reduced to a one-release deprecation shim (warn + ignore), then removed.
- **Format interop is first-class and tested:** input via `from_arrow` / `from_records` / duckdb
  replacement scan or memtable; output via `to_pandas` / `to_polars` / `to_arrow`.
- Tests: cross-engine parametrization and `test_cross_engine_dtype_parity.py` removed; replaced by a
  single compute path + explicit **format round-trip** tests.
- Docs reposition datagrove as "a DuckDB/Parquet data-package engine with first-class pandas/polars/Arrow
  interchange."

---

## Phase 0 — Safety net: pin the format-interop contract (no deletion, no behavior change)
Purpose: lock the behavior we must preserve *before* deleting anything.

1. New test file `packages/datagrove/tests/dataset/test_format_interop.py`:
   - **Input**: build a `Package`/`Table` (or `Network`) from a pandas DataFrame, a polars DataFrame, and
     a pyarrow Table; assert identical row counts/values regardless of input format.
   - **Output**: from one duckdb-loaded table, assert `to_pandas()` / `to_polars()` / `to_arrow()` all
     return the right type with the cross-engine **nullable dtype contract** (`Int64/Float64/string/
     boolean`) — the dtype guarantee currently proven by `test_cross_engine_dtype_parity.py`, re-pinned
     here as an *output-converter* property rather than a cross-compute property.
   - **Compute parity across input formats**: a filter/sort/aggregate gives the same result whether the
     source frame was pandas/polars/arrow (proving duckdb is the single compute path underneath).
2. Confirm the input paths exist: `IbisEngine.from_arrow` (ibis_engine.py:295), `from_records` (256),
   and duckdb replacement-scan/memtable via `validation/_ibis.to_ibis` (_ibis.py:80). If a clean
   "construct a Network/Package from in-memory frames" entry point is missing, add a thin one
   (`from_frames(...)`) — this is the supported *input* surface going forward.

Exit: new tests green on the current 3-engine code. Commit.

## Phase 1 — Verify duckdb is already the universal compute path (characterization, no change)
Purpose: make the "already ibis-first" claim executable so the later deletions are provably safe.

1. Add/confirm tests that the hot-path ops — schema validation, foreign-key checks, spatial `from_bbox`,
   `dataset.filter.filter_rows`, an `editing` delete/update — produce identical results when the source
   `Table` was built on the pandas or polars engine vs the ibis engine (they route through
   `validation/_ibis.to_ibis` → duckdb today). These likely already exist as parametrized cases; if so,
   just note them as the characterization set.

Exit: green. No commit needed if purely characterization, else commit.

## Phase 2 — Make ibis/duckdb the sole *default* compute engine (the one behavior change; reversible)
1. `engines/__init__.py`:
   - Stop auto-registering `PandasEngine`/`PolarsEngine` as selectable compute engines (lines ~246-269).
   - `resolve_engine(name)` (277-313): `None`→ibis/duckdb (unchanged). `"ibis"`/`"duckdb"`→the engine.
     `"pandas"`/`"polars"`→ **DeprecationWarning** ("compute engine selection is removed; DuckDB is the
     compute engine, pandas/polars are output formats via to_pandas()/to_polars()") and return the single
     engine. Unknown→`ValueError` (unchanged).
   - `get_engine`/`set_default_engine`/`list_engines`: reduce to the single engine (keep signatures as
     deprecation shims for one release).
2. The engine classes stay on disk this phase (their unit tests still instantiate them directly, so they
   stay green). Only the *default/registry path* changes.

Exit: full datagrove + gmnspy suites green (ibis was already the default, so behavior is unchanged for
the default path; only explicit `--engine pandas/polars` now warns). Commit. **Rollback point.**

## Phase 3 — Collapse the test matrix to one compute path + format round-trips
1. Convert the ~91 `@pytest.mark.parametrize("engine_name", …)` decorators to the single ibis/duckdb path.
   Mechanical: the validation (`ENGINES` in test_schema_check.py:96, test_foreign_keys.py:72,
   test_sync_state.py:65), `dataset/test_table.py`, `test_filter.py`, `test_view.py`, `test_package.py`,
   `editing/test_editing.py`, and io adapter suites (`_engines_available()`, `ENGINE_PARAMS`).
2. Delete `engines/test_cross_engine_dtype_parity.py` — moot under one compute engine. Its dtype
   guarantee is now covered by the **output-converter** tests in `test_format_interop.py` (Phase 0).
3. Keep a reduced per-engine unit suite for the surviving engine only.

Exit: green, far fewer cases, same real coverage. Commit (large but mechanical diff — reviewable alone).

## Phase 4 — Delete the pandas/polars *compute* engines
1. Delete `engines/pandas_engine.py`, `engines/polars_engine.py`, `engines/test_pandas_engine.py`,
   `engines/test_polars_engine.py`.
2. Remove `PandasEngine`/`PolarsEngine` from `engines/__init__.py` exports/imports and
   `test_registry.py`'s fakes (trim the `FakeEngine` arms added for them).
3. Verify the `_FRICTIONLESS_TO_{PANDAS,POLARS}` dtype maps leave with their engines; confirm `to_pandas`
   output casting uses `convert_dtypes()` (ibis_engine.py:528) and does NOT depend on the pandas map —
   if it does, fold the needed bit into the ibis engine's output converter.
4. Optional: add `DuckDBEngine = IbisEngine` alias (honesty) without renaming the class.

Exit: green. Commit.

## Phase 5 — Simplify the ibis-first branches now that no non-ibis source exists
Purpose: remove dead round-trip code (cleanup, not behavior change).
1. `validation/_ibis.to_ibis` becomes a passthrough for the only (ibis) input; the polars `.collect()
   .to_arrow()` and pandas pyarrow arms become unreachable → delete, inline `to_ibis` or keep as a
   documented passthrough.
2. `dataset/view.py` (184-194): drop the non-ibis "rebuild on source engine" arm; keep the duckdb lazy
   path. `dataset/filter.py`: drop its non-ibis memtable-rebuild arm (now unreachable). `editing/apply.py`:
   the `from_arrow` rebuild simplifies to the single engine.
3. `Table`/`Package`: **keep** the `engine` field (now always the one engine) to avoid touching every
   construction site. Optionally default it so callers can omit it. (A later, separate cleanup can remove
   the field entirely — intentionally deferred to keep this change subtractive and low-risk.)

Exit: green. Commit.

## Phase 6 — gmnspy + CLI cleanup
1. gmnspy CLI: make `--engine` on `build`/`viz`/`clean`/`bench`/`select` (and `cli/_helpers.resolve_engine`,
   _helpers.py:29-38/63) deprecated no-ops (warn + ignore) for one release, or remove. `Network.from_source
   (engine=…)` (network.py:166-229) likewise.
2. `map/edits.py` (413, 464): replace the hard-coded `PandasEngine()` writeback with the single engine
   (compute in duckdb; emit pandas via `to_pandas()` where a frame is actually needed).
3. `datagrove` CLI `--engine` (cli/app.py:108-173): same deprecation treatment.
4. `graph/source.py` `NetworkSource`/`DuckDBSource`: **flag only** — it's independent, already duckdb,
   with sanctioned raw SQL. Note the dedupe opportunity against datagrove's duckdb path; don't merge in
   this change.

Exit: gmnspy + datagrove green. Commit.

## Phase 7 — Docs, positioning, loose ends
1. Rewrite "engine-agnostic" language in datagrove's `pyproject` description, READMEs, `docs/architecture.md`
   (§6.1 ibis-first already aligns) → "DuckDB/Parquet engine with pandas/polars/Arrow interchange."
2. Update `lint_no_sql.py` doc note (rule itself unchanged — raw SQL still confined to the one engine).
3. Record done-state in memory (`project-engine-strategy`).
4. **Optional de-risk (separate task):** resolve the `ibis>=9,<10` pin — prefer reading parquet via duckdb
   directly and using ibis only for *expressions*, which sidesteps the `from_records` create_table codegen
   break and clears the path to ibis 10+. Not required for B.

---

## Risk & sequencing notes
- **io adapters need no logic change**: they already delegate to `engine.read_*/write_*/from_records`
  without per-engine branches (post-#134 inversion). With one engine they simply always call it.
- **Biggest diff is Phase 3** (test de-parametrization) — mechanical and isolatable.
- **Only Phase 2 changes behavior** and is a clean rollback point.
- **Deprecation, not hard break**: `engine=`/`--engine` warn-and-ignore for one release so downstream
  callers don't break.
- **LOC delta (approx):** −1,050 (two engine classes) −~2 test files, −~91 parametrizations; +1 interop
  test file; ~0 change to ibis expression code.

## Success criteria
- One compute engine; `gmnspy`/`datagrove` work with no `--engine` flag.
- pandas/polars/arrow round-trip in and out, dtype contract preserved (tested).
- Full suite green with the parity/parametrization machinery gone.
- Docs/positioning updated; ibis expression API unchanged.
