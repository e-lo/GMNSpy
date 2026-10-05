"""Tests for the netstead.select web app backend (FastAPI endpoints)."""

from importlib import resources

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from netstead.select.webapp import build_app


@pytest.fixture(scope="module")
def client():
    base = resources.files("netstead.fixtures.rdu_i40").joinpath("parquet")
    links = pd.read_parquet(base.joinpath("link.parquet"))
    nodes = pd.read_parquet(base.joinpath("node.parquet"))
    return TestClient(build_app(links, nodes, provider="stub"))


def test_index_page_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_network_geojson(client):
    r = client.get("/api/network.geojson")
    assert r.status_code == 200
    assert r.json()["type"] == "FeatureCollection"
    assert len(r.json()["features"]) > 50


def test_select_resolved(client):
    r = client.get("/api/select", params={"utterance": "I-40 EB between South Miami Boulevard and Airport Boulevard"})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "resolved"
    assert j["fragment"]["links"]["link_id"][0] == 5021
    assert len(j["selected"]["features"]) >= 1
    roles = {a["role"]: a for a in j["anchors"]}
    assert set(roles) == {"from", "to"}
    assert roles["from"]["kind"] == "gore" and roles["to"]["kind"] == "merge"
    assert -79 < roles["from"]["lon"] < -78


def test_select_not_found(client):
    r = client.get("/api/select", params={"utterance": "I-40 EB between Nowhere St and Airport Boulevard"})
    assert r.status_code == 200
    assert r.json()["status"] == "not_found"
