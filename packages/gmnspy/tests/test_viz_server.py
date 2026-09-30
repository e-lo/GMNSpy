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


def test_config_default_is_keyless_positron(client):
    style = client.get("/api/config").json()["style"]
    # default positron is a no-key vector style URL; no api_key anywhere
    assert isinstance(style, str) and "openfreemap" in style and "api_key" not in style


def test_config_esri_option_is_keyless():
    from gmnspy.viz.server import build_app
    app = build_app(pd.DataFrame({"link_id": [], "from_node_id": [], "to_node_id": [], "geometry": []}),
                    pd.DataFrame({"node_id": [], "x_coord": [], "y_coord": []}), basemap="esri")
    style = TestClient(app).get("/api/config").json()["style"]
    tiles = style["sources"]["basemap"]["tiles"][0]
    assert "arcgisonline.com" in tiles and "api_key" not in tiles


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


def test_link_detail_returns_full_row(client):
    import pandas as pd
    base = resources.files("gmnspy.fixtures.rdu_i40").joinpath("parquet")
    lid = int(pd.read_parquet(base.joinpath("link.parquet"))["link_id"].iloc[0])
    r = client.get(f"/api/link/{lid}")
    assert r.status_code == 200
    j = r.json()
    assert j["link_id"] == lid
    attrs = j["attributes"]
    assert attrs["link_id"] == lid
    assert "facility_type" in attrs and "from_node_id" in attrs


def test_link_detail_404_for_unknown(client):
    assert client.get("/api/link/999999999").status_code == 404


def test_properties_classifies_columns(client):
    props = {p["name"]: p["kind"] for p in client.get("/api/properties").json()["properties"]}
    assert props.get("lanes") == "continuous"
    assert props.get("facility_type") == "categorical"
    assert "geometry" not in props and "link_id" not in props  # skipped


def test_property_values_continuous_and_categorical(client):
    lanes = client.get("/api/property/lanes").json()
    assert lanes["kind"] == "continuous" and lanes["min"] <= lanes["max"]
    ft = client.get("/api/property/facility_type").json()
    assert ft["kind"] == "categorical" and "motorway" in ft["categories"]
    assert len(ft["values"]) == len(lanes["values"])
    assert client.get("/api/property/nope").status_code == 404


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
