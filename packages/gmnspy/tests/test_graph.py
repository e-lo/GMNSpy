"""Tests for gmnspy.graph (connectivity, isochrone, shortest path)."""

import pandas as pd
import pytest
from gmnspy.graph import GMNSGraph
from gmnspy.graph.source import DuckDBSource, ParquetSource


def clean_network():
    """A small, deterministic directed network with known answers.

    Topology (directed, costs in `weight`):
        1 ->2 (1)   2 ->3 (1)   1 ->3 (3)   3 ->4 (1)   4 ->5 (1)
        7 ->8 (1)                node 6 isolated
    Link 2->3 carries lts=3 (a barrier when filtering lts>2).
    """
    nodes = pd.DataFrame(
        {
            "node_id": [1, 2, 3, 4, 5, 6, 7, 8],
            "x_coord": [0.0, 1.0, 2.0, 3.0, 4.0, 10.0, 0.0, 1.0],
            "y_coord": [0.0, 0.0, 0.0, 0.0, 0.0, 10.0, 5.0, 5.0],
        }
    )
    links = pd.DataFrame(
        {
            "link_id": ["L12", "L23", "L13", "L34", "L45", "L78"],
            "from_node_id": [1, 2, 1, 3, 4, 7],
            "to_node_id": [2, 3, 3, 4, 5, 8],
            "weight": [1.0, 1.0, 3.0, 1.0, 1.0, 1.0],
            "lts": [1, 3, 1, 1, 1, 1],
        }
    )
    return {"node": nodes, "link": links}


@pytest.fixture
def graph():
    return GMNSGraph.build(clean_network(), cost="weight")


# -- build ------------------------------------------------------------------


def test_build_counts(graph):
    assert graph.meta["n_nodes"] == 8
    assert graph.meta["n_edges"] == 6  # all directed, no reverse edges


def test_nbytes_reports_positive_memory(graph):
    assert graph.nbytes > 0


def test_undirected_adds_reverse_edges():
    g = GMNSGraph.build(clean_network(), cost="weight", directed=False)
    assert g.meta["n_edges"] == 12


# -- connectivity -----------------------------------------------------------


def test_connectivity_components(graph):
    result = graph.connectivity(connection="weak")
    assert result.n_components == 3  # {1,2,3,4,5}, {6}, {7,8}
    sizes = set(result.component_sizes().tolist())
    assert sizes == {5, 2, 1}
    singletons = result.small_components(max_size=1)["node_id"].tolist()
    assert singletons == [6]


def test_connectivity_flags_dangling_node_from_link_only_reference():
    # A link references node 78, which is absent from the node table.
    nodes = pd.DataFrame({"node_id": [1, 2], "x_coord": [0.0, 1.0], "y_coord": [0.0, 0.0]})
    links = pd.DataFrame({"link_id": ["A"], "from_node_id": [1], "to_node_id": [78], "free_speed": [25.0]})
    g = GMNSGraph.build({"node": nodes, "link": links}, cost="free_speed")
    result = g.connectivity(connection="weak")
    assert 78 in g.meta["nodes_only_in_links"]
    assert 78 in result.nodes_only_in_links


# -- shortest path ----------------------------------------------------------


def test_shortest_path(graph):
    path = graph.shortest_path(1, 4)
    assert path.cost == 3.0
    assert path.nodes == [1, 2, 3, 4]
    assert path.links == ["L12", "L23", "L34"]


def test_shortest_path_unreachable(graph):
    path = graph.shortest_path(1, 7)  # different component
    assert not path.reachable
    assert path.links == []


def test_barrier_reroutes_path():
    g = GMNSGraph.build(clean_network(), cost="weight", barrier="lts > 2")
    assert g.meta["n_edges"] == 5  # L23 removed
    path = g.shortest_path(1, 4)
    assert path.cost == 4.0  # forced onto 1->3->4
    assert path.nodes == [1, 3, 4]
    assert path.links == ["L13", "L34"]


# -- isochrone --------------------------------------------------------------


def test_isochrone_cutoff(graph):
    iso = graph.isochrone(source_node=1, cutoff=2.0)
    assert set(iso.reachable_node_ids.tolist()) == {1, 2, 3}
    costs = dict(zip(iso.nodes["node_id"], iso.nodes["cost"], strict=False))
    assert costs[3] == 2.0


# -- snap -------------------------------------------------------------------


def test_snap(graph):
    assert graph.snap(2.9, 0.1) == 4


# -- engine parity ----------------------------------------------------------


def test_parquet_engine_parity(tmp_path):
    net = clean_network()
    net["node"].to_parquet(tmp_path / "node.parquet")
    net["link"].to_parquet(tmp_path / "link.parquet")
    g = GMNSGraph.build(ParquetSource(str(tmp_path)), cost="weight")
    assert g.meta["n_nodes"] == 8
    assert g.shortest_path(1, 4).links == ["L12", "L23", "L34"]


def test_polars_engine_parity(tmp_path):
    pytest.importorskip("polars")
    from gmnspy.graph.source import PolarsSource

    net = clean_network()
    net["node"].to_parquet(tmp_path / "node.parquet")
    net["link"].to_parquet(tmp_path / "link.parquet")
    g = GMNSGraph.build(PolarsSource(str(tmp_path)), cost="weight")
    assert g.meta["n_nodes"] == 8
    assert g.shortest_path(1, 4).links == ["L12", "L23", "L34"]


def test_duckdb_engine_parity():
    duckdb = pytest.importorskip("duckdb")
    net = clean_network()
    # pandas 3.0 'str' dtype isn't recognized by duckdb.register; use object strings.
    net["link"]["link_id"] = net["link"]["link_id"].astype(object)
    con = duckdb.connect()
    con.register("node_v", net["node"])
    con.register("link_v", net["link"])
    con.execute("CREATE TABLE node AS SELECT * FROM node_v")
    con.execute("CREATE TABLE link AS SELECT * FROM link_v")
    g = GMNSGraph.build(DuckDBSource(con), cost="weight")
    assert g.meta["n_nodes"] == 8
    assert g.shortest_path(1, 4).cost == 3.0


# -- guards -----------------------------------------------------------------


def test_edge_mode_not_implemented():
    with pytest.raises(NotImplementedError):
        GMNSGraph.build(clean_network(), cost="weight", mode="edge")


def test_negative_cost_rejected():
    net = clean_network()
    net["link"].loc[0, "weight"] = -1.0
    with pytest.raises(ValueError, match=r"[Nn]egative"):
        GMNSGraph.build(net, cost="weight")


# -- viz --------------------------------------------------------------------


def test_to_geodataframe(graph):
    gpd = pytest.importorskip("geopandas")
    gdf = graph.to_geodataframe(highlight=graph.shortest_path(1, 4))
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert gdf["highlight"].sum() == 3
    assert gdf.geometry.notna().all()
