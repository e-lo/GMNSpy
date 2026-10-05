# Netstead

Python toolkit for the [General Modeling Network Specification (GMNS)](https://github.com/zephyr-data-specs/GMNS) — Zephyr Foundation's open standard for routable transportation network data.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/e-lo/netstead/blob/main/packages/netstead/docs/notebooks/quickstart.ipynb) — try the 5-cell quickstart in your browser, no install.

**Status:** v1.0 in development on `main`. See `docs/PRD.md` for the product requirements document.

## What it provides

- **Read/write** GMNS networks from CSV, Parquet (partitioned), DuckDB, zipped CSV, or remote URLs (with credentials).
- **Validation** — schema, structural, foreign-key, sync-state (out-of-sync awareness on write), and configurable data-quality rules.
- **Network-aware scoping** — bbox, polygon, BFS / shortest-path subgraph, network-distance buffer, spatial buffer from any link/point/node.
- **Editing** (`netstead[clean]`) — simplify geometry, merge close nodes, snap to reference, etc., with atomic rollback + audit log.
- **Self-hostable API server** (`netstead[server]`) — FastAPI + auto-OpenAPI for spinning up your own GMNS data service.
- **AI accessibility** (`netstead[mcp]`) — MCP server entry point; Skills in the monorepo `skills/` directory.
- **CLI, notebook, and programmatic API** — same operations, three surfaces.

## Install

Pick the tool you already use — these are equivalent:

```bash
# uv (recommended — fastest, handles workspace projects + lockfiles)
uv add netstead

# uv pip (drop-in pip replacement, no project file needed)
uv pip install netstead

# pip (classic)
pip install netstead

# pipx (CLI-only, isolated env; gives you the `netstead` command without
#       polluting your project env)
pipx install netstead
```

`corral` comes along automatically — you don't install both.

### Optional extras

```bash
uv add 'netstead[osm]'          # build a GMNS network from OpenStreetMap (requests + pyyaml)
uv add 'netstead[clean]'        # network editing + cleanup (shapely + igraph + pyproj)
uv add 'netstead[server]'       # self-hostable HTTP server (FastAPI + uvicorn)
uv add 'netstead[mcp]'          # MCP server for Claude Desktop / Code
uv add 'netstead[notebook]'     # scope-builder Jupyter widget (ipywidgets)
uv add 'netstead[all]'          # everything above
```

Combine extras with commas: `uv add 'netstead[clean,server,mcp]'`.

> **Note:** the basic `_repr_html_` for `Network` / `ValidationReport` /
> `EditResult` works **without** `[notebook]` — that extra only adds the
> interactive scope-builder widget.

## Quickstart

```python
import netstead
from netstead.fixtures import leavenworth     # bundled example network

net = netstead.read(leavenworth.csv_dir())     # auto-detects format
report = netstead.validate(net)                # schema + FK + data-quality
print(report)                                # rich console
# report.to_html("report.html")              # writes interactive single-file HTML

# Network-aware scope: BFS subgraph + half-mile network buffer
# sub = net.scope.from_nodes([1, 2, 3], path_between=True).buffer_network("0.5mi")
# sub.write("subset.parquet")
```

## Repo

Developed in the [Netstead monorepo](https://github.com/e-lo/netstead) under `packages/netstead/`.
