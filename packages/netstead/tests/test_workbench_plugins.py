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
