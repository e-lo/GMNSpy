"""Tests for /api/n/{net_id}/{component}/... routes."""

import json

import pytest
from fastapi.testclient import TestClient
from gmnspy.select.parse import StubParser
from gmnspy.viz.buffers import unpack_network
from gmnspy.workbench import Session, build_app

BASE = "/api/n/rdu-i40/roadway"


@pytest.fixture(scope="module")
def client(tmp_path_factory, rdu_source):
    tmp = tmp_path_factory.mktemp("wb")
    env = {"GMNSPY_CONFIG_DIR": str(tmp / "user"), "GMNSPY_IO__ALLOWED_ROOTS": json.dumps([rdu_source])}
    s = Session(project_dir=tmp, environ=env, parser=StubParser())
    s.dispatch({"type": "open_network", "source": rdu_source})
    return TestClient(build_app(s))


def test_network_bin_unpacks(client):
    r = client.get(f"{BASE}/network.bin")
    assert r.headers["content-type"] == "application/octet-stream"
    net = unpack_network(r.content)
    assert net["links"]["count"] == 178 and net["nodes"]["count"] == 143


def test_attrs_index_aligned(client):
    j = client.get(f"{BASE}/network.attrs.json").json()
    assert len(j["link_id"]) == len(j["facility_type"]) == 178


def test_properties_and_property(client):
    props = {p["name"]: p["kind"] for p in client.get(f"{BASE}/properties").json()["properties"]}
    assert props["lanes"] == "continuous"
    p = client.get(f"{BASE}/property/lanes").json()
    assert p["kind"] == "continuous" and len(p["values"]) == 178
    assert client.get(f"{BASE}/property/nope").status_code == 404


def test_feature_lookup(client):
    lid = client.get(f"{BASE}/network.attrs.json").json()["link_id"][0]
    j = client.get(f"{BASE}/feature/link/{lid}").json()
    assert j["pk"] == "link_id" and j["attributes"]["link_id"] == lid and "geometry" not in j["attributes"]
    assert client.get(f"{BASE}/feature/link/999999999").status_code == 404


def test_tables_schema_rows(client):
    names = [t["name"] for t in client.get(f"{BASE}/tables").json()["tables"]]
    assert names[:2] == ["link", "node"]
    assert client.get(f"{BASE}/table/link/schema").json()["primary_key"] == "link_id"
    rows = client.get(f"{BASE}/table/link/rows", params={"limit": 5, "sort": "link_id", "dir": "desc"}).json()
    assert rows["total"] == 178 and len(rows["rows"]) == 5


def test_rows_filter_and_ids(client):
    spec = json.dumps([{"col": "facility_type", "op": "contains", "val": "motorway"}])
    j = client.get(f"{BASE}/table/link/rows", params={"filter": spec}).json()
    assert 0 < j["total"] < 178
    lid = client.get(f"{BASE}/network.attrs.json").json()["link_id"][0]
    assert client.get(f"{BASE}/table/link/rows", params={"ids": str(lid)}).json()["total"] == 1


def test_bad_filter_is_400(client):
    assert client.get(f"{BASE}/table/link/rows", params={"filter": "{"}).status_code == 400
    bad = json.dumps([{"col": "nope", "op": "eq", "val": 1}])
    assert client.get(f"{BASE}/table/link/rows", params={"filter": bad}).status_code == 400


def test_unknown_network_table_component(client):
    assert client.get("/api/n/nope/roadway/properties").status_code == 404
    assert client.get(f"{BASE}/table/nope/schema").status_code == 404
    assert client.get("/api/n/rdu-i40/bogus/properties").status_code == 404
    assert client.get("/api/n/rdu-i40/transit/properties").status_code == 501
