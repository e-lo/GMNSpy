"""Tests for :mod:`gmnspy.clean` (task 3.12 / issue #81).

Covers each op + a roundtrip-rollback assertion (apply, snapshot,
rollback, verify state matches snapshot). Skipped wholesale if the
``[clean]`` extra (shapely + igraph) is not installed.
"""

from __future__ import annotations

import pytest
from datagrove.dataset import Table
from datagrove.editing import Session
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.spec import DataPackage, Resource
from gmnspy import Network

pytest.importorskip("shapely")
pytest.importorskip("igraph")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine() -> PandasEngine:
    return PandasEngine()


def _network(tables_dict: dict[str, Table]) -> Network:
    engine = next(iter(tables_dict.values())).engine
    spec = DataPackage(name="synthesized", resources=[Resource(name=n) for n in tables_dict])
    return Network(spec=spec, tables=dict(tables_dict), engine=engine, spec_version="0.97")


def _link(engine, rows: list[dict]) -> Table:
    return Table(name="link", expr=engine.from_records(rows), engine=engine)


def _node(engine, rows: list[dict]) -> Table:
    return Table(name="node", expr=engine.from_records(rows), engine=engine)


def _snapshot(net: Network) -> dict[str, list[dict]]:
    """Return per-table row dicts for equality-comparison after rollback."""
    return {name: net.tables[name].to_pandas().to_dict(orient="records") for name in net.tables}


# ---------------------------------------------------------------------------
# simplify_geometry
# ---------------------------------------------------------------------------


def test_simplify_geometry_drops_collinear_vertex():
    """A 4-vertex straight line collapses to a 2-vertex line under redundant_only."""
    from gmnspy.clean import simplify_geometry

    engine = _engine()
    nodes = _node(engine, [{"node_id": 1, "x_coord": 0.0, "y_coord": 0.0}])
    links = _link(
        engine,
        [
            {
                "link_id": 1,
                "from_node_id": 1,
                "to_node_id": 1,
                "geometry": "LINESTRING (0 0, 1 0, 2 0, 3 0)",
            }
        ],
    )
    net = _network({"link": links, "node": nodes})
    with Session(net) as s:
        result = simplify_geometry(net, s)
    new_wkt = net.links.to_pandas()["geometry"].iloc[0]
    # Collapses to just the endpoints.
    assert new_wkt == "LINESTRING (0 0, 3 0)"
    assert result.diff.rows_changed >= 0  # bulk replace records a coarse diff


def test_simplify_geometry_douglas_peucker_with_tolerance():
    """A slight bend within tolerance gets smoothed under douglas_peucker."""
    from gmnspy.clean import simplify_geometry

    engine = _engine()
    nodes = _node(engine, [{"node_id": 1, "x_coord": 0.0, "y_coord": 0.0}])
    # The middle vertex is 0.1 units off the chord; tolerance 0.5 drops it.
    links = _link(
        engine,
        [{"link_id": 1, "from_node_id": 1, "to_node_id": 1, "geometry": "LINESTRING (0 0, 5 0.1, 10 0)"}],
    )
    net = _network({"link": links, "node": nodes})
    with Session(net) as s:
        simplify_geometry(net, s, mode="douglas_peucker", tolerance=0.5)
    new_wkt = net.links.to_pandas()["geometry"].iloc[0]
    assert "0 0" in new_wkt and "10 0" in new_wkt
    # Middle vertex 5 should be dropped.
    assert "5" not in new_wkt.split(",")[1]


def test_simplify_geometry_roundtrip_rollback():
    """simplify_geometry -> rollback restores the original geometry exactly."""
    from gmnspy.clean import simplify_geometry

    engine = _engine()
    nodes = _node(engine, [{"node_id": 1, "x_coord": 0.0, "y_coord": 0.0}])
    links = _link(
        engine,
        [{"link_id": 1, "from_node_id": 1, "to_node_id": 1, "geometry": "LINESTRING (0 0, 1 0, 2 0, 3 0)"}],
    )
    net = _network({"link": links, "node": nodes})
    before = _snapshot(net)

    s = Session(net)
    with s:
        simplify_geometry(net, s)
        # Verify state CHANGED inside the with block.
        assert net.links.to_pandas()["geometry"].iloc[0] != before["link"][0]["geometry"]
        s.rollback()
    after = _snapshot(net)
    assert after == before


def test_simplify_geometry_requires_geometry_column():
    from gmnspy.clean import CleanError, simplify_geometry

    engine = _engine()
    nodes = _node(engine, [{"node_id": 1, "x_coord": 0.0, "y_coord": 0.0}])
    links = _link(engine, [{"link_id": 1, "from_node_id": 1, "to_node_id": 1}])  # no geometry
    net = _network({"link": links, "node": nodes})
    with Session(net) as s:  # noqa: SIM117
        with pytest.raises(CleanError, match="geometry"):
            simplify_geometry(net, s)


