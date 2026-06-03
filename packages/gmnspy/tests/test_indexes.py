"""Tests for ``gmnspy.indexes`` — spatial (STRtree) builder + the build_indexes helper.

Cross-engine where the engine actually changes behavior; otherwise pandas
is fine because the indexes themselves are engine-agnostic (materialize-to-arrow
once, then operate on shapely / scipy objects). The graph slot of
:func:`build_indexes` returns a :class:`gmnspy.graph.GMNSGraph` whose own tests
live in ``test_graph.py`` + ``test_graph_network_api.py``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

shapely = pytest.importorskip("shapely")
pytest.importorskip("scipy")  # build_indexes' graph slot returns a GMNSGraph
pyarrow = pytest.importorskip("pyarrow")

from datagrove.dataset import Table  # noqa: E402
from datagrove.engines.pandas_engine import PandasEngine  # noqa: E402
from gmnspy.fixtures import leavenworth  # noqa: E402
from gmnspy.indexes import (  # noqa: E402
    SpatialIndex,
    build_indexes,
    cache_path,
)
from gmnspy.indexes.cache import load_cached, save_cached  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _read_csv_table(name: str, engine: PandasEngine) -> Table:
    """Read a Leavenworth CSV into a Table backed by ``engine``."""
    import pandas as pd

    df = pd.read_csv(leavenworth.csv_dir() / f"{name}.csv")
    expr = engine.from_records(df.to_dict(orient="records"))
    return Table(name=name, expr=expr, engine=engine)


@pytest.fixture
def engine() -> PandasEngine:
    return PandasEngine()


@pytest.fixture
def links_with_geom(engine: PandasEngine) -> Table:
    """``link`` table joined to ``geometry`` so it carries a WKT ``geometry`` column."""
    import pandas as pd

    links_df = pd.read_csv(leavenworth.csv_dir() / "link.csv")
    geom_df = pd.read_csv(leavenworth.csv_dir() / "geometry.csv")
    merged = links_df.merge(geom_df, on="geometry_id", how="left")
    expr = engine.from_records(merged.to_dict(orient="records"))
    return Table(name="link", expr=expr, engine=engine)


@pytest.fixture
def nodes_table(engine: PandasEngine) -> Table:
    return _read_csv_table("node", engine)


# ---------------------------------------------------------------------------
# SpatialIndex
# ---------------------------------------------------------------------------


def test_spatial_index_builds_from_link_table(links_with_geom: Table) -> None:
    idx = SpatialIndex.build(links_with_geom)
    assert isinstance(idx, SpatialIndex)
    assert len(idx) > 0


def test_spatial_index_bbox_query_returns_link_ids(links_with_geom: Table) -> None:
    """A bbox that covers all of Leavenworth must return all link_ids."""
    idx = SpatialIndex.build(links_with_geom)
    # generous bbox over the Leavenworth area (lon, lat WGS84)
    hits = idx.query_bbox(-120.70, 47.58, -120.65, 47.62)
    assert len(hits) == len(idx)
    # link_ids are ints in the fixture
    assert all(isinstance(h, int) for h in hits)


def test_spatial_index_bbox_far_away_returns_empty(links_with_geom: Table) -> None:
    idx = SpatialIndex.build(links_with_geom)
    # an Atlantic Ocean bbox — no overlap with Leavenworth links
    hits = idx.query_bbox(-30.0, 0.0, -20.0, 10.0)
    assert hits == []


def test_spatial_index_point_query(links_with_geom: Table) -> None:
    """A point query at a known node coordinate must hit at least one link."""
    # Node 1 is at (-120.6687239, 47.5950787) per node.csv — multiple links touch it.
    idx = SpatialIndex.build(links_with_geom)
    hits = idx.query_point(-120.6687239, 47.5950787)
    assert len(hits) >= 1


def test_spatial_index_geometry_query(links_with_geom: Table) -> None:
    """Querying with a shapely polygon returns the link ids whose geoms intersect it."""
    from shapely.geometry import box

    idx = SpatialIndex.build(links_with_geom)
    poly = box(-120.70, 47.58, -120.65, 47.62)
    hits = idx.query_geometry(poly)
    assert len(hits) == len(idx)


# ---------------------------------------------------------------------------
# Graph (GMNSGraph) — direct tests live in test_graph.py + test_graph_network_api.py.
# This module covers the build_indexes helper that returns a GMNSGraph in the
# graph slot (see test_build_indexes_returns_both below).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cache round-trip
# ---------------------------------------------------------------------------


def test_cache_path_structure() -> None:
    p = cache_path("/tmp/net.duckdb", "spatial", "abcdef1234567890")
    assert p.parent.name == "_gmnspy_indexes"
    assert p.suffix == ".parquet"
    assert "spatial" in p.name
    assert "abcdef12" in p.name  # first 8 chars of hash


def test_cache_round_trip_spatial(links_with_geom: Table) -> None:
    idx = SpatialIndex.build(links_with_geom)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "spatial.parquet"
        save_cached(p, idx)
        assert p.is_file()
        loaded = load_cached(p)
        assert loaded is not None
        # Same query returns same hits
        assert sorted(loaded.query_bbox(-120.70, 47.58, -120.65, 47.62)) == sorted(
            idx.query_bbox(-120.70, 47.58, -120.65, 47.62)
        )


def test_cache_load_missing_returns_none() -> None:
    with tempfile.TemporaryDirectory() as td:
        assert load_cached(Path(td) / "nope.parquet") is None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def test_build_indexes_returns_both(links_with_geom: Table, nodes_table: Table) -> None:
    from gmnspy.graph import GMNSGraph

    spatial, graph = build_indexes(
        links=links_with_geom,
        nodes=nodes_table,
        spatial=True,
        graph=True,
    )
    assert isinstance(spatial, SpatialIndex)
    # Graph slot now returns a GMNSGraph (scipy CSR), the unified routing
    # backend for scope + semantics; the older GraphIndex (igraph) wrapper
    # still lives in gmnspy.indexes.graph for direct callers.
    assert isinstance(graph, GMNSGraph)


def test_build_indexes_can_skip(links_with_geom: Table, nodes_table: Table) -> None:
    spatial, graph = build_indexes(
        links=links_with_geom,
        nodes=nodes_table,
        spatial=True,
        graph=False,
    )
    assert isinstance(spatial, SpatialIndex)
    assert graph is None


# ---------------------------------------------------------------------------
# Cross-engine smoke (ibis path)
# ---------------------------------------------------------------------------


def test_indexes_build_under_ibis_engine() -> None:
    """Same fixture, ibis engine — indexes must agree with the pandas baseline.

    Indexes are engine-agnostic by design (they materialize to arrow
    once at build time), so this is a regression guard against the
    materialization path silently diverging.
    """
    import pandas as pd
    import pyarrow as pa
    from datagrove.engines.ibis_engine import IbisEngine

    ibis_eng = IbisEngine()
    pandas_eng = PandasEngine()

    links_df = pd.read_csv(leavenworth.csv_dir() / "link.csv")
    geom_df = pd.read_csv(leavenworth.csv_dir() / "geometry.csv")
    merged = links_df.merge(geom_df, on="geometry_id", how="left")
    nodes_df = pd.read_csv(leavenworth.csv_dir() / "node.csv")

    # Go through pyarrow.Table so both engines see the same dtypes (the
    # ibis engine's from_records uses pa.Table.from_pylist which infers
    # types per-column from the first row; pandas-CSV `nan` in a string
    # column trips that inference).
    links_arrow = pa.Table.from_pandas(merged, preserve_index=False)
    nodes_arrow = pa.Table.from_pandas(nodes_df, preserve_index=False)

    ibis_links = Table(name="link", expr=ibis_eng.from_arrow(links_arrow), engine=ibis_eng)
    ibis_nodes = Table(name="node", expr=ibis_eng.from_arrow(nodes_arrow), engine=ibis_eng)
    pandas_links = Table(name="link", expr=pandas_eng.from_arrow(links_arrow), engine=pandas_eng)
    pandas_nodes = Table(name="node", expr=pandas_eng.from_arrow(nodes_arrow), engine=pandas_eng)

    ibis_spatial = SpatialIndex.build(ibis_links)
    pandas_spatial = SpatialIndex.build(pandas_links)
    assert len(ibis_spatial) == len(pandas_spatial)
    assert sorted(ibis_spatial.query_bbox(-120.70, 47.58, -120.65, 47.62)) == sorted(
        pandas_spatial.query_bbox(-120.70, 47.58, -120.65, 47.62)
    )

    # Graph slot is a GMNSGraph (scipy); its full engine-parity is covered by
    # tests/test_osm_bench.test_build_is_engine_agnostic. Here we just confirm
    # the build_indexes plumbing produces equivalent shapes from either engine.
    _, ibis_graph = build_indexes(links=ibis_links, nodes=ibis_nodes, spatial=False, graph=True)
    _, pandas_graph = build_indexes(links=pandas_links, nodes=pandas_nodes, spatial=False, graph=True)
    assert ibis_graph.meta["n_nodes"] == pandas_graph.meta["n_nodes"]
    assert ibis_graph.shortest_path(1, 2).nodes == pandas_graph.shortest_path(1, 2).nodes
