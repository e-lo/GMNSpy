"""Tests for workbench Action schemas."""

import pytest
from gmnspy.workbench.actions import (
    Navigate,
    OpenNetwork,
    Select,
    SetSetting,
    Style,
    action_json_schema,
    parse_action,
    to_python,
)
from pydantic import ValidationError


def test_parse_action_discriminates_on_type():
    a = parse_action({"type": "open_network", "source": "/x"})
    assert isinstance(a, OpenNetwork) and a.source == "/x"


def test_unknown_type_and_extra_fields_rejected():
    with pytest.raises(ValidationError):
        parse_action({"type": "launch_rockets"})
    with pytest.raises(ValidationError):
        parse_action({"type": "open_network", "source": "/x", "bogus": 1})


def test_select_needs_exactly_one_of_utterance_or_link_ids():
    with pytest.raises(ValidationError):
        Select()
    with pytest.raises(ValidationError):
        Select(utterance="I-40", link_ids=[1])
    assert Select(link_ids=[1, 2]).component == "roadway"


def test_select_accepts_transit_component_in_schema():
    assert Select(utterance="route 38", component="transit").component == "transit"


def test_navigate_needs_exactly_one_target():
    with pytest.raises(ValidationError):
        Navigate()
    with pytest.raises(ValidationError):
        Navigate(to_network=True, to_selection=True)
    assert Navigate(bbox=(-79, 35, -78, 36)).bbox == (-79, 35, -78, 36)


def test_style_colors_must_be_rgb_triples():
    with pytest.raises(ValidationError):
        Style(colors={"links": [1, 2]})
    assert Style(show={"nodes": False}).show == {"nodes": False}


def test_set_setting_is_mutating():
    assert SetSetting.mutates is True and Select.mutates is False


def test_to_python_omits_defaults_and_type():
    assert to_python(OpenNetwork(source="/x")) == "app.do(OpenNetwork(source='/x'))"
    assert to_python(Select(utterance="I-40 EB")) == "app.do(Select(utterance='I-40 EB'))"
    assert to_python(Style(show={"nodes": False})) == "app.do(Style(show={'nodes': False}))"


def test_action_json_schema_lists_every_type():
    schema = action_json_schema()
    types = {v["properties"]["type"]["const"] for v in schema["$defs"].values() if "type" in v.get("properties", {})}
    assert {"open_network", "select", "style", "navigate", "set_setting"} <= types


def test_open_network_is_a_job_action():
    assert OpenNetwork.runs_as_job and not Select.runs_as_job and not OpenNetwork.mutates
    assert OpenNetwork.replay_overrides == {}