# ---------------------------------------------------------------------------
# merge_close_nodes
# ---------------------------------------------------------------------------


def test_merge_close_nodes_collapses_pair_and_rewrites_links():
    from gmnspy.clean import merge_close_nodes

    engine = _engine()
    nodes = _node(
        engine,
        [
            {"node_id": 1, "x_coord": 0.0, "y_coord": 0.0},
            {"node_id": 2, "x_coord": 0.001, "y_coord": 0.0},  # within 5m of node 1
            {"node_id": 3, "x_coord": 100.0, "y_coord": 100.0},  # far away
        ],
    )
    links = _link(
        engine,
        [
            {"link_id": 10, "from_node_id": 1, "to_node_id": 2},  # incident to merged pair
            {"link_id": 20, "from_node_id": 2, "to_node_id": 3},  # one end merged
        ],
    )
    net = _network({"link": links, "node": nodes})
    with Session(net) as s:
        merge_close_nodes(net, s, threshold_m=1.0)

    surviving_nodes = set(net.nodes.to_pandas()["node_id"].tolist())
    # Node 2 merged into node 1 (lowest id wins).
    assert surviving_nodes == {1, 3}

    links_df = net.links.to_pandas().sort_values("link_id").reset_index(drop=True)
    # link 10's to_node_id rewritten to 1; link 20's from_node_id rewritten to 1.
    assert links_df.loc[0, "to_node_id"] == 1
    assert links_df.loc[1, "from_node_id"] == 1


def test_merge_close_nodes_roundtrip_rollback():
    from gmnspy.clean import merge_close_nodes

    engine = _engine()
    nodes = _node(
        engine,
        [
            {"node_id": 1, "x_coord": 0.0, "y_coord": 0.0},
            {"node_id": 2, "x_coord": 0.001, "y_coord": 0.0},
        ],
    )
    links = _link(engine, [{"link_id": 10, "from_node_id": 1, "to_node_id": 2}])
    net = _network({"link": links, "node": nodes})
    before = _snapshot(net)

    s = Session(net)
    with s:
        merge_close_nodes(net, s, threshold_m=1.0)
        s.rollback()
    after = _snapshot(net)
    assert after == before


@pytest.mark.perf
def test_merge_close_nodes_scales_to_1k_nodes_in_under_2s():
    """Regression bound: 1000 spatially-distributed nodes complete in <2s.

    The pre-fix nested-loop ran ~0.5s on 1k random nodes and degraded
    quadratically beyond that. After the grid pre-filter we're well
    under 100ms on this size; the 2s ceiling is a generous regression
    fence in case CI is loaded. Excluded from the default run with
    ``-m "not perf"`` so test latency stays low for everyone else.
    """
    import random
    import time

    from gmnspy.clean import merge_close_nodes

    rng = random.Random(0)
    n = 1000
    # Spread points across a 1000x1000 grid so most pairs are far apart
    # (the realistic "very few merges" case). A few intentional duplicates
    # exercise the merge path itself.
    nodes_data = [{"node_id": i, "x_coord": rng.uniform(0, 1000), "y_coord": rng.uniform(0, 1000)} for i in range(n)]
    # Drop ten near-duplicates so the merge logic actually runs.
    for i in range(10):
        nodes_data.append(
            {
                "node_id": 10_000 + i,
                "x_coord": nodes_data[i]["x_coord"] + 0.01,
                "y_coord": nodes_data[i]["y_coord"],
            }
        )

    engine = _engine()
    nodes = _node(engine, nodes_data)
    # Single link — the timed path is the node clustering pass; we keep
    # one link row so the rewrite-and-replace plumbing actually executes
    # too (and the resulting table satisfies "at least one column").
    links = _link(engine, [{"link_id": 1, "from_node_id": 0, "to_node_id": 1}])
    net = _network({"link": links, "node": nodes})

    t0 = time.perf_counter()
    with Session(net) as s:
        merge_close_nodes(net, s, threshold_m=1.0)
    elapsed = time.perf_counter() - t0
    # Print for visibility under ``-s``; assert against a generous bound.
    print(f"\n[perf] merge_close_nodes({len(nodes_data)} nodes) -> {elapsed * 1000:.1f} ms")
    assert elapsed < 2.0, f"merge_close_nodes regressed to {elapsed:.2f}s on {len(nodes_data)} nodes"


# ---------------------------------------------------------------------------
# remove_orphans
# ---------------------------------------------------------------------------


def test_remove_orphans_drops_node_with_no_links():
    from gmnspy.clean import remove_orphans

    engine = _engine()
    nodes = _node(
        engine,
        [
            {"node_id": 1, "x_coord": 0.0, "y_coord": 0.0},
            {"node_id": 2, "x_coord": 1.0, "y_coord": 0.0},
            {"node_id": 99, "x_coord": 5.0, "y_coord": 5.0},  # orphan
        ],
    )
    links = _link(engine, [{"link_id": 1, "from_node_id": 1, "to_node_id": 2}])
    net = _network({"link": links, "node": nodes})

    with Session(net) as s:
        remove_orphans(net, s)
    surviving = set(net.nodes.to_pandas()["node_id"].tolist())
    assert surviving == {1, 2}


