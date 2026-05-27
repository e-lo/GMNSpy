---
title: Run the bundled benchmarks
audience: users
kind: howto
summary: gmnspy bench measures load + validate + connectivity timings per phase on your network + hardware.
---

# Run the bundled benchmarks

## When to use this

You want a fast read on how `gmnspy` performs on your hardware against your network — sizing a server, comparing engines (`ibis` / `pandas` / `polars`), or tracking CI regressions over time.

## Quick example

Run the bench against the bundled Leavenworth fixture. Add `--json` to any `gmnspy` (or `datagrove`) CLI command and the output becomes a single machine-readable JSON document on stdout — pipe into `jq`, save to a file, feed to a script or AI agent. Default output is human-readable rich panels:

```bash
gmnspy bench packages/gmnspy/gmnspy/fixtures/leavenworth/csv --json
```

Expected:

```json
{
  "source": "packages/gmnspy/gmnspy/fixtures/leavenworth/csv",
  "engine": "ibis",
  "phases": [
    {"name": "load",         "seconds": 0.082},
    {"name": "validate",     "seconds": 0.124},
    {"name": "quality",      "seconds": 0.041},
    {"name": "connectivity", "seconds": 0.038}
  ],
  "total_seconds": 0.285
}
```

## Step-by-step

### 1. Run against the bundled reference

The Leavenworth fixture is small (214 links / 75 nodes) — total runtime is under a second. It's a baseline, not a benchmark; useful for confirming nothing's wrong with the install:

```bash
gmnspy bench packages/gmnspy/gmnspy/fixtures/leavenworth/csv
```

### 2. Run against your own network

Same command, different path. The bench accepts the same source surface as `Network.from_source` — local dirs, `s3://`, `duckdb://`, etc.:

```bash
gmnspy bench /path/to/my/network --json > bench.json
```

### 3. Compare engines

`ibis` (the default) typically wins for partitioned Parquet on a fast disk; `polars` wins for CSV bulk loads; `pandas` is the slowest of the three on anything > 100k rows but is the most portable:

```bash
gmnspy bench /path/to/net --engine ibis --json > ibis.json
gmnspy bench /path/to/net --engine pandas --json > pandas.json
gmnspy bench /path/to/net --engine polars --json > polars.json
```

### 4. Capture a baseline for CI

For regression tracking, save a baseline JSON in-repo and compare on every PR. A 30% tolerance is reasonable for the Leavenworth fixture given timing noise; tighten on larger networks:

```bash
gmnspy bench packages/gmnspy/gmnspy/fixtures/leavenworth/csv --json > bench-baseline.json
# in CI:
gmnspy bench packages/gmnspy/gmnspy/fixtures/leavenworth/csv --json > bench-current.json
python -c "
import json
b = json.load(open('bench-baseline.json'))['total_seconds']
c = json.load(open('bench-current.json'))['total_seconds']
assert c < b * 1.3, f'regression: {c:.2f}s vs baseline {b:.2f}s (+{(c/b-1)*100:.0f}%)'
"
```

### 5. Read the JSON

The shape is stable inside a major version. Each phase is one logical operation: `load` opens the package and instantiates the engine; `validate` runs structural + schema + FK + sync passes; `quality` runs the GMNS rule pack; `connectivity` builds the igraph index and counts components:

```json
{
  "source": "...",
  "engine": "ibis",
  "spec_version": "0.97",
  "table_counts": {"link": 214, "node": 75, "lane": 412, ...},
  "phases": [
    {"name": "load",         "seconds": 0.082},
    {"name": "validate",     "seconds": 0.124},
    {"name": "quality",      "seconds": 0.041},
    {"name": "connectivity", "seconds": 0.038}
  ],
  "total_seconds": 0.285
}
```

## Common variations

???+ note "Default — Leavenworth fixture, JSON out"
    Quickest smoke-test that the install works and the engine is wired up.

    ```bash
    gmnspy bench packages/gmnspy/gmnspy/fixtures/leavenworth/csv --json
    ```

??? note "Just the total seconds (for shell pipelines)"
    Pipe through `jq` to extract a single number.

    ```bash
    gmnspy bench ./my-net --json | jq -r .total_seconds
    ```

??? note "Phase breakdown as CSV"
    For charting or copying into a spreadsheet.

    ```bash
    gmnspy bench ./my-net --json | jq -r '.phases[] | [.name,.seconds] | @csv'
    ```

??? note "CI regression check (one-liner)"
    Fails the CI step if the total exceeds your budget.

    ```bash
    gmnspy bench ./my-net --json | jq -e '.total_seconds < 5.0'
    ```

??? note "Engine sweep"
    Loop over engines in shell and compare.

    ```bash
    for e in ibis pandas polars; do
      gmnspy bench ./my-net --engine "$e" --json > "bench-$e.json"
    done
    ```

## Pitfalls

* **Micro-network timing is noisy.** On Leavenworth the absolute numbers fluctuate by ±30% between runs. Use it to confirm correctness, not for engine choice — switch to a regional-scale network before drawing conclusions.
* **First run pays the GraphIndex build cost.** Subsequent calls hit the in-memory cache, so the second run is faster. For a representative cold-start number, restart Python between runs; for a hot-cache number, run the bench twice and take the second.
* **`--engine polars` needs the `polars` extra.** `pip install 'gmnspy[polars]'`. Without it the CLI errors before timing anything.
* **Quality + connectivity require `[clean]`.** A pure `pip install gmnspy` skips those phases (they show as `null` seconds in the JSON).

## See also

* [Convert CSV ↔ Parquet ↔ DuckDB](https://e-lo.github.io/GMNSpy/datagrove/cookbook/convert-formats/) — the format you load from dominates `load` time.
* [API reference](../reference/api.md) — `Network.from_source()` + `.validate()` for programmatic equivalents (the bench command itself is CLI-only at v1.0; a programmatic API is tracked for v1.1).
