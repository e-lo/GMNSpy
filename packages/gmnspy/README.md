# GMNSpy

Python toolkit for the [General Modeling Network Specification (GMNS)](https://github.com/zephyr-data-specs/GMNS) — Zephyr Foundation's open standard for routable transportation network data.

**Status:** v1.0 in development on `refactor/v1.0`. See `docs/PRD.md` for the product requirements document.

## What it provides

- **Read/write** GMNS networks from CSV, Parquet (partitioned), DuckDB, zipped CSV, or remote URLs (with credentials).
- **Validation** — schema, structural, foreign-key, sync-state (out-of-sync awareness on write), and configurable data-quality rules.
- **Network-aware scoping** — bbox, polygon, BFS / shortest-path subgraph, network-distance buffer, spatial buffer from any link/point/node.
- **Editing** (`gmnspy[clean]`) — simplify geometry, merge close nodes, snap to reference, etc., with atomic rollback + audit log.
- **Self-hostable API server** (`gmnspy[server]`) — FastAPI + auto-OpenAPI for spinning up your own GMNS data service.
- **AI accessibility** (`gmnspy[mcp]`) — MCP server entry point; Skills in the monorepo `skills/` directory.
- **CLI, notebook, and programmatic API** — same operations, three surfaces.

## Install

```bash
pip install gmnspy                       # core
pip install 'gmnspy[clean]'              # add network editing + cleanup
pip install 'gmnspy[server]'             # add self-hostable API server
pip install 'gmnspy[mcp]'                # add MCP server for AI agents
pip install 'gmnspy[notebook]'           # add Jupyter widgets
pip install 'gmnspy[all]'                # everything
```

## Quickstart

```python
import gmnspy

net = gmnspy.read("path/to/network.gmns")           # auto-detects format
report = gmnspy.validate(net)                       # schema + FK + data-quality
print(report)                                       # rich console
report.to_html("report.html")                       # interactive single-file HTML

sub = net.scope.from_nodes([1, 2, 3], path_between=True).buffer_network("0.5mi")
sub.write("subset.parquet")
```

## Repo

Developed in the [GMNSpy monorepo](https://github.com/e-lo/GMNSpy) under `packages/gmnspy/`.
