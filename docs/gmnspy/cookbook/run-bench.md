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

```shell-session
$ gmnspy bench packages/gmnspy/gmnspy/fixtures/leavenworth/csv --json
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

```shell-session
$ gmnspy bench packages/gmnspy/gmnspy/fixtures/leavenworth/csv
```

The Leavenworth fixture is small (214 links / 75 nodes) — total runtime is under a second. It's a baseline, not a benchmark; useful for confirming nothing's wrong with the install.

### 2. Run against your own network

```shell-session
$ gmnspy bench /path/to/my/network --json > bench.json
```

Same command, different path. The bench accepts the same source surface as `Network.from_source` — local dirs, `s3://`, `duckdb://`, etc.

### 3. Compare engines

```shell-session
$ gmnspy bench /path/to/net --engine ibis --json > ibis.json
$ gmnspy bench /path/to/net --engine pandas --json > pandas.json
$ gmnspy bench /path/to/net --engine polars --json > polars.json
```

Typical patterns: `ibis` (the default) wins for partitioned Parquet on a fast disk; `polars` wins for CSV bulk loads; `pandas` is the slowest of the three on anything > 100k rows but is the most portable.

### 4. Capture a baseline for CI

For regression tracking, save a baseline JSON in-repo and compare on every PR:

```shell-session
$ gmnspy bench packages/gmnspy/gmnspy/fixtures/leavenworth/csv --json > bench-baseline.json
$ # in CI:
$ gmnspy bench packages/gmnspy/gmnspy/fixtures/leavenworth/csv --json > bench-current.json
$ python -c "
import json
b = json.load(open('bench-baseline.json'))['total_seconds']
c = json.load(open('bench-current.json'))['total_seconds']
assert c < b * 1.3, f'regression: {c:.2f}s vs baseline {b:.2f}s (+{(c/b-1)*100:.0f}%)'
"
```

A 30% tolerance is reasonable for the Leavenworth fixture given timing noise; tighten on larger networks.

### 5. Read the JSON

The shape is stable inside a major version:

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

Each phase is one logical operation: `load` opens the package and instantiates the engine; `validate` runs structural + schema + FK + sync passes; `quality` runs the GMNS rule pack; `connectivity` builds the igraph index and counts components.

## Common variations

| You want... | Pipe through |
|---|---|
| Just the total | `jq -r .total_seconds bench.json` |
| Phase breakdown as CSV | `jq -r '.phases[] \| [.name,.seconds] \| @csv' bench.json` |
| CI regression check | save baseline `bench.json`; compare with `jq -e '.total_seconds < 5.0'` |
| Engine sweep | shell loop over `--engine ibis pandas polars` with `--json` |

## Pitfalls

* **Micro-network timing is noisy.** On Leavenworth the absolute numbers fluctuate by ±30% between runs. Use it to confirm correctness, not for engine choice — switch to a regional-scale network before drawing conclusions.
* **First run pays the GraphIndex build cost.** Subsequent calls hit the in-memory cache, so the second run is faster. For a representative cold-start number, restart Python between runs; for a hot-cache number, run the bench twice and take the second.
* **`--engine polars` needs the `polars` extra.** `pip install 'gmnspy[polars]'`. Without it the CLI errors before timing anything.
* **Quality + connectivity require `[clean]`.** A pure `pip install gmnspy` skips those phases (they show as `null` seconds in the JSON).

## See also

* [Convert CSV ↔ Parquet ↔ DuckDB](../../datagrove/cookbook/convert-formats.md) — the format you load from dominates `load` time.
* [API reference](../reference/api.md) — `gmnspy.bench.run_bench` for programmatic use.
