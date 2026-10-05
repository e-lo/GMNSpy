---
title: Benchmarking suite — scope
audience: maintainers
kind: design
status: draft
date: 2026-09-30
summary: >
  An advertisable + internal-regression performance suite for netstead across the
  three corral engines (pandas / polars / ibis-duckdb), covering network
  creation, selection queries, and visualization packing.
---

# Benchmarking suite — scope

## 1. Motivation & goals

netstead is engine-agnostic (pandas / polars / ibis-duckdb via corral) and
markets Parquet/DuckDB as the intended hot path. We need one suite that serves
**two audiences at once**:

1. **Advertising** — a clean, reproducible table we can put in the README /
   docs: *"a 269k-link metro drive network builds from OSM in ~27s, answers a
   natural-language selection in <1s, and packs for the browser in <1s."*
   Engine × size × operation → time + memory.
2. **Regression tracking** — a CI-friendly, machine-readable format that flags
   when a change makes a hot path meaningfully slower or heavier, without
   flaking on timing noise.

Design constraints carried from project memory:

- **Avoid over-engineering.** Reuse the existing `netstead bench` JSON contract
  and the already-wired `bench.yml` workflow before adding new machinery.
  Complexity (headless-browser FPS, per-frame accounting) is opt-in tiers, not
  the default path.
- **Lean deps, externalize data.** Prefer stdlib capture (`time.perf_counter`,
  `tracemalloc`, `resource`) plus one thin process-RSS dep (`psutil`) over a
  heavyweight framework. Keep fixture *definitions* (sizes, bboxes, seeds) in a
  maintained data file, not scattered through code.
- **Engine-agnostic storage.** Parquet/DuckDB is the hot path; pandas is one
  engine among three, not the baseline. The matrix must make the Parquet+ibis
  numbers the headline while keeping pandas/CSV honest as a portability floor.

## 2. What already exists (reuse inventory)

| Asset | Path | Reuse |
|---|---|---|
| `netstead bench` CLI | `netstead/cli/commands/bench.py` | Per-phase `perf_counter` timing (`load`/`validate`/counts/`is_connected`), `--engine`, `--json`. **Extend**, don't replace — it already defines the JSON shape (`{source, engine, total_seconds, phases:[{phase,seconds}]}`). |
| Bench cookbook | `netstead/docs/cookbook/run-bench.md` | Documents an OSM-build harness (`scripts/bench_osm_build.py`) with a per-engine **build + peak-mem + result-count** table and osmnx/osm2gmns baselines. **The script is referenced but not present in the tree** — the doc's table is the format precedent; the suite should ship the script the doc already describes. |
| `bench.yml` workflow | `.github/workflows/bench.yml` | Already future-proofed: discovers `-m perf` / `tests/bench/` / `test_bench_*.py`, downloads the most-recent main baseline, runs pytest-benchmark with `--benchmark-compare-fail=mean:200%`, uploads JSON artifact (90-day retention). **Wire the new tests into this; don't author a second workflow.** |
| `perf` marker | root `pyproject.toml` `[tool.pytest.ini_options].markers` | `"perf: performance regression bench"` already registered. |
| `pytest-benchmark>=4` | root `pyproject.toml` `[dependency-groups].dev` | Already a dev dep. |
| `OperationCost` cost model | `corral/operations/cost_model.py` | Coefficients (seconds-per-million-rows per op) are **calibrated by** the bench job (docstring cites "Phase 5 nightly bench, issue #126"). The suite is the calibration source; emit numbers in a shape the coefficients can be re-fit from. |
| Cross-engine OSM smoke | `netstead/tests/test_osm_bench.py` | `@pytest.mark.perf`, parametrized over `["ibis","pandas","polars"]`, builds from a synthetic grid via `convert.build_node_link_tables` + `build.network_from_records`. **The correctness harness the timing suite sits beside** (it explicitly defers timing to `scripts/bench_osm_build.py`). |
| Engine registry | `corral/engines/__init__.py` | `resolve_engine(name)`, `list_engines()`, `get_engine()` — the matrix driver. `list_engines()` gates skips when an extra is absent. |
| Fixtures | `netstead/fixtures/{leavenworth,rdu_i40}` | leavenworth = 339 links (smoke, not a benchmark); rdu_i40 = small real interchange. Both ship csv+parquet(+duckdb). **The S tier**; M/L are not (and should not be) committed. |

