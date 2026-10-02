"""Tests for the workbench Session (the action bus)."""

from pathlib import Path

import pytest
from gmnspy import Network
from gmnspy.select.parse import StubParser
from gmnspy.workbench.actions import (
    ClearSelection,
    CloseNetwork,
    Navigate,
    OpenNetwork,
    Select,
    SetActiveNetwork,
    SetSetting,
    Style,
)
from gmnspy.workbench.session import ActionError, NotSupportedYet, Session

UTTERANCE = "I-40 EB between South Miami Boulevard and Airport Boulevard"


@pytest.fixture
def session(tmp_path, isolated_env):
    return Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser())


@pytest.fixture
def opened(session, rdu_source):
    session.dispatch(OpenNetwork(source=rdu_source))
    return session


def test_open_network_registers_activates_and_records(opened, rdu_source):
    assert opened.active == "rdu-i40"
    entry = opened.history[-1]
    assert entry.ok and entry.seq == 1 and entry.result == {"net_id": "rdu-i40"}
    assert entry.python == f"app.do(OpenNetwork(source={rdu_source!r}))"


def test_open_bad_path_is_recorded_failure(session, tmp_path):
    with pytest.raises(ActionError, match="could not open"):
        session.dispatch(OpenNetwork(source=str(tmp_path / "missing")))
    assert session.history[-1].ok is False and len(session.registry) == 0


def test_dispatch_accepts_plain_dicts(session, rdu_source):
    assert session.dispatch({"type": "open_network", "source": rdu_source}) == {"net_id": "rdu-i40"}


def test_select_utterance_resolves_with_anchors(opened):
    sel = opened.dispatch(Select(utterance=UTTERANCE))
    assert sel["status"] == "resolved" and sel["net_id"] == "rdu-i40"
    assert sel["link_ids"] and {a["role"] for a in sel["anchors"]} == {"from", "to"}
    assert sel["fragment"] is not None
    assert opened.state()["selection"] == sel


def test_select_unparseable_is_not_found_not_error(opened):
    sel = opened.dispatch(Select(utterance="???"))
    assert sel["status"] == "not_found" and sel["diagnostics"][0].startswith("could not parse")


def test_select_link_ids(opened):
    ids = [int(i) for i in opened.registry.get("rdu-i40").links_df()["link_id"].iloc[:2]]
    sel = opened.dispatch(Select(link_ids=ids))
    assert sorted(sel["link_ids"]) == sorted(ids)


def test_select_transit_not_supported_yet(opened):
    with pytest.raises(NotSupportedYet, match="transit"):
        opened.dispatch(Select(utterance="route 38", component="transit"))
    assert opened.history[-1].ok is False


def test_select_without_network_fails(session):
    with pytest.raises(ActionError, match="no network is open"):
        session.dispatch(Select(utterance=UTTERANCE))


def test_clear_selection(opened):
    opened.dispatch(Select(utterance=UTTERANCE))
    opened.dispatch(ClearSelection())
    assert opened.selection is None


def test_style_partial_merge_and_validation(opened):
    opened.dispatch(Style(show={"nodes": False}))
    assert opened.style["show"] == {"links": True, "nodes": False, "labels": True, "selection": True}
    opened.dispatch(Style(color_by="lanes"))
    assert opened.style["color_by"] == "lanes"
    with pytest.raises(ActionError, match="cannot color by"):
        opened.dispatch(Style(color_by="geometry"))


def test_navigate_publishes_event(opened):
    published = []
    opened.events.publish = published.append
    opened.dispatch(Navigate(to_network=True))
    assert published[0] == {"type": "navigate", "bbox": None, "to_network": True, "to_selection": False}
    assert [e["type"] for e in published] == ["navigate", "history", "state"]


def test_navigate_to_selection_requires_selection(opened):
    with pytest.raises(ActionError, match="nothing is selected"):
        opened.dispatch(Navigate(to_selection=True))


def test_set_setting_session_scope(opened):
    result = opened.dispatch(SetSetting(key="viz.basemap", value="esri"))
    assert result == {"key": "viz.basemap", "value": "esri", "source": "session"}
    assert opened.settings.viz.basemap == "esri"


def test_set_setting_user_scope_writes_file(opened, isolated_env):
    opened.dispatch(SetSetting(key="app.port", value=9200, scope="user"))
    assert "port = 9200" in (Path(isolated_env["GMNSPY_CONFIG_DIR"]) / "config.toml").read_text()
    assert opened.loaded.sources["app.port"] == "user"


def test_set_setting_rejects_bad_value(opened):
    with pytest.raises(ActionError, match="invalid settings"):
        opened.dispatch(SetSetting(key="select.provider", value="gpt"))


def test_close_and_switch_networks(opened, rdu_source):
    opened.dispatch(OpenNetwork(source=rdu_source, label="copy"))
    assert opened.active == "copy"
    opened.dispatch(SetActiveNetwork(net_id="rdu-i40"))
    assert opened.active == "rdu-i40"
    opened.dispatch(CloseNetwork(net_id="rdu-i40"))
    assert opened.active == "copy" and opened.registry.ids() == ["copy"]


def test_unexpected_handler_error_is_recorded_not_raised_raw(opened, monkeypatch):
    def _boom(action):
        raise KeyError("boom")

    monkeypatch.setattr(opened, "_do_clear_selection", _boom)
    with pytest.raises(ActionError, match="internal error: KeyError"):
        opened.dispatch(ClearSelection())
    entry = opened.history[-1]
    assert entry.ok is False and entry.error_type == "InternalError"


def test_add_network_from_python(session, rdu_source):
    h = session.add_network(Network.from_source(rdu_source), source=rdu_source)
    assert session.active == h.id and session.history == []


def test_state_shape(opened):
    st = opened.state()
    assert set(st) == {"networks", "active", "selection", "style"}
    assert st["networks"][0]["links"] == 178


def test_settings_payload(opened):
    p = opened.settings_payload()
    assert p["values"]["app"]["port"] == 8850 and p["sources"]["app.port"] == "default"
    assert "properties" in p["schema"] and set(p["paths"]) == {"user", "project"}


def test_history_python_replays_to_same_state(session, rdu_source):
    session.dispatch(OpenNetwork(source=rdu_source))
    session.dispatch(Select(utterance=UTTERANCE))
    session.dispatch(Style(color_by="lanes"))
    session.dispatch(ClearSelection())

    replay = Session(project_dir=session.project_dir, environ=session._environ, parser=StubParser())
    import gmnspy.workbench as workbench_module

    globals_ns = {name: getattr(workbench_module, name) for name in workbench_module.__all__}
    globals_ns["app"] = replay
    for entry in session.history:
        if entry.ok:
            exec(entry.python, globals_ns)

    assert replay.state() == session.state()
