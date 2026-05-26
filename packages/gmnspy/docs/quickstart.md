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

The fastest way to confirm `gmnspy` is wired up correctly is to install it, load the bundled Leavenworth, WA fixture, and print a one-line summary. The whole sequence runs in under thirty seconds on a cold cache.

```bash
pip install 'gmnspy[clean]'
```

Then in Python:

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth

net = Network.from_source(leavenworth.csv_dir())
print(f"{net.spec_version}: {net.links.count()} links, {net.nodes.count()} nodes")
```

Expected:

```text
0.97: 214 links, 75 nodes
```

You just loaded the bundled Leavenworth network through the default ibis + DuckDB engine. Nothing was materialised — `net.links` is a lazy expression; only the integer count came back from DuckDB to Python.

## Step-by-step

### 1. Install

Pick the extras you need. The `[clean]` extra brings in `shapely` and `igraph` so the geometry and connectivity ops work; a plain `pip install gmnspy` is enough for read-only validation work.

```bash
pip install 'gmnspy[clean]'
```

`datagrove` comes along as a transitive dependency — you don't install both packages.

### 2. Load the bundled fixture

The fixture is a small real network (Leavenworth, WA — roughly 600 m of OSM-derived street grid) bundled inside the `gmnspy` wheel, so the example below runs without any download. `Network.from_source` accepts the same surface as `datagrove.Package.from_source`: local paths, URLs (`s3://`, `https://`, `duckdb://`), or directories of CSV / Parquet / DuckDB / zip-CSV.

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth

net = Network.from_source(leavenworth.csv_dir())
```

The result is a lazy `Network` object — its tables haven't been read yet. Print a quick summary to confirm it loaded:

```python
print(f"{net.spec_version}: {net.links.count()} links, {net.nodes.count()} nodes")
```

Expected:

```text
0.97: 214 links, 75 nodes
```

In a Jupyter notebook, evaluating `net` on its own renders an HTML summary card with the spec version, table counts, and a thumbnail map.

#### Outputs

![Network summary card for the Leavenworth fixture](assets/screenshots/leavenworth-network-card.png){ .screenshot }
*Network summary card (`net._repr_html_()` rendered in a notebook). Shows spec version, table inventory with row counts, and a thumbnail of the link geometry.*

### 3. Validate against the spec

Validation runs four passes in a single call: **structural** (required tables and files), **schema** (per-field types and constraints), **foreign-key** (cross-table integrity), and **sync-state** (have any FKs gone stale since a previous edit?). The Leavenworth fixture is clean by construction, so you should see zero ERROR-severity findings.

```python
report = net.validate()
print(f"issues: {len(report.issues)} ({report.spec_version})")
```

In a notebook, `report` on its own renders an HTML card grouped by severity.

#### Outputs

![Validation report card for the Leavenworth fixture](assets/screenshots/leavenworth-validation-report.png){ .screenshot }
*Validation report card (`report._repr_html_()` rendered in a notebook). Zero ERRORs since Leavenworth is clean; a few DATA_QUALITY warnings from the residential-speed rule.*

### 4. Run data-quality checks

The data-quality rule pack covers things the spec is silent on but every real network gets wrong sooner or later — high-speed-residential, lane-count mismatch, sharp-angle bends, near-duplicate nodes, disconnected components, implausible v/c ratios, missing critical fields. Findings come back as WARNING or INFO by default.

```python
from datagrove.quality import run_quality

qreport = run_quality(net)
for issue in qreport.issues[:5]:
    print(f"  {issue.severity.value:9} {issue.code:35} {issue.message[:60]}")
```

#### Outputs

![Quality report card for the Leavenworth fixture](assets/screenshots/leavenworth-quality-report.png){ .screenshot }
*Quality report card (`qreport._repr_html_()` rendered in a notebook). Severity-grouped findings — Leavenworth's tertiary streets with 25-30 mph posted speeds trip the `quality.high_speed_residential` rule when configured with a low threshold.*

### 5. Scope to a subgraph

The scope module lets you carve a smaller network out of a larger one without writing FK-pushdown SQL by hand. `from_node` builds a network-distance-bounded subgraph around a seed node; every related table (`lane`, `link_tod`, `movement`, signal control) is pre-filtered so the result is still a self-consistent GMNS network.

```python
from gmnspy.scope import from_node

