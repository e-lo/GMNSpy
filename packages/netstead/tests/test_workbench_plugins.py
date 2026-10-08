"""Tests for Workbench plugins: spec checks, discovery, install, Host, settings, state."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

import pytest
from netstead.workbench.actions import ActionRegistry, BaseAction
from netstead.workbench.plugins import HOST_API, ActionSpec, WorkbenchPlugin
from netstead.workbench.plugins.spec import api_compatible, problems
from pydantic import BaseModel, ConfigDict


class Greet(BaseAction):
    type: Literal["hello.greet"] = "hello.greet"
    name: str


class HelloSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prefix: str = "Hello"


def make_hello(**overrides: Any) -> WorkbenchPlugin:
    """A fresh ``hello`` plugin: ``hello.greet`` returns ``"<prefix>, <name>!"`` and remembers names in state."""
    greeted: list[str] = []

    def greet(host, action: Greet) -> str:
        greeted.append(action.name)
        return f"{host.settings.prefix}, {action.name}!"

    fields: dict[str, Any] = {
        "id": "hello",
        "name": "Hello",
        "version": "0.1",
        "requires_api": HOST_API,
        "actions": (ActionSpec(Greet, greet),),
        "settings_model": HelloSettings,
        "state": lambda host: {"greeted": list(greeted)},
    }
    fields.update(overrides)
    return WorkbenchPlugin(**fields)


# ---------------------------------------------------------------------------- spec


def test_api_compatible_same_major_and_new_enough_minor():
    assert api_compatible("1.0", "1.2") and api_compatible("1.2", "1.2")
    assert not api_compatible("1.3", "1.2") and not api_compatible("2.0", "1.2")
    assert not api_compatible("one", "1.0") and not api_compatible("1", "1.0")


def test_problems_none_for_a_good_plugin():
    assert problems(make_hello(), ActionRegistry(), taken=()) == []


class Unprefixed(BaseAction):
    type: Literal["greet"] = "greet"


class JobAction(BaseAction):
    type: Literal["hello.slow"] = "hello.slow"
    runs_as_job: ClassVar[bool] = True


@pytest.mark.parametrize(
    ("overrides", "taken", "match"),
    [
        ({"id": "Hello-World"}, (), "must match"),
        ({}, ("hello",), "already uses"),
        ({"actions": (ActionSpec(Unprefixed, lambda h, a: None),)}, (), "must start with 'hello.'"),
        ({"actions": (ActionSpec(JobAction, lambda h, a: None),)}, (), "job actions"),
        ({"actions": (ActionSpec(dict, lambda h, a: None),)}, (), "not a BaseAction"),  # type: ignore[arg-type]
    ],
)
def test_problems_reports_each_violation(overrides, taken, match):
    found = problems(make_hello(**overrides), ActionRegistry(), taken=taken)
    assert any(match in p for p in found), found


def test_problems_reports_a_type_already_registered():
    registry = ActionRegistry()
    registry.register(Greet)
    assert any("already registered" in p for p in problems(make_hello(), registry, taken=()))


# ---------------------------------------------------------------------------- discovery

from dataclasses import dataclass  # noqa: E402

from netstead.workbench.plugins.discovery import PluginStatus, discover  # noqa: E402


@dataclass
class FakeEntryPoint:
    name: str
    target: Any  # the factory, or an exception ``load`` raises

    def load(self) -> Any:
        if isinstance(self.target, Exception):
            raise self.target
        return self.target


def test_discover_loads_factories_and_isolates_failures():
    eps = [
        FakeEntryPoint("hello", make_hello),
        FakeEntryPoint("broken", ImportError("no module named broken")),
        FakeEntryPoint("not_a_plugin", lambda: 42),
        FakeEntryPoint("misnamed", make_hello),  # factory's plugin id is "hello"
    ]
    plugins, statuses = discover(eps=eps)
    assert [p.id for p in plugins] == ["hello"]
    by_id = {s.id: s for s in statuses}
    assert by_id["broken"].state == "error" and "no module named broken" in by_id["broken"].error
    assert by_id["not_a_plugin"].state == "error" and "WorkbenchPlugin" in by_id["not_a_plugin"].error
    assert by_id["misnamed"].state == "error" and "must equal" in by_id["misnamed"].error


def test_discover_skips_disabled_without_importing_them():
    plugins, statuses = discover(disabled={"broken"}, eps=[FakeEntryPoint("broken", ImportError("x"))])
    assert plugins == [] and statuses == [
        PluginStatus(id="broken", name="broken", version="", requires_api=None, state="disabled")
    ]


# ---------------------------------------------------------------------------- host settings

from netstead.workbench.plugins.host import PluginSettingsError, validate_plugin_settings  # noqa: E402


def test_validate_plugin_settings_defaults_and_values():
    assert validate_plugin_settings(HelloSettings, {}, "hello").prefix == "Hello"
    assert validate_plugin_settings(HelloSettings, {"prefix": "Hi"}, "hello").prefix == "Hi"


def test_validate_plugin_settings_never_echoes_values():
    with pytest.raises(PluginSettingsError) as info:
        validate_plugin_settings(HelloSettings, {"prefix": "s3cr3t-value", "bogus": "s3cr3t-value"}, "hello")
    assert "plugins.hello.bogus" in str(info.value) and "s3cr3t" not in str(info.value)
    assert info.value.__context__ is None and info.value.__cause__ is None
