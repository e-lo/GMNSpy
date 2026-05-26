---
title: Quickstart
audience: users
kind: howto
summary: Install, load the bundled Leavenworth fixture, run validation + quality + scope in five minutes.
---

# Quickstart

## When to use this

You're new to `gmnspy` and want to see what it does on a real GMNS network before reading anything else. Time budget: five minutes.

## Quick example

```shell-session
$ pip install 'gmnspy[clean]'
$ python -c "
from gmnspy import Network
from gmnspy.fixtures import leavenworth
net = Network.from_source(leavenworth.csv_dir())
print(f'{net.spec_version}: {net.links.count()} links, {net.nodes.count()} nodes')
"
0.97: 214 links, 75 nodes
```

You just loaded the bundled Leavenworth WA network through the default ibis + duckdb engine. Nothing was materialised — `net.links` is a lazy expression.

## Step-by-step

### 1. Install

```shell-session
$ pip install 'gmnspy[clean]'
```

The `[clean]` extra brings in `shapely` + `igraph` so the connectivity + geometry ops work. For a pure-read install, plain `pip install gmnspy` is enough.

### 2. Load the bundled fixture

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth

net = Network.from_source(leavenworth.csv_dir())
```

The fixture is a small real network (Leavenworth, WA) bundled with the package. `Network.from_source` accepts the same surface as `datagrove.Package.from_source`: local paths, URLs (`s3://`, `https://`, `duckdb://`), or directories of CSV / Parquet / DuckDB / zip-CSV.

You should see something like:

```text
0.97: 214 links, 75 nodes
```

### 3. Validate against the spec

```python
report = net.validate()
print(f"issues: {len(report.issues)} ({report.spec_version})")
```

The validator runs four passes — structural (required tables / files), schema (field types + constraints), foreign-key (cross-table integrity), sync-state (have any FKs gone stale since a previous edit?). The Leavenworth fixture is clean; expect zero ERROR-severity findings.

### 4. Run data-quality checks

```python
from datagrove.quality import run_quality

qreport = run_quality(net)
for issue in qreport.issues[:5]:
    print(f"  {issue.severity.value:9} {issue.code:35} {issue.message[:60]}")
```

This runs the GMNS rule pack: high-speed-residential, lane-count-mismatch, sharp-angle-bends, etc. Findings are WARNING / INFO by default — the spec is silent on these, but they're frequent data-quality misses.

### 5. Scope to a subgraph

```python
from gmnspy.scope import from_node

scoped = from_node(net, 1, network_buffer="200m").apply()
print(f"scoped: {scoped.links.count()} links, {scoped.nodes.count()} nodes")
```

That's a 200-metre network-distance buffer around node 1. The returned `Network` has every table pre-filtered by FK chain — only `link_tod` / `lane` rows whose `link_id` survived the scope are kept.

### 6. Or run the same thing from the CLI

Every command supports `--json` for piping into scripts or AI agents:

```shell-session
$ gmnspy info --json packages/gmnspy/gmnspy/fixtures/leavenworth/csv
$ gmnspy validate --json packages/gmnspy/gmnspy/fixtures/leavenworth/csv
$ gmnspy quality --json packages/gmnspy/gmnspy/fixtures/leavenworth/csv
$ gmnspy scope from-node packages/gmnspy/gmnspy/fixtures/leavenworth/csv 1 --network-buffer 200m
```

## Common variations

| You want... | Change |
|---|---|
| A different GMNS spec version | `Network.from_source(path, spec_version="0.96")` |
| A different backend engine | `Network.from_source(path, engine=PandasEngine())` |
| Read from S3 with credentials | `Network.from_source("s3://bucket/net/")` — credentials cascade: kwarg → `DATAGROVE_CRED_<host>_TOKEN` env → keyring → `.netrc` |
| Write the scoped network out | `scoped.write("./scoped.parquet")` |
| Run the data-quality pack with custom thresholds | `from datagrove.quality import RuleConfig; run_quality(net, config={"quality.high_speed_residential": RuleConfig(thresholds={"speed_limit_mph": 30.0})})` |

## Pitfalls

* **Auto-build of the graph index on large networks** — the first `from_node` / `connected_component` call on a > 50k-node network silently builds the igraph adjacency. Pre-build with `net.build_indexes(graph=True)` if you want to control timing, or set `GMNSPY_AUTO_INDEX_THRESHOLD` to raise the silent-build bar.
* **Duplicate-near-nodes default is tight** (`epsilon_units=1e-5`). Networks in WGS84 degrees barely trigger it; networks in projected meters need an explicit threshold via `RuleConfig`.
* **Editing requires a `Session`**. Don't mutate tables directly — open `with datagrove.editing.Session(net) as s:` and pass `s` into the `gmnspy.clean.*` ops. The cookbook recipe walking through this is being filled in this wave.

## See also

* [Cookbook](cookbook/index.md) — task-oriented recipes for the common workflows.
* [API reference](reference/api.md) — every symbol you saw above.
* [Architecture](../shared/architecture.md) — design rationale for the defaults.
