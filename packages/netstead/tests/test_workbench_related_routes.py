"""Tests for the related-records, POST rows and locate routes (read-only, never recorded)."""

import json

import pytest
from fastapi.testclient import TestClient
from netstead.fixtures import leavenworth
from netstead.workbench import Session, build_app

BASE = "/api/n/leavenworth/roadway"


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("wb")
    src = str(leavenworth.parquet_dir())
    env = {"NETSTEAD_CONFIG_DIR": str(tmp / "u"), "NETSTEAD_IO__ALLOWED_ROOTS": json.dumps([src])}
    s = Session(project_dir=tmp, environ=env)
    s.dispatch({"type": "open_network", "source": src})
    return s


@pytest.fixture(scope="module")
def client(session):
    return TestClient(build_app(session))


@pytest.fixture(scope="module")
def link1(session):
    return session.registry.get("leavenworth").links_df().set_index("link_id").loc[1]


def test_schema_lists_spec_keys(client):
    j = client.get(f"{BASE}/table/link/schema").json()
    assert j["primary_key"] == "link_id"
    fks = {(f["column"], f["ref_table"], f["navigable"]) for f in j["foreign_keys"]}
    assert {("from_node_id", "node", True), ("to_node_id", "node", True)} <= fks
    lane = client.get(f"{BASE}/table/lane/schema").json()
    assert lane["primary_key"] == "lane_id" and [f["column"] for f in lane["foreign_keys"]] == ["link_id"]


def test_related_summary_and_map_ids(client, link1):
    j = client.post(f"{BASE}/related", json={"sources": {"link": [1]}}).json()
    by = {t["table"]: t for t in j["tables"]}
    assert by["lane"]["count"] >= 1 and by["lane"]["via"] == ["lane.link_id → link"] and by["lane"]["hop"] == 1
    assert set(j["map"]["node"]["ids"]) == {int(link1.from_node_id), int(link1.to_node_id)}
    assert j["map"]["node"]["truncated"] is False and "link" not in j["map"]


def test_related_is_read_only(client, session):
    before = len(session.history)
    assert client.post(f"{BASE}/related", json={"sources": {"node": [1]}, "hops": 2}).status_code == 200
    assert len(session.history) == before


def test_related_rejects_unknown_tables_and_too_many_ids(client):
    assert client.post(f"{BASE}/related", json={"sources": {"nope": [1]}}).status_code == 400
    r = client.post(f"{BASE}/related", json={"sources": {"link": list(range(10_001))}})
    assert r.status_code == 422 and "narrow the highlight" in r.text and "10000" not in r.text  # no echoed ids


def test_post_rows_matches_get(client):
    get = client.get(f"{BASE}/table/link/rows", params={"limit": 7, "sort": "link_id", "dir": "desc"}).json()
    post = client.post(f"{BASE}/table/link/rows", json={"limit": 7, "sort": "link_id", "dir": "desc"}).json()
    assert post == get


def test_post_rows_empty_ids_means_no_rows(client):
    assert client.post(f"{BASE}/table/link/rows", json={"ids": []}).json()["total"] == 0


def test_post_rows_tints_related_rows(client):
    j = client.post(f"{BASE}/table/lane/rows", json={"limit": 500, "related": {"sources": {"link": [1]}}}).json()
    link_col = j["columns"].index("link_id")
    tinted = [row[link_col] for row, via in zip(j["rows"], j["related"], strict=True) if via]
    assert tinted and set(tinted) == {1}
    assert set(v for v in j["related"] if v) == {"lane.link_id → link"}


def test_post_rows_filters_to_related_and_to_sources(client):
    body = {"related": {"sources": {"link": [1]}}, "related_mode": "filter"}
    lanes = client.post(f"{BASE}/table/lane/rows", json=body).json()
    assert lanes["total"] >= 1 and "related" not in lanes
    links = client.post(f"{BASE}/table/link/rows", json=body).json()
    assert links["total"] == 1  # the source table filters to the sources themselves


