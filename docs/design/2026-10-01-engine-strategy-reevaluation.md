# Engine strategy re-evaluation — corral / netstead

Status: **accepted — Option B (DuckDB-only, stay on ibis); Option C (drop ibis) rejected** ·
Implemented: #195 (consolidation), #198 (ibis pin lifted) · Date: 2026-10-01 · Owner: corral core

> **Resolved since writing:** the `ibis>=9,<10` pin discussed below was lifted in #198
> (`ibis-framework[duckdb]>=10`). The one-release deprecation shim for
> `engine="pandas"|"polars"` was *not* kept — the library is pre-release, so #195 removed
> those engines outright. See the [implementation plan](2026-10-01-engine-consolidation-plan.md).

## Why now

corral was built around an **engine-agnostic compute** abstraction — a `Engine`
protocol with three native implementations (`IbisEngine` on duckdb, `PandasEngine`,
`PolarsEngine`) so the same pipeline could run on any of them. The premise was that
"engine-agnostic" was a core value worth the abstraction.

That premise just lost its strongest backer. **Ibis removed the pandas and dask
execution backends in 10.0**, and their own rationale is almost verbatim our situation
([Farewell pandas](https://ibis-project.org/posts/farewell-pandas/)):

- the pandas backend was "a few thousand lines of code" and often *slower than pandas directly*;
- `NaN` vs `NULL` conflicts were "an ongoing headache";
- "There is **no feature gap** between the pandas backend and our default DuckDB backend, and DuckDB is much more performant";
- **pandas/polars DataFrames remain valid as input/output _format_** — DuckDB queries them directly (zero-copy via Arrow replacement scans) and returns `.df()` / `.pl()` / `.arrow()`.

The maintainers of the very abstraction we leaned on concluded that maintaining a
non-SQL compute backend alongside DuckDB isn't worth it. We should reach the same
conclusion for the same reasons.

## The conceptual error to correct

"Engine-agnostic" conflated **two different properties**:

1. **Compute-engine agnosticism** — run the *same operations* on pandas compute vs polars
   compute vs duckdb compute. Expensive to maintain (N implementations + N² parity tests),
   and the thing Ibis just abandoned.
2. **Dataframe-format interoperability** — *accept and return* pandas / polars / pyarrow at
   the boundaries. Genuinely valuable for a library people embed in notebooks and pipelines.

**(2) is the property our users actually want. DuckDB gives it for free** — it scans pandas/
polars/arrow objects in-process with zero copy (Arrow replacement scans) and emits any of them
([DuckDB⇄Arrow](https://duckdb.org/2021/12/03/duck-arrow/)). We have been paying the full cost of
(1) to deliver (2), which DuckDB already delivers natively.

## What we actually have today (blast-radius survey)

A full survey of `engines/`, `dataset/`, `validation/`, `editing/`, `io/`, and all of netstead found
that **the compute core is already single-engine; the multi-engine surface is mostly thin readers
and parity tests:**

- **Compute is already ibis-first, not engine-polymorphic.** `validation/schema_check.py`,
  `validation/foreign_keys.py`, `validation/sync_state.py`, `dataset/view.py` (spatial scopes),
  `dataset/filter.py`, and `editing/apply.py` all build **ibis** expressions and run them on duckdb.
  For a pandas/polars input they call `validation/_ibis.to_ibis()` to wrap the frame in an
  `ibis.memtable` on duckdb, compute there, and round-trip back via pyarrow. **Nothing of substance
  is reimplemented per engine.**
- **pandas/polars engines are mostly thin wrappers.** Of the 18 `Engine` methods, the only genuinely
  independent per-engine work is **file read/write** (`read_csv`/`read_parquet`/`read_duckdb_table`
  + writers) — one-line routes into each library. `select`/`head`/`order_by`/`limit`/`count`/`columns`
  are one-liners; `to_pandas`/`to_polars` are `convert_dtypes()` converters. `PolarsEngine` can't even
  write duckdb (raises). `engines/` is ~2,800 LOC, but most is these thin wrappers + three
  near-identical `_scan_dict` helpers + three `_FRICTIONLESS_TO_*` dtype maps kept in sync by one
  parity test.
- **netstead is barely coupled.** It almost never uses lazy engine ops; the dominant idiom is
  `table.to_pandas()` → work on the frame (graph, select, osm, viz, map, scope, semantics, quality,
  clean, indexes). It assumes only "the Table can materialize to pandas/arrow," never a specific
  compute engine. The lone concrete pins are `map/edits.py` (`PandasEngine()` for writeback) and
  netstead's *own* `graph/source.py` duckdb/polars/parquet `NetworkSource` (independent of corral's
  `Engine`, already duckdb-native with sanctioned raw SQL).
- **Tests: ~91 `@parametrize("engine_name", …)` decorators + a dedicated cross-engine dtype-parity
  suite.** These overwhelmingly prove "each engine's `to_ibis` round-trip yields identical results,"
  i.e. they test the round-trip, not independent compute. Under one compute engine they *collapse*,
  not port.

**Conclusion: the "three engines" are one duckdb compute core + two alternative readers + a dtype
converter, surrounded by parity tests for a polymorphism we don't really exercise.**

## Options

### A. Status quo — keep three native compute engines
Rejected. We'd carry two reader classes, ~91 parametrizations, and the `_FRICTIONLESS_TO_*` parity
machinery to advertise a compute-agnosticism that (a) is already faked by round-tripping everything
to duckdb and (b) the upstream (Ibis) is actively retreating from. Pure cost, no real capability.

### B. One compute engine = DuckDB, frames as I/O — **keep Ibis as the expression layer** ✅ recommended (now)
- DuckDB is the single compute engine. **pandas / polars / pyarrow become boundary formats only:**
  input via duckdb replacement scan / `from_arrow`; output via `.to_pandas()` / `.to_polars()` /
  `.to_arrow()` converters.
- Delete `PandasEngine` / `PolarsEngine` as **compute** engines. The `Engine` protocol collapses to a
  thin "read sources into an ibis/duckdb table + convert out" surface (or disappears into a single
  `DuckDBStore`). `Table`/`Package` drop the `engine` back-pointer.
- `validation/*`, `dataset/view.py`, `dataset/filter.py`, `editing/apply.py` keep their **existing
  ibis code** and simply lose the non-ibis `to_ibis` round-trip branch. io adapters target duckdb
  reads + pandas/polars/arrow writers.
- **Pros:** smallest, lowest-risk change (mostly *deletion* — netstead essentially untouched); keeps the
  lazy, composable ibis expression API; `lint_no_sql` ethos intact (ibis, not raw SQL); matches Ibis's
  own blessed path; **cross-SQL-warehouse portability stays possible** (ibis still supports
  postgres/bigquery/snowflake/spark — only the *local* non-SQL backends were removed).
- **Cons:** still depends on Ibis (a heavy dep) even though we'd only use its duckdb backend; the
  `ibis>=9,<10` pin (the `create_table`/`from_records` codegen break) remains until we move to 10+.

### C. DuckDB-native — **drop Ibis entirely** (evaluated and NOT pursued — see Decision)
- Use DuckDB's Python **relational API** (`rel.filter().order().limit().aggregate()`) and/or
  parameterized SQL in one sanctioned module; frames via replacement scans + `.df()/.pl()/.arrow()`.
- **Pros:** leanest deps (drops Ibis + its transitive weight — aligns with the repo's "hand-roll thin
  wrappers over heavy deps" value); closest to the engine we're actually betting on; the ibis-10
  pin pain disappears.
- **Cons:** biggest rewrite — `validation/`, `dataset/view.py`, `dataset/filter.py`, `editing/apply.py`
  are ~2,500 LOC of **ibis-expression** compute that would be ported to the relational API/SQL; loses
  cross-warehouse portability; `lint_no_sql` inverts (we'd sanction parameterized SQL in a data-access
  layer instead of forbidding it). Real risk for marginal benefit *once the pandas/polars engines are
  already gone*.

### D. Narwhals at the boundary
[Narwhals](https://narwhals-dev.github.io/narwhals/) is the other compat layer, but it targets a
different shape: a thin **dataframe-API** facade for libraries whose public surface is "give me a
dataframe, chain Polars-style ops, get your dataframe back," delegating to the native frame's own
engine with no query planning or parquet-scan model
([Ibis vs Narwhals vs Fugue](https://codecut.ai/ibis-vs-narwhals-vs-fugue-dataframe-portability/)).
Our workload is parquet-backed networks with spatial joins and graph ops — DuckDB is the stronger
compute substrate, and it *already* accepts any in-process frame, so Narwhals adds little to the core.
Set aside (possible minor input-normalization convenience, not the architecture).

## Recommendation

**Adopt B now; keep C as a deliberately-deferred option.**

B is almost entirely deletion and netstead barely moves, so it's a low-risk, high-clarity win: it kills
the maintenance sink (two reader classes, ~91 parametrizations, the dtype-parity maps) and replaces a
false "3-engine" promise with an honest one — **"a DuckDB/Parquet data-package engine with first-class
pandas / polars / Arrow interchange."** That is both more accurate and a better story (it's exactly
what Ibis now tells its own users).

The one strategic question that decides B-vs-eventually-C:

> **Is running the *same pipeline* against a remote SQL warehouse (Postgres / BigQuery / Snowflake /
> Spark) a real product goal, or is local DuckDB/Parquet the whole game?**

- **Warehouse portability matters** → stay on B. Ibis earns its keep as the portable expression layer;
  duckdb is just the default backend and the others are a config change.
- **Local DuckDB/Parquet is the whole game** → B now, then plan C later. A single-backend Ibis is a
  heavy abstraction over one engine, which cuts against the repo's lean-deps value; going
  duckdb-native removes a big dependency and the ibis-version pin. But do it only after B, as its own
  project, because it's the ~2,500-LOC ibis-expression port.

Either way, **B is the immediate move**. (Update: after evaluating DuckDB's Python API, C is dropped —
ibis-on-duckdb is the chainable-expression wrapper we want and its duckdb backend is not deprecated. See
the Decision section.)

## Migration sketch for B (phased, low-risk)

1. **Reframe + freeze the format contract.** Declare DuckDB the one compute engine; pandas/polars/arrow
   are I/O. Lock input (replacement scan / `from_arrow`) and output (`to_pandas`/`to_polars`/`to_arrow`)
   as the supported interop surface, with tests.
2. **Collapse the `Engine` protocol.** Replace the 3-impl protocol with a single duckdb-backed store
   (keep the ibis expr inside). `Table`/`Package` drop `engine`; `get_engine`/`resolve_engine`/the
   registry and the `--engine` CLI flags are removed (or kept as no-op deprecation shims for one release).
3. **Strip the non-ibis branches.** In `validation/*`, `dataset/view.py`, `dataset/filter.py`,
   `editing/apply.py`, delete the `to_ibis`-from-non-ibis round-trip arms; keep the pass-through.
   io adapters stop fanning out to 3 engines' read/write primitives.
4. **netstead cleanup.** Drop `engine=` plumbing on `Network.from_source` + the ~10 CLI `--engine`
   options; unpin `map/edits.py` from `PandasEngine`; reconcile netstead's own `graph/source.py`
   duckdb path with corral's (dedupe if sensible — netstead already has a sanctioned duckdb-native
   `DuckDBSource`).
5. **Tests.** Delete `test_cross_engine_dtype_parity.py` and the `engine_name` parametrization; keep
   one duckdb compute path + explicit **format-interop** tests (pandas-in/out, polars-in/out,
   arrow-in/out round-trips). Net: large reduction in test count, same real coverage.
6. **Docs + positioning.** Rewrite the "engine-agnostic" claim to "DuckDB compute + pandas/polars/arrow
   interchange." Update the memory and the corral description.

Backwards-compat: keep `engine="pandas"|"polars"` accepted-but-deprecated for one release (warn, ignore
beyond selecting output format) so downstream callers don't break hard.

## Side effects to note
- **`lint_no_sql.py`** stays as-is under B (raw SQL still confined to the one duckdb module). Under C it
  would be rewritten to *sanction* parameterized SQL in a named data-access layer.
- **The `ibis>=9,<10` pin** (create_table/from_records codegen break on duckdb) persists under B; C
  removes the dependency and the pin.
- **netstead `graph/source.py`** already contains a duckdb-native `NetworkSource` with `# pragma: allow-sql`
  — evidence the duckdb-native style is already in the codebase, and a candidate to unify under C.
- **The G1/G2 viewer work** (just landed) simplifies under B: the viewer's table path becomes a single
  duckdb query (filter+sort+limit+count pushed down, page-only materialization) for *every* input,
  removing the pandas-vs-lazy branch in `viz/tables.py`.

## Decision (made 2026-10-01; refined after checking DuckDB's Python API)
**Local DuckDB/Parquet only, and stay on Ibis-on-DuckDB permanently. Option B is the whole change;
Option C is dropped (parked, not tracked).**

- **Do Option B** (one compute engine = DuckDB; pandas/polars/arrow as I/O formats; Ibis retained as the
  expression layer, duckdb backend only) — mostly deletion, netstead barely moves, and it does **not touch
  the ibis expression API** we rely on.
- **Option C (drop Ibis → DuckDB-native) is NOT pursued.** Rationale, after evaluating DuckDB's Python
  API directly: DuckDB's Relational API is chainable but its expressions are largely **SQL strings**
  (`rel.filter("lanes >= 3").project("…")`); the native **Expression API** (`duckdb.ColumnExpression`)
  is only partial and DuckDB has an open workstream to reach dataframe-library parity
  ([duckdb#12134](https://github.com/duckdb/duckdb/discussions/12134)). Our validation / FK / filter /
  spatial code builds predicates **programmatically**, which is exactly where ibis's composable,
  type-aware expression algebra pays off. **ibis-on-duckdb _is_ the chainable-Python-expression wrapper
  over DuckDB** — there is no better native one yet.
- **Crucially, our ibis usage carries no deprecation risk:** Ibis removed the *pandas/dask* execution
  backends; **DuckDB is Ibis's flagship backend** and is being invested in. We confine ourselves to it.
- The lean-deps value is satisfied by *scoping* ibis to one backend, not by reimplementing its expression
  algebra over DuckDB's half-finished one. Warehouse portability (Postgres/BigQuery/…) comes along as a
  free latent bonus, not a goal.
- Loose end to resolve during B: the `ibis>=9,<10` pin (create_table/from_records codegen break). Prefer
  reading parquet via DuckDB directly and using ibis for *expressions*, which de-risks moving to ibis 10+.

This is a corral-wide refactor and should ride its own branch, not `feat/nl-selection`.
