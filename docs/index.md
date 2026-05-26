---
title: GMNSpy + datagrove
audience: both
summary: Python toolkit for the General Modeling Network Specification — fast I/O at regional scale, validation with sync-state awareness, network-aware scoping, data-quality checks, editing with atomic rollback, CLI + notebook + HTTP + MCP surfaces.
---

# GMNSpy + datagrove

Two PyPI packages, one repo:

* **`datagrove`** — generic engine for Frictionless tabular data packages. Lazy ibis (DuckDB) by default; pandas / polars as opt-in. Reads CSV / Parquet / DuckDB / zip-CSV from local paths + URLs with credentials cascade.
* **`gmnspy`** — GMNS-specific bindings on top of `datagrove`. Adds the network class, vendored GMNS spec (0.95 / 0.96 / 0.97), connectivity + scope ops, data-quality rule pack, optional editing tools, optional HTTP + MCP servers.

Install the GMNS package; datagrove comes along:

```text
$ pip install gmnspy           # core
$ pip install 'gmnspy[clean]'   # + shapely + igraph + editing
$ pip install 'gmnspy[server]'  # + FastAPI HTTP server
$ pip install 'gmnspy[mcp]'     # + MCP server for AI agents
```

## Where to go next

| If you want to... | Start here |
|---|---|
| Get a result in 5 minutes | [Quickstart](intro/quickstart.md) |
| Understand what GMNS is and why this exists | [What is GMNS?](intro/what-is-gmns.md) |
| See the bundled Leavenworth fixture in action | [Visual tour](intro/visual-tour.md) |
| Solve a specific task (read S3, scope, edit, …) | [Cookbook](cookbook/index.md) |
| Look up an API symbol | [API reference](reference/api.md) |
| Look up a GMNS table or field | [Schema reference](reference/spec.md) |
| Understand the architecture | [Architecture](architecture.md) |
| Upgrade from v0.3 | [Migration guide](migration/v0.3-to-v1.0.md) |
| Use this with Claude Code / Claude Desktop | [AI surface](ai/index.md) |

## The three usage modes

All three target the same data + the same validation + the same scope ops — choose by ergonomics, not capability.

=== "CLI"

    ```text
    $ gmnspy validate --json packages/gmnspy/gmnspy/fixtures/leavenworth/csv
    $ gmnspy info packages/gmnspy/gmnspy/fixtures/leavenworth/csv
    $ gmnspy quality --json packages/gmnspy/gmnspy/fixtures/leavenworth/csv
    ```

=== "Notebook"

    ```python
    from gmnspy import Network
    from gmnspy.fixtures import leavenworth

    net = Network.from_source(leavenworth.csv_dir())
    net                                # renders a card with spec_version + link/node counts
    net.validate()                     # renders a severity-grouped issue table
    ```

=== "Programmatic"

    ```python
    from gmnspy import Network
    from gmnspy.scope import from_nodes

    net = Network.from_source("s3://bucket/network/")
    scoped = from_nodes(net, [101, 202, 303], path_between=True).apply()
    scoped.write("./output.parquet")
    ```

=== "AI agent (MCP)"

    ```text
    $ gmnspy mcp serve                 # stdio MCP server for Claude Desktop / Claude Code
    ```

## Status

v1.0 is a clean-break rewrite of GMNSpy v0.3.x — see the [migration guide](migration/v0.3-to-v1.0.md) for the side-by-side API mapping. **Currently in beta**; tag `gmnspy-v1.0.0` ships when the [Phase 5 acceptance criteria](https://github.com/e-lo/GMNSpy/issues?q=label%3Ablocks-ga) are green.