**Bottom line:** ~70% of the scaffolding exists. The gap is (a) the missing
`bench_osm_build.py`-style macro runner generalized to all three operation
families, (b) a fixture-provisioning story for M/L sizes, (c) memory capture,
and (d) the viz/render benchmark.

## 3. What to measure

Three operation families, each swept across the engine matrix and S/M/L sizes.

### 3.1 Network creation

The headline. Three sources, because they exercise different code and different
future-facing claims:

| Source | Path exercised | Status |
|---|---|---|
| **OSM** | `osm.build.build_network_from_osm` (fetch) + `network_from_records` (assemble) | Live. Split the timing: `fetch` (network I/O, excluded from the engine comparison) vs `convert` vs `assemble` (the engine-sensitive part). |
| **CSV files** | `Network.from_source(<dir>)` on a CSV GMNS package | Live. This is the pandas/CSV portability floor and the `read_csv` coefficient source. |
| **Parquet / DuckDB** | `Network.from_source(<dir|.duckdb>)` | Live — **the advertised hot path.** Should be a first-class column even though the prompt lists OSM/Overture/CSV; it is the number we actually want to sell. |
| **Overture** | (planned reader) | **Placeholder row in the matrix, marked `n/a — planned`.** Define the slot now so the harness and output table don't need reshaping when the reader lands; do not block the suite on it. |

Metrics per (engine, size, source): **wall-clock** (and CPU time) of each
sub-phase and total; **peak process RSS** delta; **materialized-frame memory**
of the resulting `node`/`link` tables; result counts (nodes/links) as a
correctness co-assertion (the OSM smoke test already proves all three engines
agree — carry that invariant here so a "fast" run that dropped rows fails).

### 3.2 Selections (NL / structured queries)

A **fixed, versioned set** of representative utterances per fixture, resolved
via `netstead.select` (`resolve_frames`) — the same path `netstead select` drives.
The recent win (resolver vectorization: ~11s → ~0.93s on RDU) is exactly the
kind of regression this must lock in.

- Use the **StubParser**, never the Claude parser, in the timed path — we are
  benchmarking resolve, not an LLM round-trip or network latency.
- Cover the resolver's pipeline stages (facility narrowing → direction →
  anchor → path → classify) with utterances that hit each: a simple ref match,
  a between-anchors path, a direction-filtered corridor, and a
  no-match/degenerate case (empty result should be fast, not pathological).
- **Cold vs warm:** cold = first resolve on a freshly loaded network (pays
  frame materialization + any `GraphIndex`/CSR build — the cookbook already
  documents "first run pays the GraphIndex build cost"); warm = repeat resolve
  with caches hot. Report both; cold is the honest UX number, warm is the
  steady-state number.
- **Caveat to surface:** `select/resolve.py` and `viz/buffers.py` operate on
  **materialized pandas frames** (`.apply`, `pd.to_numeric`, `pd.Series`). So
  the *engine* dimension for selection/viz mostly measures **materialize-to-
  pandas cost** (ibis→arrow→pandas vs polars→pandas vs pandas-identity), not
  three independent resolver implementations. State this explicitly so the
  table isn't misread as "polars resolves faster" when it's really "polars
  materializes faster." This is itself a useful signal (it quantifies the
  cross-engine handoff tax on the hot path).

### 3.3 Visualization

Two measured metrics + one recommended (opt-in) tier.

- **Pack time** — `viz.buffers.pack_network(links, nodes)` wall-clock. ~0.86s
  on RDU 269k. The dominant inherent cost is the per-link WKT parse
  (`_parse_linestring_points`); measure with and without geometry to separate
  parse cost from buffer assembly.
- **Payload size** — `len(pack_network(...))` bytes (the ~14MB RDU blob), plus
  a breakdown from the wire-format header (link positions / start indices / ids
  / lanes / node positions / ids). This is what the browser downloads; it is
  advertisable ("14MB for 269k links") and a hard regression signal (a format
  change that doubles payload is a real user cost).
- **Actual render (deck.gl FPS + load):** see §8 — recommended as an **opt-in
  nightly/manual tier using headless Playwright**, with pack-time + payload as
  the **per-PR proxy**.

## 4. Metrics & capture methods

