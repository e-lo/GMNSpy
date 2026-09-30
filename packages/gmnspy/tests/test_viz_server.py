"""Tests for the gmnspy.viz web app backend."""
from importlib import resources

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from gmnspy.viz.server import build_app
from gmnspy.viz.buffers import unpack_network


@pytest.fixture(scope="module")
def client():
    base = resources.files("gmnspy.fixtures.rdu_i40").joinpath("parquet")
    links = pd.read_parquet(base.joinpath("link.parquet"))
    nodes = pd.read_parquet(base.joinpath("node.parquet"))
    return TestClient(build_app(links, nodes, provider="stub"))


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_network_bin_parses(client):
    r = client.get("/api/network.bin")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    net = unpack_network(r.content)
    assert net["links"]["count"] > 50 and net["nodes"]["count"] > 50


def test_network_attrs(client):
    r = client.get("/api/network.attrs.json")
    assert r.status_code == 200
    j = r.json()
    assert len(j["link_id"]) == len(j["facility_type"])


def test_select_returns_link_ids_and_anchors(client):
    r = client.get("/api/select",
                   params={"utterance": "I-40 EB between South Miami Boulevard and Airport Boulevard"})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "resolved"
    assert j["link_ids"][0] == 5021
    roles = {a["role"]: a for a in j["anchors"]}
    assert set(roles) == {"from", "to"}
    assert roles["from"]["kind"] == "gore" and -79 < roles["from"]["lon"] < -78
