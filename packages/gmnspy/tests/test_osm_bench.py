"""Perf-marked cross-engine smoke for the OSM build path.

Runs the records -> Network build on each installed engine (ibis/pandas/polars)
over a synthetic grid, asserting correctness (counts + clean GMNS validation).
Doubles as the regression hook the bench workflow targets; timings are measured
by the standalone ``scripts/bench_osm_build.py`` harness, not asserted here.
"""

from __future__ import annotations

import pytest
from datagrove.engines import list_engines, resolve_engine
from gmnspy.osm import build, convert


def _grid(n: int):
    nodes = {row * n + col + 1: (-71.0 + 0.001 * col, 42.0 + 0.001 * row) for row in range(n) for col in range(n)}
    ways = []
    way_id = 0
    for row in range(n):
        way_id += 1
        ways.append({"id": way_id, "nodes": [row * n + c + 1 for c in range(n)], "tags": {"highway": "residential"}})
    for col in range(n):
        way_id += 1
        ways.append({"id": way_id, "nodes": [r * n + col + 1 for r in range(n)], "tags": {"highway": "residential"}})
    return nodes, ways


@pytest.mark.perf
@pytest.mark.parametrize("engine_name", ["ibis", "pandas", "polars"])
def test_build_is_engine_agnostic(engine_name):
    if engine_name not in list_engines():
        pytest.skip(f"{engine_name} engine not installed")
    nodes, ways = _grid(8)  # 64 nodes, 16 ways
    node_recs, link_recs = convert.build_node_link_tables(nodes, ways)

    net = build.network_from_records(node_recs, link_recs, engine=resolve_engine(engine_name))

    assert net.nodes.count() == 64
    assert net.engine.name == engine_name
    errors = [i for i in net.validate().issues if i.severity.value == "error"]
    assert errors == [], errors