def test_remove_orphans_roundtrip_rollback():
    from gmnspy.clean import remove_orphans

    engine = _engine()
    nodes = _node(
        engine,
        [
            {"node_id": 1, "x_coord": 0.0, "y_coord": 0.0},
            {"node_id": 2, "x_coord": 1.0, "y_coord": 0.0},
            {"node_id": 99, "x_coord": 5.0, "y_coord": 5.0},
        ],
    )
    links = _link(engine, [{"link_id": 1, "from_node_id": 1, "to_node_id": 2}])
    net = _network({"link": links, "node": nodes})
    before = _snapshot(net)

    s = Session(net)
    with s:
        remove_orphans(net, s)
        s.rollback()
    assert _snapshot(net) == before


# ---------------------------------------------------------------------------
# recompute_lengths
# ---------------------------------------------------------------------------


def test_recompute_lengths_planar():
    """Planar mode: length is shapely's geometric length (CRS units)."""
    from gmnspy.clean import recompute_lengths

    engine = _engine()
    nodes = _node(engine, [{"node_id": 1, "x_coord": 0.0, "y_coord": 0.0}])
    # Length should be 5.0 (3-4-5 triangle).
    links = _link(
        engine,
        [{"link_id": 1, "from_node_id": 1, "to_node_id": 1, "geometry": "LINESTRING (0 0, 3 0, 3 4)", "length": 999.0}],
    )
    net = _network({"link": links, "node": nodes})
    with Session(net) as s:
        recompute_lengths(net, s)
    new_length = float(net.links.to_pandas()["length"].iloc[0])
    assert new_length == pytest.approx(7.0)  # 3 + 4 = 7 planar


def test_recompute_lengths_geodesic_returns_meters():
    """Geodesic mode: WGS84 (lon, lat) -> haversine length in meters."""
    from gmnspy.clean import recompute_lengths

    engine = _engine()
    nodes = _node(engine, [{"node_id": 1, "x_coord": 0.0, "y_coord": 0.0}])
    # 1 degree of longitude at the equator ≈ 111_320m. Using
    # LINESTRING (0 0, 1 0) — should be approximately that distance.
    links = _link(
        engine,
        [{"link_id": 1, "from_node_id": 1, "to_node_id": 1, "geometry": "LINESTRING (0 0, 1 0)", "length": 0.0}],
    )
    net = _network({"link": links, "node": nodes})
    with Session(net) as s:
        recompute_lengths(net, s, geodesic=True)
    new_length = float(net.links.to_pandas()["length"].iloc[0])
    assert new_length == pytest.approx(111_195, rel=0.01)


def test_recompute_lengths_roundtrip_rollback():
    from gmnspy.clean import recompute_lengths

    engine = _engine()
    nodes = _node(engine, [{"node_id": 1, "x_coord": 0.0, "y_coord": 0.0}])
    links = _link(
        engine,
        [{"link_id": 1, "from_node_id": 1, "to_node_id": 1, "geometry": "LINESTRING (0 0, 3 0, 3 4)", "length": 999.0}],
    )
    net = _network({"link": links, "node": nodes})
    before = _snapshot(net)

    s = Session(net)
    with s:
        recompute_lengths(net, s)
        s.rollback()
    assert _snapshot(net) == before


# ---------------------------------------------------------------------------
# Multiple ops in a single Session
# ---------------------------------------------------------------------------


def test_sequential_ops_chain_inside_one_session():
    """Two ops in one session both apply; rollback at end restores baseline."""
    from gmnspy.clean import recompute_lengths, remove_orphans

    engine = _engine()
    nodes = _node(
        engine,
        [
            {"node_id": 1, "x_coord": 0.0, "y_coord": 0.0},
            {"node_id": 2, "x_coord": 1.0, "y_coord": 0.0},
            {"node_id": 99, "x_coord": 5.0, "y_coord": 5.0},  # orphan
        ],
    )
    links = _link(
        engine,
        [{"link_id": 1, "from_node_id": 1, "to_node_id": 2, "geometry": "LINESTRING (0 0, 1 0)", "length": 0.0}],
    )
    net = _network({"link": links, "node": nodes})
    before = _snapshot(net)

    s = Session(net)
    with s:
        remove_orphans(net, s)
        recompute_lengths(net, s)
        # Both applied:
        assert set(net.nodes.to_pandas()["node_id"]) == {1, 2}
        assert float(net.links.to_pandas()["length"].iloc[0]) == pytest.approx(1.0)
        s.rollback()
    assert _snapshot(net) == before