| Metric | Capture | Notes / caveats |
|---|---|---|
| Wall-clock | `time.perf_counter()` (stdlib) — already used by `bench.py` | Monotonic, highest resolution. The unit of the whole suite. |
| CPU time | `time.process_time()` (stdlib) | Wall vs CPU gap reveals I/O wait (OSM fetch) and duckdb's own threads. Cheap to add; keep it. |
| Python-heap peak | `tracemalloc` (stdlib): `start()` → run → `get_traced_memory()[1]` → `stop()` | Sees **only Python allocations**. Perfect for pandas frames + the pack buffers; **blind to duckdb's arena** (see below). Low overhead but non-zero — never leave it on during a wall-clock measurement; run memory and timing in **separate passes**. |
| Process RSS peak | `psutil.Process().memory_info().rss` sampled around the op (delta), or `resource.getrusage(RUSAGE_SELF).ru_maxrss` for a whole-run high-water mark | The **only** metric that captures duckdb's out-of-Python-heap memory. RSS is noisy (allocator retention, shared pages) — report as a delta and round generously. `ru_maxrss` is process-lifetime max (good for subprocess-per-case), bytes on Linux but **KiB on macOS** — normalize. |
| Materialized-frame memory | pandas `df.memory_usage(deep=True).sum()`; polars `df.estimated_size()`; arrow `table.nbytes` (ibis: `materialize()`→arrow→`.nbytes`) | The honest "how big is the network in RAM" number, engine-comparable. `deep=True` is required for object/string columns (WKT geometry, names) or you undercount by 10×. |
| DuckDB memory | `PRAGMA database_size` / duckdb's `memory_usage` if the connection is reachable | **Caveat, prominently:** ibis-duckdb keeps data in duckdb's own buffer manager, out of the Python heap, and **can spill to disk** under `memory_limit`. tracemalloc reports ~0; RSS captures resident portion only; spilled bytes show as neither. We report RSS + a bold footnote, and do **not** pretend the duckdb number is comparable to pandas' in-heap number. This is the single biggest honesty risk in the suite. |

**Rule:** timing and memory are measured in **separate runs** of the same case
(tracemalloc/psutil sampling perturbs wall-clock). The runner does two passes;
the output merges them per (engine, size, op).

## 5. Fixtures — sizes, sources, caching

### 5.1 Size tiers

Anchored on link count (the dimension that drives resolve + pack cost), with
the RDU metro measurement (269k links, ~27s OSM build, 14MB pack) as the L
anchor:

| Tier | Links (order) | Role | Concrete fixture |
|---|---|---|---|
| **S** | 10²–10³ | Smoke / correctness / CI-per-PR | `leavenworth` (339), `rdu_i40` (~small) — **already committed** |
| **M** | 10⁴–10⁵ | The "does it scale" middle | A metro-county OSM bbox (e.g. a single NC county) **or** a synthetic grid of matched size — provisioned, not committed |
| **L** | ~2.5×10⁵+ | The advertisable headline | RDU-metro drive network (269k links) — provisioned from a cached Overpass extract |

Keep the synthetic-grid generator from `test_osm_bench.py` (`_grid(n)`): it
gives **exactly reproducible, zero-I/O** M-sized inputs for CI, decoupled from
Overpass availability. Real bbox extracts are for the advertising numbers (they
carry real geometry + tag distributions that synthetic grids don't).

### 5.2 Sources & caching (no giant repo commits)

Externalize fixture *definitions* into one maintained data file
(`benchmarks/fixtures.toml` or `.yaml`): each entry = `{id, tier, source_kind
(osm_bbox|csv|parquet|synthetic|overture), bbox|seed|url, expected_links,
expected_nodes, content_hash}`. Code reads this; adding a size is a data edit.

Provisioning + caching strategy:

- **Never commit M/L raw data.** Only S (leavenworth, rdu_i40) stays in-repo.
- **OSM bbox extracts:** fetch once via the existing Overpass client, cache the
  raw response to a content-addressed path in a user cache dir
  (`platformdirs.user_cache_dir("netstead")/benchmarks/<hash>.json`) keyed by
  `(bbox, network_type, overpass_query_version)`. Re-runs are offline. Store
  the expected node/link counts + a content hash in `fixtures.toml` so a
  silently-changed OSM extract is detected (Overpass is not reproducible over
  time — pin by cached artifact, not by re-query).
- **CI:** cache the same directory with `actions/cache` keyed on the fixtures
  file hash. First CI run (or a fixtures bump) fetches; subsequent runs restore.
  For the strict per-PR regression gate, prefer the **synthetic M grid** (fully
  deterministic, no external dependency) and reserve real-bbox L for the
  nightly/manual advertising refresh so a flaky Overpass can't red a PR.
- **Overture (planned):** its cloud Parquet is large; when the reader lands,
  cache a pinned snapshot (specific release + bbox) to the same cache dir. The
  `fixtures.toml` slot is defined now; the provisioner grows one `source_kind`.
- **Format variants:** derive CSV/Parquet/DuckDB variants of a cached network
  on demand (corral already round-trips formats) so the "source format"
  dimension of §3.1 doesn't multiply committed bytes.

## 6. Harness design & tooling choice

### 6.1 Recommendation: two-layer harness

**Layer A — macro runner (custom), for the advertisable suite.** A small
runner that extends the `netstead bench` JSON contract to sweep
`engine × size × operation` and emit one merged JSON document. Rationale:

- The headline ops are **seconds-to-minutes, side-effect-heavy, once-per-run**
  (an OSM fetch must not be repeated dozens of times; a 27s build calibrated
  over pytest-benchmark's default multi-round auto-calibration would take many
  minutes and hammer Overpass). pytest-benchmark's model (many fast rounds of a
  pure function) is the wrong shape for these.
