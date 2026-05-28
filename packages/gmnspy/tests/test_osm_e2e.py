"""End-to-end: synthetic OSM grid -> Network -> GMNS validate -> write/reread round-trip."""

from __future__ import annotations

from datagrove.engines.pandas_engine import PandasEngine
from gmnspy import Network
from gmnspy.osm import build, convert


def _grid(n: int):
    """Build an n-by-n grid of OSM nodes plus row/column ways (all two-way residential)."""
    nodes = {}
    for row in range(n):
        for col in range(n):
            node_id = row * n + col + 1
            nodes[node_id] = (-71.0 + 0.001 * col, 42.0 + 0.001 * row)
    ways = []
    way_id = 0
    for row in range(n):
        way_id += 1
        ways.append(
            {"id": way_id, "nodes": [row * n + col + 1 for col in range(n)], "tags": {"highway": "residential"}}
        )
    for col in range(n):
        way_id += 1
        ways.append(
            {"id": way_id, "nodes": [row * n + col + 1 for row in range(n)], "tags": {"highway": "residential"}}
        )
    return nodes, ways


def test_generated_network_passes_gmns_validation():
    nodes, ways = _grid(3)
    node_recs, link_recs = convert.build_node_link_tables(nodes, ways)
    net = build.network_from_records(node_recs, link_recs, engine=PandasEngine())

    report = net.validate()
    errors = [i for i in report.issues if i.severity.value == "error"]
    assert errors == [], errors
    assert report.spec_version == "0.97"


def test_write_csv_and_reread_round_trip(tmp_path):
    nodes, ways = _grid(3)
    node_recs, link_recs = convert.build_node_link_tables(nodes, ways)
    net = build.network_from_records(node_recs, link_recs, engine=PandasEngine())

    dest = tmp_path / "net"
    net.write(dest, format="csv", overwrite=False)

    reread = Network.from_source(dest, engine=PandasEngine())
    assert reread.nodes.count() == net.nodes.count()
    assert reread.links.count() == net.links.count()
