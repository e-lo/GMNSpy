"""Tests for the workbench FastAPI app."""

import pytest
from fastapi.testclient import TestClient
from gmnspy.select.parse import StubParser
from gmnspy.workbench import Session, build_app

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