- We already own the JSON contract, the CLI, and the memory-capture plan. A
  custom runner is ~a few hundred lines over primitives we've read, versus
  bending a framework. This is the "avoid over-engineering / lean deps" call.
- **Cold measurement wants process isolation:** run each cold case in a fresh
  **subprocess** (import cost, engine/duckdb connection init, and OS file cache
  all reset) — the runner shells `netstead bench`-style subcommands and collects
  their `--json`. Warm cases run in-process with a repeat loop.

**Layer B — micro-benchmarks (pytest-benchmark), for hot pure functions.**
Wire the smallest, purest hot spots into the **existing `bench.yml`**:
`pack_network` (S+M fixtures), `resolve_frames` (locks in the 11s→0.93s win),
`_link_paths`/WKT parse. These are deterministic, fast, and exactly what
pytest-benchmark's statistical machinery + the `--benchmark-compare-fail=
mean:200%` gate is built for. No new workflow needed — the discovery step
already finds `-m perf` and `test_bench_*.py`.

### 6.2 Tooling evaluated

| Tool | License | Verdict |
|---|---|---|
| **`time`/`tracemalloc`/`resource`** (stdlib) | PSF | **Adopt** — capture primitives. Zero deps. |
| **`psutil`** | BSD-3-Clause | **Adopt** — the only clean cross-platform RSS/peak-RSS source. One small, ubiquitous dep; add to a `bench` extra (not core). |
| **`pytest-benchmark`** | BSD-2-Clause | **Adopt for Layer B.** Already a dev dep; already wired into `bench.yml` with baseline compare. Ideal for micro hot-paths, wrong for macro OSM builds. |
| **`asv` (airspeed velocity)** | BSD-3-Clause | **Reject.** Manages its own conda/virtualenv per commit and is oriented around walking git history — duplicates the uv workspace, adds a second env manager, and is overkill for a suite that mostly wants "engine × size" not "every commit." Its nice HTML history could be revisited in v1.1+ if we want long-term dashboards, but not now. |
| **Custom macro runner** | (ours, Apache-2.0) | **Adopt for Layer A.** Extends the existing bench JSON; owns subprocess isolation + the two-pass (time then memory) protocol. |

All adopted third-party licenses (BSD-2/3, PSF) are permissive and compatible
with the project's Apache-2.0.

### 6.3 Layout

```
benchmarks/                         # workspace root, sibling to packages/
  fixtures.toml                     # size/source/hash definitions (data)
  runner.py                         # Layer A macro runner (engine×size×op sweep)
  provision.py                      # fetch/cache/derive fixtures from fixtures.toml
  cases/                            # the versioned selection utterances, per fixture
  results/                          # gitignored; JSON output lands here
