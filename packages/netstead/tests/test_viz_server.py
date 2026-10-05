"""Tests for the netstead.viz web app backend."""

import json as _json
from importlib import resources

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from netstead.viz.buffers import unpack_network
from netstead.viz.server import build_app


@pytest.fixture(scope="module")
def client():
    base = resources.files("netstead.fixtures.rdu_i40").joinpath("parquet")
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
    from netstead.viz.server import build_app

    app = build_app(
        pd.DataFrame({"link_id": [], "from_node_id": [], "to_node_id": [], "geometry": []}),
        pd.DataFrame({"node_id": [], "x_coord": [], "y_coord": []}),
        basemap="esri",
    )
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

    base = resources.files("netstead.fixtures.rdu_i40").joinpath("parquet")
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


def test_tables_lists_link_and_node(client):
    j = client.get("/api/tables").json()
    tables = {t["name"]: t for t in j["tables"]}
    assert "link" in tables and "node" in tables
    assert tables["link"]["rows"] > 50
    assert "facility_type" in tables["link"]["columns"]


def test_table_schema_classifies_and_names_pk(client):
    j = client.get("/api/table/link/schema").json()
    assert j["primary_key"] == "link_id" and j["rows"] > 50
    kinds = {c["name"]: c["kind"] for c in j["columns"]}
    assert kinds["lanes"] == "num" and kinds["facility_type"] == "str"
    assert kinds.get("geometry") == "geom"


def test_table_rows_paged_excludes_geometry(client):
    j = client.get("/api/table/link/rows", params={"offset": 0, "limit": 5}).json()
    assert len(j["rows"]) == 5
    assert j["total"] > 5 and j["offset"] == 0
    assert "geometry" not in j["columns"]  # geometry excluded from grid payload


def test_table_rows_sorted(client):
    j = client.get("/api/table/link/rows", params={"limit": 50, "sort": "lanes", "dir": "asc"}).json()
    li = j["columns"].index("lanes")
    vals = [r[li] for r in j["rows"] if r[li] is not None]
    assert vals == sorted(vals)


def test_table_rows_filtered(client):
    spec = _json.dumps([{"col": "facility_type", "op": "eq", "val": "motorway"}])
    j = client.get("/api/table/link/rows", params={"limit": 500, "filter": spec}).json()
    fi = j["columns"].index("facility_type")
    assert j["total"] > 0
    assert all(r[fi] == "motorway" for r in j["rows"])


def test_table_rows_crossfilter_by_ids(client):
    base = resources.files("netstead.fixtures.rdu_i40").joinpath("parquet")
    ids = [int(i) for i in pd.read_parquet(base.joinpath("link.parquet"))["link_id"].iloc[:3]]
    j = client.get("/api/table/link/rows", params={"ids": ",".join(map(str, ids)), "limit": 500}).json()
    assert j["total"] == 3


def test_table_rows_unknown_table_404(client):
    assert client.get("/api/table/nope/rows").status_code == 404


def test_table_rows_bad_filter_column_400(client):
    spec = _json.dumps([{"col": "nonsuch", "op": "eq", "val": 1}])
    assert client.get("/api/table/link/rows", params={"filter": spec}).status_code == 400


def test_fragment_from_picked_link_ids(client):
    base = resources.files("netstead.fixtures.rdu_i40").joinpath("parquet")
    ids = [int(i) for i in pd.read_parquet(base.joinpath("link.parquet"))["link_id"].iloc[:3]]
    r = client.post("/api/fragment", json={"link_ids": ids})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "resolved"
    assert j["fragment"]["links"]["link_id"] == ids
    assert j["count"] == 3


def test_fragment_query_form(client):
    base = resources.files("netstead.fixtures.rdu_i40").joinpath("parquet")
    ids = [int(i) for i in pd.read_parquet(base.joinpath("link.parquet"))["link_id"].iloc[:2]]
    j = client.post("/api/fragment", json={"link_ids": ids, "form": "query"}).json()
    assert j["fragment"]["links"]["link_id"] == ids  # query form of explicit ids


def test_fragment_empty_is_rejected(client):
    r = client.post("/api/fragment", json={"link_ids": []})
    assert r.status_code == 400


def test_fragment_unknown_ids_not_found(client):
    j = client.post("/api/fragment", json={"link_ids": [999999999]}).json()
    assert j["status"] == "not_found"
    assert j["fragment"] is None


def test_select_returns_link_ids_and_anchors(client):
    r = client.get("/api/select", params={"utterance": "I-40 EB between South Miami Boulevard and Airport Boulevard"})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "resolved"
    assert j["link_ids"][0] == 5021
    roles = {a["role"]: a for a in j["anchors"]}
    assert set(roles) == {"from", "to"}
    assert roles["from"]["kind"] == "gore" and -79 < roles["from"]["lon"] < -78
