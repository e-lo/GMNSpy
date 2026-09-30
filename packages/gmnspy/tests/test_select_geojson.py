"""Tests for gmnspy.select._geojson — link frames -> GeoJSON for the map."""
from importlib import resources

import pandas as pd
import pytest

from gmnspy.select._geojson import links_to_geojson, node_lonlat


@pytest.fixture(scope="module")
def rdu():
    base = resources.files("gmnspy.fixtures.rdu_i40").joinpath("parquet")
    return (pd.read_parquet(base.joinpath("link.parquet")),
            pd.read_parquet(base.joinpath("node.parquet")))


def test_links_to_geojson_all(rdu):
    links, nodes = rdu
    fc = links_to_geojson(links)
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == len(links)
    f = fc["features"][0]
    assert f["geometry"]["type"] == "LineString"
    assert len(f["geometry"]["coordinates"]) >= 2
    assert "link_id" in f["properties"]


def test_links_to_geojson_subset(rdu):
    links, nodes = rdu
    ids = list(links["link_id"].iloc[:3])
    fc = links_to_geojson(links, link_ids=ids)
    assert [f["properties"]["link_id"] for f in fc["features"]] == ids


def test_node_lonlat(rdu):
    links, nodes = rdu
    nid = int(nodes["node_id"].iloc[0])
    lon, lat = node_lonlat(nodes, nid)
    assert -79 < lon < -78 and 35 < lat < 36