packages/netstead/netstead/tests/bench/ # Layer B pytest-benchmark micro-tests (-m perf)
scripts/bench_osm_build.py          # keep the doc's OSM-build entry point (thin wrapper on runner.py)
```

(Exact home — `benchmarks/` at root vs under `packages/netstead/` — is an
implementation detail; root keeps it out of the shipped wheel, which is
correct: benchmarks are not a runtime concern.)

## 7. Output formats

One canonical JSON per run; two rendered views derived from it.

### 7.1 Regression format (canonical JSON)

Superset of the existing `netstead bench` shape, adding the matrix keys +
memory + environment provenance:

```json
{
  "schema_version": "1",
  "env": {
    "machine": "arm64", "cpu": "Apple M1", "cores": 8,
    "python": "3.13.x", "os": "macOS-15",
    "versions": {"duckdb": "1.x", "ibis": "9.x", "polars": "1.x",
                 "pandas": "2.x", "pyarrow": "16.x", "netstead": "1.0.0b2"},
    "commit": "…", "timestamp": "…"
  },
  "results": [
    {"operation": "network_create", "source": "parquet", "engine": "ibis",
     "size": "L", "links": 269000, "nodes": 190000,
     "phases": [{"phase": "load", "seconds": 1.9}, {"phase": "assemble", "seconds": 4.1}],
     "total_seconds": 6.0,
     "mem": {"peak_rss_mb": 512, "py_heap_peak_mb": 40, "frame_mb": 180,
             "duckdb_note": "out-of-heap; RSS partial"}},
    {"operation": "selection", "case": "between_anchors", "engine": "ibis",
     "size": "L", "cold_seconds": 0.93, "warm_seconds": 0.21, "result_links": 84},
    {"operation": "viz_pack", "engine": "pandas", "size": "L",
     "seconds": 0.86, "payload_bytes": 14000000,
     "payload_breakdown": {"linkPositions": …, "startIndices": …}}
  ]
}
```

Regression use: `bench.yml` already downloads the most-recent main baseline
and fails a pytest-benchmark comparison at mean:200%. For the macro (Layer A)
numbers, add a tiny comparator step (the cookbook already shows the one-liner
pattern) with **per-operation tolerances** — tight on deterministic micro
(±15–25%), loose on macro wall-clock (±50%, or the existing 2× guard), and a
**hard cap on payload_bytes** (a size regression is deterministic and cheap to
gate strictly, e.g. ±2%).

### 7.2 Advertising format (Markdown)

Rendered from the same JSON into the table the cookbook already established
(engine × dataset → build / peak-mem / result), with the L Parquet+ibis row as
the headline and pandas/CSV as the honest floor. Emit alongside a one-line
environment stamp (machine, key lib versions) — a benchmark without its machine
is marketing, not data. Keep the cookbook's existing takeaways style ("all
engines produce identical counts", "polars leanest at scale").

## 8. Render benchmark — recommendation

**Recommendation: pack-time + payload-size as the per-PR proxy; a headless
Playwright FPS/load tier as opt-in nightly/manual.**

Reasoning and tradeoffs:

| Approach | Pros | Cons |
|---|---|---|
| **Pack time + payload (proxy)** — §3.3 | Deterministic, fast, no browser, no GPU, runs in CI on every PR. Directly measures what we control (the buffers we ship). Payload size is a hard, honest regression gate. | Doesn't measure actual frame rate or GPU upload. A change that keeps payload constant but tanks deck.gl perf (e.g. layer-config regression) is invisible. |
| **Headless browser FPS/load** — Playwright | Measures the real thing: time-to-first-render, sustained FPS on pan/zoom, GPU memory. | Flaky and machine/GPU-dependent (headless Chrome often falls back to SwiftShader software GL in CI → FPS numbers that don't reflect real hardware). Heavy dep + browser download. Slow. Hard to set a stable regression threshold. |

**Why Playwright, not Puppeteer:** Playwright ships **first-party Python
bindings** (this is a Python project; Puppeteer is Node-only and would drag in
a JS toolchain), is **Apache-2.0** (matches our license), and has better
headless-GPU controls. Use it, if at all, in a dedicated `bench-render` extra.

**Concrete plan:** ship the proxy now (it's ~free — `pack_network` + `len()`);
define but gate the Playwright tier behind an opt-in marker (`-m render`) that
`bench.yml` does **not** run on PRs. Run it nightly or manually on a known
machine, report FPS/load as **advertising-only** numbers with a loud
"software-GL in CI is not representative" caveat, and never make it a PR gate.
The viewer already serves the blob at `/api/network.bin`, so the Playwright
harness is: serve → navigate → `performance` API for load time →
`requestAnimationFrame` sampling during a scripted pan for FPS.

## 9. Reproducibility & variance

- **Machine dependence is inherent.** Every emitted artifact carries the `env`
  block (§7.1). Advertising tables cite the machine. Regression compares only
  same-machine runs (CI-to-CI baseline; the M1 dev numbers are separate).
- **Warmup.** Discard a warmup iteration for warm cases; for cold cases use a
  fresh subprocess (the cookbook's "restart Python between runs" guidance,
  automated). Report cold and warm separately — never average them.
- **Variance.** Micro (Layer B) → pytest-benchmark's built-in rounds/stddev.
  Macro (Layer A) → N=5 repeats, report **median + min** (min is the least
  contended, most reproducible single number; median resists outliers).
  Absolute numbers are noisy ±30% (already documented in the cookbook); the
  **cross-engine ratio at a fixed size is the stable signal** — lead with
  ratios in the narrative, absolutes in the table.
- **Determinism.** Synthetic grids from a fixed seed; OSM extracts pinned by
  cached content hash (Overpass is not time-reproducible). Fixture hashes in
  `fixtures.toml` fail loudly if an input silently changed.
- **Isolation.** Timing pass and memory pass are separate (tracemalloc/psutil
  perturb timing). One engine per subprocess for cold (duckdb connection state
  and OS file cache don't leak across engines).
- **CI stability.** GitHub runners are shared and variable; keep the strict
  per-PR gate on **deterministic** signals (payload bytes; micro pure-function
  means with a generous 2× guard) and push noisy wall-clock macro numbers to
  nightly on a more stable target.

## 10. Engine matrix & honest caveats

Matrix: `{pandas, polars, ibis-duckdb} × {S, M, L} × {network_create(osm,
csv, parquet, [overture]), selection(×cases), viz_pack}`. Skip cells cleanly
when an extra is absent (`list_engines()` gate, as the OSM smoke test does).

Caveats to print with every published table:

1. **DuckDB memory isn't in the Python heap.** ibis-duckdb numbers use process
   RSS; duckdb can spill to disk under `memory_limit` (neither tracemalloc nor
   RSS captures spilled bytes). Do not compare duckdb's memory to pandas'
   in-heap memory as if they measured the same thing.
2. **Selection/viz are pandas-bound.** `resolve_frames` and `pack_network`
   operate on materialized pandas frames; the engine axis for those ops
   measures **materialize-to-pandas cost**, not three resolver implementations.
3. **OSM fetch is network I/O.** Excluded from the engine comparison; reported
   separately (and cached, so it's ~0 on re-runs).
4. **Absolute numbers are machine- and noise-dependent** (±30%); ratios at
   fixed size are the signal.
5. **osmnx/osm2gmns baselines are directional**, not apples-to-apples
   (different simplification + directed-link conventions) — sanity check, not
   a speed claim. (Carried from the existing cookbook.)

## 11. Phased plan

- **Phase 0 — foundations (small).** Add `psutil` to a `bench` extra; add the
  two-pass (time/memory) capture helpers over the primitives in §4; define
  `benchmarks/fixtures.toml` with S entries only. Extend the `netstead bench`
  JSON with the `env` block + memory fields.
- **Phase 1 — network creation (the headline).** Ship `scripts/bench_osm_build.py`
  (the doc already advertises it) generalized into `benchmarks/runner.py`:
  engine × {csv, parquet, osm, synthetic} × {S, M} with time + memory + count
  assertions. Produces the first advertisable table.
- **Phase 2 — provisioning + L tier.** `benchmarks/provision.py` with the
  Overpass content-addressed cache; add the M-county bbox and RDU-metro L
  extract; CI `actions/cache` wiring. Now the 269k headline is reproducible.
- **Phase 3 — selection + viz.** Versioned selection cases (StubParser,
  cold/warm) into the runner; `pack_network` time + payload + breakdown. Wire
  `resolve_frames` / `pack_network` / WKT-parse micro-benchmarks into
  `tests/bench/` under `-m perf` so `bench.yml` guards them per-PR.
- **Phase 4 — regression gating + rendered outputs.** Macro comparator with
  per-operation tolerances + strict payload cap; Markdown advertising renderer;
  publish the first README table. Re-fit `cost_model.COEFFICIENTS` from the
  emitted numbers (closes issue #126's loop).
- **Phase 5 — opt-in render tier (deferred).** Playwright FPS/load behind
  `-m render`, nightly/manual only, advertising-only. Consider asv-style
  history dashboards only if long-term trend tracking becomes a real need.

## 12. Open questions

- Home for `benchmarks/` — workspace root (out of the wheel) is the current
  recommendation; confirm.
- M-tier real fixture — a specific NC county bbox vs synthetic grid as the
  *committed default*? (Recommendation: synthetic for the CI gate, real bbox
  cached for advertising.)
- Whether to expose Layer A as a `netstead bench-suite` CLI subcommand vs a
  standalone `benchmarks/runner.py` script (CLI is discoverable; script keeps
  bench machinery out of the shipped package — leaning script).
- DuckDB `memory_limit` setting during L runs — cap it (to force a spill and
  measure that honestly) or leave default? Affects what the RSS number means.
