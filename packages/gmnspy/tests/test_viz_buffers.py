"""Tests for gmnspy.viz.buffers — Parquet frames -> packed binary + attrs."""

from importlib import resources

import pandas as pd
import pytest
from gmnspy.viz.buffers import network_attrs, pack_network, unpack_network


@pytest.fixture(scope="module")
def rdu():
    base = resources.files("gmnspy.fixtures.rdu_i40").joinpath("parquet")
    return (pd.read_parquet(base.joinpath("link.parquet")), pd.read_parquet(base.joinpath("node.parquet")))


def test_pack_unpack_roundtrip_counts(rdu):
    links, nodes = rdu
    blob = pack_network(links, nodes)
    assert isinstance(blob, (bytes, bytearray))
    net = unpack_network(blob)
    assert net["links"]["count"] == len(links)
    assert net["nodes"]["count"] == len(nodes)
    # startIndices has count+1 entries, monotonic non-decreasing
    si = net["links"]["startIndices"]
    assert len(si) == len(links) + 1
    assert all(si[i] <= si[i + 1] for i in range(len(si) - 1))
    # positions are flat lon,lat pairs; last startIndex = number of vertices
    assert len(net["links"]["positions"]) == si[-1] * 2
    assert net["links"]["ids"][0] == links["link_id"].iloc[0]


def test_positions_are_wgs84ish(rdu):
    links, nodes = rdu
    net = unpack_network(pack_network(links, nodes))
    xs = net["links"]["positions"][0::2]
    ys = net["links"]["positions"][1::2]
    assert all(-79 < x < -78 for x in xs[:50])
    assert all(35 < y < 36 for y in ys[:50])


def test_straight_fallback_when_no_geometry(rdu):
    links, nodes = rdu
    links = links.copy()
    links.loc[links.index[0], "geometry"] = None  # force fallback on first link
    net = unpack_network(pack_network(links, nodes))
    # first link now has exactly 2 vertices (straight from->to)
    si = net["links"]["startIndices"]
    assert si[1] - si[0] == 2


def test_lanes_present_and_freeway_thicker(rdu):
    links, nodes = rdu
    net = unpack_network(pack_network(links, nodes))
    lanes = net["links"]["lanes"]
    assert len(lanes) == len(links) and all(x >= 1 for x in lanes)
    # motorway links should default to more lanes than residential when untagged
    ids = net["links"]["ids"]
    ft = dict(zip(links["link_id"], links["facility_type"], strict=False))
    mot = [lanes[i] for i, lid in enumerate(ids) if ft.get(lid) == "motorway"]
    res = [lanes[i] for i, lid in enumerate(ids) if ft.get(lid) == "residential"]
    if mot and res:
        assert max(mot) > min(res)


def test_network_attrs_index_aligned(rdu):
    links, _nodes = rdu
    attrs = network_attrs(links)
    assert attrs["link_id"] == list(links["link_id"])
    assert len(attrs["name"]) == len(links)
    assert len(attrs["facility_type"]) == len(links)
