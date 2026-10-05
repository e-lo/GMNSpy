"""Tests for the workbench FastAPI app."""

import pytest
from fastapi.testclient import TestClient
from gmnspy.select.parse import StubParser
from gmnspy.workbench import Session, build_app
from gmnspy.workbench.server import _host_name

UTTERANCE = "I-40 EB between South Miami Boulevard and Airport Boulevard"


@pytest.fixture
def session(tmp_path, isolated_env, rdu_source):
    s = Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser())
    s.dispatch({"type": "open_network", "source": rdu_source})
    return s


@pytest.fixture
def client(session):
    return TestClient(build_app(session))


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_state(client):
    st = client.get("/api/state").json()
    assert st["active"] == "rdu-i40" and st["networks"][0]["links"] == 178


def test_config_is_keyless_basemap(client):
    assert "openfreemap" in client.get("/api/config").json()["style"]


def test_post_action_ok_returns_result_and_entry(client):
    r = client.post("/api/actions", json={"type": "select", "utterance": UTTERANCE})
    j = r.json()
    assert r.status_code == 200 and j["ok"] and j["result"]["status"] == "resolved"
    assert j["entry"]["python"] == f"app.do(Select(utterance={UTTERANCE!r}))"


def test_post_action_failure_is_400_and_recorded(client):
    r = client.post("/api/actions", json={"type": "set_active_network", "net_id": "nope"})
    assert r.status_code == 400 and "unknown network" in r.json()["error"]
    hist = client.get("/api/history").json()["entries"]
    assert hist[-1]["ok"] is False


def test_post_set_setting_cannot_widen_allowed_roots(client, session):
    roots = list(session.settings.io.allowed_roots)
    body = {"type": "set_setting", "key": "io.allowed_roots", "value": ["/"], "scope": "user"}
    r = client.post("/api/actions", json=body)
    assert r.status_code == 400 and "can only be set in config files, env, or on the command line" in r.json()["error"]
    assert session.settings.io.allowed_roots == roots


def test_post_invalid_action_is_422_and_not_recorded(client):
    before = len(client.get("/api/history").json()["entries"])
    r = client.post("/api/actions", json={"type": "select"})
    assert r.status_code == 422 and r.json()["error"] == "invalid action"
    assert len(client.get("/api/history").json()["entries"]) == before


def test_settings(client):
    j = client.get("/api/settings").json()
    assert j["values"]["viz"]["basemap"] == "positron" and j["sources"]["viz.basemap"] == "default"


def test_events_stream_starts_with_state_snapshot(client):
    with client.stream("GET", "/api/events", params={"max_events": 1}) as r:
        body = r.read().decode()
    assert r.headers["content-type"].startswith("text/event-stream")
    assert body.startswith("event: state\n") and '"active": "rdu-i40"' in body


def test_rejects_spoofed_host_header(client):
    """DNS-rebinding guard: a loopback bind only trusts the hosts it expects."""
    r = client.get("/", headers={"Host": "evil.example"})
    assert r.status_code == 400


def test_normal_request_still_works(client):
    """The TestClient's own Host header ("testserver") must stay allowed."""
    r = client.get("/")
    assert r.status_code == 200


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("127.0.0.1:8850", "127.0.0.1"),
        ("localhost", "localhost"),
        ("[::1]:8850", "[::1]"),
        ("[::1]", "[::1]"),
        ("Evil.Example:80", "evil.example"),
    ],
)
def test_host_name(header, expected):
    assert _host_name(header) == expected


def test_ipv6_loopback_bind_accepts_bracketed_host(tmp_path, isolated_env, rdu_source):
    """A ``--host ::1`` bind must accept the browser's bracketed Host header."""
    session = Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser(), overrides={"app.host": "::1"})
    session.dispatch({"type": "open_network", "source": rdu_source})
    ipv6_client = TestClient(build_app(session))
    assert ipv6_client.get("/", headers={"host": "[::1]:8850"}).status_code == 200
    assert ipv6_client.get("/", headers={"host": "evil.example"}).status_code == 400


def test_post_with_foreign_origin_is_403(client):
    r = client.post("/api/actions", json={"type": "clear_selection"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_post_with_cross_site_sec_fetch_is_403(client):
    r = client.post("/api/actions", json={"type": "clear_selection"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_post_with_matching_origin_is_ok(client):
    r = client.post("/api/actions", json={"type": "clear_selection"}, headers={"Origin": "http://127.0.0.1:8850"})
    assert r.status_code == 200


def test_post_with_no_origin_is_ok(client):
    """CLI/curl/TestClient callers send no Origin header at all."""
    r = client.post("/api/actions", json={"type": "clear_selection"})
    assert r.status_code == 200


def test_get_with_foreign_origin_still_ok(client):
    """Reads are harmless; the Host guard already covers DNS rebinding."""
    r = client.get("/", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200


def test_post_with_null_origin_is_403(client):
    r = client.post("/api/actions", json={"type": "clear_selection"}, headers={"Origin": "null"})
    assert r.status_code == 403


def test_invalid_action_422_never_echoes_values(client):
    key = "sk-ant-api03-ECHOCHECKabcdefghijklmnop"
    r = client.post("/api/actions", json={"type": "set_setting", "key": "select.model", "value": key})
    assert r.status_code == 422 and "ECHOCHECK" not in r.text


def test_rejected_base_url_with_userinfo_never_echoed(client):
    action = {"type": "set_setting", "key": "llm.openai.base_url", "value": "https://me:ECHOTOKEN@llm.example.org"}
    r = client.post("/api/actions", json=action)  # refused at validation: never recorded, never echoed
    assert r.status_code == 422 and "must not contain a username" in r.text and "ECHOTOKEN" not in r.text
    assert "ECHOTOKEN" not in client.get("/api/history").text


@pytest.mark.parametrize(
    "action",
    [
        {"type": "set_setting", "key": "llm.openai.api_key", "value": "ghp_SECRETMARKER123"},
        {"type": "set_setting", "key": "llm", "value": {"openai": {"api_key": "SECRETMARKER"}}},
    ],
)
def test_secret_named_settings_never_recorded(client, action):
    r = client.post("/api/actions", json=action)
    assert r.status_code == 422 and "SECRETMARKER" not in r.text
    assert "SECRETMARKER" not in client.get("/api/history").text
    with client.stream("GET", "/api/events", params={"max_events": 1}) as stream:
        assert "SECRETMARKER" not in "".join(stream.iter_text())


def test_estimate_422_never_echoes_values(client):
    r = client.post("/api/estimate", json={"source": "osm", "output_dir": "d", "output_format": "ECHOMARKER"})
    assert r.status_code == 422 and "ECHOMARKER" not in r.text