scoped = from_node(net, 1, network_buffer="200m").apply()
print(f"scoped: {scoped.links.count()} links, {scoped.nodes.count()} nodes")
```

That's a 200-metre Dijkstra-bounded buffer around node 1.

#### Outputs

![Scoped subgraph rendered next to the full Leavenworth network](assets/screenshots/leavenworth-scoped-map.png){ .screenshot }
*Scope visualisation. The 200 m network-distance buffer around node 1 (highlighted green) over the full Leavenworth network (grey context). Spatially nearby links that are only reachable via long detours fall outside the buffer.*

### 6. Or run the same thing from the CLI

The CLI mirrors the Python API one-for-one. The same fixture lives at `packages/gmnspy/gmnspy/fixtures/leavenworth/csv` in the repo, so you can point the CLI at it directly.

```bash
gmnspy info packages/gmnspy/gmnspy/fixtures/leavenworth/csv
gmnspy validate packages/gmnspy/gmnspy/fixtures/leavenworth/csv
gmnspy quality packages/gmnspy/gmnspy/fixtures/leavenworth/csv
gmnspy scope from-node packages/gmnspy/gmnspy/fixtures/leavenworth/csv 1 --network-buffer 200m
```

By default `gmnspy` prints colorized tables and panels for humans. Add `--json` and you get a single machine-readable JSON document on stdout instead — useful for scripting, CI checks, or feeding the output to an AI agent.

```bash
gmnspy validate --json packages/gmnspy/gmnspy/fixtures/leavenworth/csv | jq '.issues | length'
```

## Common variations

Each accordion below is one alternative to the defaults used above. The first (most common) is expanded; the rest are collapsed — open the one that matches your situation.

???+ note "Pick a different GMNS spec version"
    The vendored versions are 0.95, 0.96, and 0.97; default is 0.97. Networks load against the version they were written against — no silent upgrades.

    ```python
    net = Network.from_source(path, spec_version="0.96")
    ```

??? note "Switch the backend engine to pandas"
    Default is `IbisEngine` (lazy, DuckDB-backed). Switch to pandas when you need eager evaluation or DataFrame ergonomics for downstream code.

    ```python
    from datagrove.engines.pandas_engine import PandasEngine

    net = Network.from_source(path, engine=PandasEngine())
    ```

??? note "Read from S3 with credentials"
    Credentials resolve via a cascade: keyword arg → `DATAGROVE_CRED_<host>_TOKEN` env var → OS keyring → `.netrc`. No code changes if your environment is already set up.

    ```python
    net = Network.from_source("s3://bucket/network/")
    ```

??? note "Write the scoped network out"
    The output format follows the file extension — `.parquet`, `.duckdb`, or a directory for CSV.

    ```python
    scoped.write("./scoped.parquet")
    ```

??? note "Run the data-quality pack with custom thresholds"
    Per-rule config keys override defaults. The example below tightens the residential-speed threshold to 30 mph.

    ```python
    from datagrove.quality import RuleConfig, run_quality

    qreport = run_quality(
        net,
        config={
            "quality.high_speed_residential": RuleConfig(
                thresholds={"speed_limit_mph": 30.0}
            )
        },
    )
    ```

## Pitfalls

* **Auto-build of the graph index on large networks.** The first `from_node` or `connected_component` call on a network larger than ~50k nodes silently builds the igraph adjacency. Pre-build with `net.build_indexes(graph=True)` if you want to control the timing, or set `GMNSPY_AUTO_INDEX_THRESHOLD` to raise the silent-build bar.
* **Duplicate-near-nodes default threshold is tight** (`epsilon_units=1e-5`). Networks in WGS84 degrees barely trigger it; networks in projected meters need an explicit threshold via `RuleConfig`.
* **Editing requires a `Session`.** Don't mutate tables directly — open `with datagrove.editing.Session(net) as s:` and pass `s` into the `gmnspy.clean.*` ops. The cookbook recipe walking through this is being filled in this wave.

## See also

* [Cookbook](cookbook/index.md) — task-oriented recipes for the common workflows.
* [Visual tour](visual-tour.md) — see every step above rendered as maps, cards, and diffs in a notebook.
* [API reference](reference/api.md) — every symbol you saw above.
* [Architecture](https://e-lo.github.io/GMNSpy/datagrove/architecture/) — design rationale for the defaults.
