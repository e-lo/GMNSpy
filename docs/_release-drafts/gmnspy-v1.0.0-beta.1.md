# gmnspy v1.0.0-beta.1 — first public preview of v1.0

> **This is a public preview, not GA.** The API is stable enough to build against; we expect bug reports and small breaking changes before `v1.0.0`. See [BETA.md](https://github.com/e-lo/GMNSpy/blob/main/BETA.md) for the beta program.

> **No in-place upgrade from v0.3.x.** v1.0 is a clean rewrite — see the [migration guide](https://github.com/e-lo/GMNSpy/blob/main/packages/gmnspy/docs/migration/v0.3-to-v1.0.md).

## What changed (vs v0.3.5)

The whole codebase, in one sentence: GMNS-specific tools sit on top of a generic Frictionless engine ([`datagrove`](https://pypi.org/project/datagrove/)), with multi-version spec support, lazy ibis + DuckDB by default, network-aware scoping, data-quality rules beyond spec compliance, an HTTP server + MCP surface for AI agents, and a CLI / notebook / programmatic API that share the same objects.

## Quick start

```bash
uv add 'gmnspy[all]==1.0.0b1'        # uv (recommended)
pip install 'gmnspy[all]==1.0.0b1'   # pip

gmnspy doctor                        # confirm install
```

```python
import gmnspy
from gmnspy.fixtures import leavenworth

net = gmnspy.read(leavenworth.csv_dir())
report = gmnspy.validate(net)
print(f"{net.links.count()} links, {len(report.issues)} validation issues")
```

## Highlights

- **Three usage modes, one core.** CLI (`gmnspy <cmd>`), notebook (`Network._repr_html_`), programmatic (`gmnspy.read`, `gmnspy.validate`).
- **Multi-version GMNS** out of the box — `0.95`, `0.96`, `0.97`. Default = `0.97`; override with `spec_version="0.96"`.
- **`gmnspy quality`** — rule pack for issues beyond the spec (high-speed-residential, disconnected components, lane-count mismatch, sharp-angle bends, …). Plugin-extensible.
- **Network-aware scope** (`gmnspy.scope.from_nodes`, `from_link`, `from_point`, `connected_component`, …). Chainable. Returns a scoped Network with FK chain pre-filtered.
- **`gmnspy[clean]`** — network editing with atomic rollback + audit log.
- **`gmnspy[server]`** — self-hostable FastAPI server with pluggable auth. Ships `Dockerfile` + `docker-compose.example.yml`.
- **`gmnspy[mcp]`** — MCP server for Claude Desktop / Claude Code. Exposes read / describe / query / scope / validate / quality_check / edit_session tools.
- **`gmnspy doctor`** — install diagnostic. **`gmnspy bench`** — read/validate/connectivity timings.
- **Bundled Leavenworth, WA fixture** so you can try things without finding data.
- **AI-first surface** — `--json` on every CLI command; `llms.txt` / `ai/api-index.json` auto-generated from docs.

## Breaking changes from v0.3.x

Everything. See [migration guide](https://github.com/e-lo/GMNSpy/blob/main/packages/gmnspy/docs/migration/v0.3-to-v1.0.md). Biggest moves:

- `gmnspy.read_gmns_network(path)` → `gmnspy.read(path)`
- `gmnspy.schema.read_schema(path)` → `gmnspy.load_gmns_spec(version="0.97")`
- DataFrames are no longer the lingua franca — operations are lazy ibis expressions; call `.to_pandas()` / `.to_polars()` at the boundary.
- Single-file imports under `gmnspy.{schema,validation,utils}` moved to `datagrove.*`.

## Compatibility

- Python 3.11, 3.12, 3.13.
- macOS + Linux. Windows is community-supported only (no CI coverage).
- Optional extras: `clean`, `server`, `mcp`, `notebook`, `all`.

## Known limitations

- `gmnspy.bench` is CLI-only — no programmatic API yet (v1.1).
- HTML report doesn't yet embed a Vega-Lite map view for geo-located issues.
- `gmnspy.clean` lacks `split_link_at_node` and `snap_to_reference` (v1.1).

## How to report issues

[**Beta-feedback issue template →**](https://github.com/e-lo/GMNSpy/issues/new?template=beta-feedback.md)

The template asks for `gmnspy doctor --json` output and the shortest reproduction command — please include both when you can.

## Acknowledgements

This beta wouldn't exist without the upstream [zephyr-data-specs/GMNS](https://github.com/zephyr-data-specs/GMNS) project. The new architecture and AI surface borrow heavily from patterns proven in Frictionless Data Packages, ibis-project, and the broader open-data ecosystem.

## Full CHANGELOG

[packages/gmnspy/CHANGELOG.md](https://github.com/e-lo/GMNSpy/blob/main/packages/gmnspy/CHANGELOG.md)

**Full Changelog**: https://github.com/e-lo/GMNSpy/commits/gmnspy-v1.0.0-beta.1