def test_locate_follows_the_page_order(client):
    rows = client.post(f"{BASE}/table/link/rows", json={"limit": 500, "sort": "link_id", "dir": "desc"}).json()
    ids = [r[rows["columns"].index("link_id")] for r in rows["rows"]]
    j = client.post(f"{BASE}/table/link/locate", json={"id": 5, "sort": "link_id", "dir": "desc"}).json()
    assert j["index"] == ids.index(5)
    assert client.post(f"{BASE}/table/lane/locate", json={"id": 1}).json() == {"index": None}  # lazy table


def test_post_routes_keep_the_origin_guard(client):
    r = client.post(f"{BASE}/related", json={"sources": {"link": [1]}}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_every_navigable_fk_targets_a_located_table(client):
    """A navigable FK cell must be able to land on its row: the target's key is its located primary key."""
    for name in [t["name"] for t in client.get(f"{BASE}/tables").json()["tables"]]:
        for fk in client.get(f"{BASE}/table/{name}/schema").json()["foreign_keys"]:
            target = client.get(f"{BASE}/table/{fk['ref_table']}/schema").json()
            assert fk["navigable"] is (fk["ref_column"] == target["primary_key"])


def test_jump_from_a_link_to_its_from_node_lands_on_that_row(client, link1):
    node = int(link1.from_node_id)
    j = client.post(f"{BASE}/table/node/locate", json={"id": node}).json()
    page = client.post(f"{BASE}/table/node/rows", json={"offset": (j["index"] // 100) * 100, "limit": 100}).json()
    assert node in [r[page["columns"].index("node_id")] for r in page["rows"]]


@pytest.mark.parametrize("source", ["link", "lane"])  # eager frame, lazy duckdb table
def test_numeric_string_ids_answer_like_ints(client, source):
    as_int = client.post(f"{BASE}/related", json={"sources": {source: [1]}}).json()
    as_text = client.post(f"{BASE}/related", json={"sources": {source: ["1"]}}).json()
    assert as_text == as_int and as_int["tables"]
    for name in ("lane", "link"):
        body = {"limit": 500, "related": {"sources": {source: [1]}}}
        rows_int = client.post(f"{BASE}/table/{name}/rows", json=body).json()
        body["related"]["sources"][source] = ["1"]
        assert client.post(f"{BASE}/table/{name}/rows", json=body).json() == rows_int


@pytest.mark.parametrize("name", ["link", "lane"])
def test_numeric_string_row_ids_and_locate_answer_like_ints(client, name):
    rows = [client.post(f"{BASE}/table/{name}/rows", json={"ids": ids}).json() for ids in ([1, 2], ["1", " 2"])]
    assert rows[0] == rows[1] and rows[0]["total"] == 2
    located = [client.post(f"{BASE}/table/{name}/locate", json={"id": key}).json() for key in (5, "5")]
    assert located[0] == located[1]


@pytest.mark.parametrize("name", ["link", "lane"])
def test_ids_that_cannot_be_keys_are_rejected(client, name):
    assert client.post(f"{BASE}/related", json={"sources": {name: ["abc"]}}).status_code == 422
    assert client.post(f"{BASE}/table/{name}/rows", json={"ids": ["abc"]}).status_code == 422
    assert client.post(f"{BASE}/table/{name}/locate", json={"id": "abc"}).status_code == 422
    assert client.get(f"{BASE}/table/{name}/rows", params={"ids": "1,abc"}).status_code == 422


def test_a_filter_value_of_the_wrong_type_is_a_400_on_a_lazy_table(client):
    bad = [{"col": "lane_id", "op": "eq", "val": "abc"}]
    assert client.post(f"{BASE}/table/lane/rows", json={"filter": bad}).status_code == 400
    bad_in = [{"col": "lane_id", "op": "in", "val": ["abc"]}]
    assert client.post(f"{BASE}/table/lane/rows", json={"filter": bad_in}).status_code == 400


def test_related_is_computed_once_per_question_and_version(client, session, monkeypatch):
    from netstead.workbench.routes import network

    calls = []
    real = network.relate
    monkeypatch.setattr(network, "relate", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    related = {"sources": {"link": [3, 4]}}
    for offset in (0, 2, 4):  # paging a tinted table
        client.post(f"{BASE}/table/lane/rows", json={"offset": offset, "limit": 2, "related": related})
    client.post(f"{BASE}/related", json=related)
    assert len(calls) == 1
    client.post(f"{BASE}/related", json={**related, "hops": 2})
    assert len(calls) == 2
    session.registry.get("leavenworth").bump()  # a mutated network asks again
    client.post(f"{BASE}/related", json=related)
    assert len(calls) == 3


def test_oversized_filters_are_rejected_without_echoing_values(client):
    many = [{"col": "link_id", "op": "notnull"}] * 51
    assert client.post(f"{BASE}/table/link/rows", json={"filter": many}).status_code == 422
    assert client.post(f"{BASE}/table/link/rows", json={"filter": many[:50]}).status_code == 200
    long_in = [{"col": "link_id", "op": "in", "val": list(range(10_001))}]
    r = client.post(f"{BASE}/table/lane/rows", json={"filter": long_in})
    assert r.status_code == 422 and "too many values" in r.text and "10000" not in r.text
    r = client.post(f"{BASE}/table/link/locate", json={"id": 1, "filter": long_in})
    assert r.status_code == 422
    r = client.get(f"{BASE}/table/link/rows", params={"filter": json.dumps(many)})
    assert r.status_code == 422
    ok_in = [{"col": "link_id", "op": "in", "val": list(range(10_000))}]
    assert client.post(f"{BASE}/table/lane/rows", json={"filter": ok_in}).status_code == 200


def test_related_reports_partial_and_truncated(client, session, monkeypatch):
    from netstead.workbench import related
    from netstead.workbench.routes import network

    session.registry.get("leavenworth").bump()  # drop answers memoised before the caps changed
    monkeypatch.setattr(related, "MAX_SOURCE_IDS", 1)
    monkeypatch.setattr(network, "MAX_MAP_IDS", 1)
    j = client.post(f"{BASE}/related", json={"sources": {"node": [1, 2, 3]}, "hops": 2}).json()
    by = {t["table"]: t for t in j["tables"]}
    assert by["link"]["partial"] is False and by["lane"]["partial"] is True
    assert j["map"]["link"]["truncated"] is True and len(j["map"]["link"]["ids"]) == 1
    session.registry.get("leavenworth").bump()


def test_locate_honours_ids_filter_and_related_filter(client, link1):
    ids = [5, 9, 2]
    assert client.post(f"{BASE}/table/link/locate", json={"id": 9, "ids": ids, "sort": "link_id"}).json() == {
        "index": 2
    }
    assert client.post(f"{BASE}/table/link/locate", json={"id": 7, "ids": ids}).json() == {"index": None}
    flt = [{"col": "link_id", "op": "gte", "val": 5}]
    assert client.post(f"{BASE}/table/link/locate", json={"id": 6, "filter": flt, "sort": "link_id"}).json() == {
        "index": 1
    }
    assert client.post(f"{BASE}/table/link/locate", json={"id": 4, "filter": flt}).json() == {"index": None}
    node = int(link1.to_node_id)
    related = {"related": {"sources": {"link": [1]}}, "related_mode": "filter", "sort": "node_id", "dir": "desc"}
    j = client.post(f"{BASE}/table/node/locate", json={"id": node, **related}).json()
    ends = sorted({int(link1.from_node_id), node}, reverse=True)
    assert j == {"index": ends.index(node)}
    other = next(n for n in range(1, 100) if n not in ends)
    assert client.post(f"{BASE}/table/node/locate", json={"id": other, **related}).json() == {"index": None}
