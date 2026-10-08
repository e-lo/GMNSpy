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


class NamedSelect(BaseAction):
    type: Literal["hello.select"] = "hello.select"


class NamedSession(BaseAction):
    type: Literal["hello.session"] = "hello.session"


# Named like the core ``Select`` and the ``Session`` a replayed script constructs: importing either would rebind it.
NamedSelect.__name__ = NamedSelect.__qualname__ = "Select"
NamedSession.__name__ = NamedSession.__qualname__ = "Session"


class EmptySuffix(BaseAction):
    type: Literal["hello."] = "hello."


class Greet2(BaseAction):
    type: Literal["hello.greet"] = "hello.greet"


def _nested_action() -> type[BaseAction]:
    class Nested(BaseAction):
        type: Literal["hello.nested"] = "hello.nested"

    return Nested


def _main_action() -> type[BaseAction]:
    class Main(BaseAction):
        type: Literal["hello.main"] = "hello.main"

    Main.__qualname__, Main.__module__ = "Main", "__main__"
    return Main


class StrTyped(BaseAction):
    type: str = "hello.str"


class MultiTyped(BaseAction):
    type: Literal["hello.a", "hello.b"] = "hello.a"


def _spec(model: Any) -> ActionSpec:
    return ActionSpec(model, lambda h, a: None)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"id": "hello\n"}, "must match"),
        ({"actions": (_spec(EmptySuffix),)}, "then name the action"),
        ({"actions": (_spec(Greet), _spec(Greet))}, "declared twice"),
        ({"actions": (_spec(Greet), _spec(Greet2))}, "declared twice"),
        ({"actions": (_spec(NamedSelect),)}, "class name 'Select'"),
        ({"actions": (_spec(NamedSession),)}, "class name 'Session'"),
        ({"actions": (_spec(_nested_action()),)}, "top level of an importable module"),
        ({"actions": (_spec(_main_action()),)}, "top level of an importable module"),
        ({"actions": (_spec(StrTyped),)}, "one value"),
        ({"actions": (_spec(MultiTyped),)}, "one value"),
    ],
)
def test_problems_reports_what_would_break_parsing_or_replay(overrides, match):
    found = problems(make_hello(**overrides), ActionRegistry(), taken=())
    assert any(match in p for p in found), found


class OtherGreet(BaseAction):
    type: Literal["other.greet"] = "other.greet"


OtherGreet.__name__ = OtherGreet.__qualname__ = "Greet"  # another plugin's class with the same name


def test_problems_reports_a_class_name_another_plugin_registered():
    registry = ActionRegistry()
    registry.register(Greet)
    other = WorkbenchPlugin(id="other", name="O", version="0", requires_api=HOST_API, actions=(_spec(OtherGreet),))
    assert any("class name 'Greet'" in p for p in problems(other, registry, taken=()))


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


# ---------------------------------------------------------------------------- session install

from netstead.select.parse import StubParser  # noqa: E402
from netstead.workbench.actions import SetSetting  # noqa: E402
from netstead.workbench.session import ActionError, Session  # noqa: E402
from pydantic import ValidationError  # noqa: E402


@pytest.fixture
def make_session(tmp_path, isolated_env):
    def build(*plugins: WorkbenchPlugin, **overrides: Any) -> Session:
        return Session(
            project_dir=tmp_path, environ=isolated_env, parser=StubParser(), plugins=list(plugins), overrides=overrides
        )

    return build


def _status(session: Session, plugin_id: str):
    return next(s for s in session.plugin_status if s.id == plugin_id)


def test_plugin_action_dispatches_records_and_replays(make_session):
    session = make_session(make_hello())
    assert session.dispatch(Greet(name="Ada")) == "Hello, Ada!"
    assert session.dispatch({"type": "hello.greet", "name": "Bo"}) == "Hello, Bo!"
    entry = session.history[-1]
    assert entry.python == "app.do(Greet(name='Bo'))" and entry.imports == f"from {Greet.__module__} import Greet"
    assert _status(session, "hello").state == "loaded"


def test_plugin_state_is_merged_under_plugins(make_session):
    session = make_session(make_hello())
    session.dispatch(Greet(name="Ada"))
    assert session.state()["plugins"] == {"hello": {"greeted": ["Ada"]}}


def test_plugin_settings_come_from_the_layers(make_session):
    session = make_session(make_hello(), **{"plugins.hello.prefix": "Hi"})
    assert session.dispatch(Greet(name="Ada")) == "Hi, Ada!"


def test_invalid_plugin_settings_at_start_mark_the_plugin_error(make_session):
    session = make_session(make_hello(), **{"plugins.hello.bogus": 1})
    assert _status(session, "hello").state == "error" and "plugins.hello.bogus" in _status(session, "hello").error
    assert not session.actions.has("hello.greet")


def test_set_setting_validates_plugin_settings(make_session):
    session = make_session(make_hello())
    with pytest.raises(ActionError, match="plugin 'hello'"):
        session.dispatch(SetSetting(key="plugins.hello.prefix", value=3))
    assert session.dispatch(SetSetting(key="plugins.hello.prefix", value="Hey"))["value"] == "Hey"
    assert session.dispatch(Greet(name="Ada")) == "Hey, Ada!"
    assert session.dispatch(SetSetting(key="plugins.hello.prefix", value=None))["value"] is None
    assert session.dispatch(Greet(name="Ada")) == "Hello, Ada!"


@pytest.mark.parametrize("scope", ["user", "project"])
def test_set_setting_checks_a_persisted_plugin_setting_before_writing(make_session, scope):
    session = make_session(make_hello())
    paths = {"user": session.loaded.user_path, "project": session.loaded.project_path}
    with pytest.raises(ActionError, match=r"plugins\.hello\.bogus"):
        session.dispatch(SetSetting(key="plugins.hello.bogus", value="x", scope=scope))
    with pytest.raises(ActionError, match="plugin 'hello'"):
        session.dispatch(SetSetting(key="plugins.hello", value={"prefix": 3}, scope=scope))
    assert not paths[scope].exists()  # nothing a plugin rejects ever reaches a file
    assert session.dispatch(SetSetting(key="plugins.hello.prefix", value="Yo", scope=scope))["value"] == "Yo"
    assert session.dispatch(Greet(name="Ada")) == "Yo, Ada!"


def test_settings_of_a_plugin_that_is_not_loaded_are_not_checked(make_session):
    session = make_session(make_hello(), **{"app.disabled_plugins": ["hello"]})
    assert session.dispatch(SetSetting(key="plugins.hello.anything", value=1))["value"] == 1


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("plugins.hello.api_key", "x"),  # secret-named key
        ("plugins.hello.token", "x"),
        ("plugins.hello.prefix", "sk-ant-api03-" + "a" * 40),  # key-shaped value
        ("plugins.hello", {"auth": {"password": "x"}}),  # secret-named key nested in the value
        ("plugins.hello.endpoint", "https://user:pw@example.com/"),  # URL userinfo
    ],
)
def test_plugin_secrets_are_refused_like_any_setting(key, value):
    with pytest.raises(ValidationError) as info:
        SetSetting(key=key, value=value)
    assert "sk-ant" not in str(info.value) and "pw@" not in str(info.value)


def test_a_refused_plugin_secret_is_recorded_without_its_value(make_session):
    session = make_session(make_hello())
    with pytest.raises(ValidationError):
        session.dispatch({"type": "set_setting", "key": "plugins.hello.api_key", "value": "hunter2"})
    assert session.history == [] and "api_key" not in session.settings.plugins.get("hello", {})


@pytest.mark.parametrize(
    ("plugin", "overrides", "state"),
    [
        (make_hello(), {"app.disabled_plugins": ["hello"]}, "disabled"),
        (make_hello(requires_api="2.0"), {}, "incompatible"),
        (make_hello(id="Bad Id"), {}, "error"),
    ],
)
def test_plugins_that_do_not_install(make_session, plugin, overrides, state):
    session = make_session(plugin, **overrides)
    assert session.plugin_status[0].state == state and not session.actions.has("hello.greet")


def test_failing_on_load_installs_nothing(make_session):
    def boom(host):
        raise RuntimeError("cannot start")

    session = make_session(make_hello(on_load=boom))
    assert _status(session, "hello").state == "error" and "cannot start" in _status(session, "hello").error
    assert not session.actions.has("hello.greet") and "hello" not in session.plugins


def test_failing_state_is_reported_not_raised(make_session):
    def bad_state(host):
        raise RuntimeError("oops")

    session = make_session(make_hello(state=bad_state))
    assert session.state()["plugins"]["hello"] == {"error": "RuntimeError: oops"}


def test_duplicate_plugin_ids_keep_the_first(make_session):
    session = make_session(make_hello(), make_hello())
    assert [s.state for s in session.plugin_status] == ["loaded", "error"]


class Shout(BaseAction):
    type: Literal["loud.shout"] = "loud.shout"
    name: str


def test_plugins_call_each_other_through_actions(make_session):
    def shout(host, action: Shout) -> str:
        if not host.has_action("hello.greet"):
            return action.name.upper()
        return host.dispatch(Greet(name=action.name)).upper()

    loud = WorkbenchPlugin(
        id="loud", name="Loud", version="0.1", requires_api=HOST_API, actions=(ActionSpec(Shout, shout),)
    )
    assert make_session(loud).dispatch(Shout(name="ada")) == "ADA"
    both = make_session(make_hello(), loud)
    assert both.dispatch(Shout(name="ada")) == "HELLO, ADA!"
    assert [e.action["type"] for e in both.history] == ["hello.greet", "loud.shout"]  # inner first


class Widen(BaseAction):
    type: Literal["edit.widen"] = "edit.widen"
    mutates: ClassVar[bool] = True
    link_id: int


def test_a_plugin_previews_an_edit_on_a_derived_network(make_session, rdu_source):
    from corral.editing import Edit
    from netstead.workbench.actions import OpenNetwork

    def widen(host, action: Widen) -> str:
        preview = host.derive(None, label="Preview", note="preview")
        payload = {"predicate": lambda t: t.link_id == action.link_id, "set": {"lanes": 9}}
        host.mutate(preview, [Edit(op="update_rows", table="link", payload=payload)], note=f"widen {action.link_id}")
        return preview

    editor = WorkbenchPlugin(
        id="edit", name="Edit", version="0.1", requires_api=HOST_API, actions=(ActionSpec(Widen, widen),)
    )
    session = make_session(editor)
    session.dispatch(OpenNetwork(source=rdu_source))
    first = int(session.registry.get("rdu-i40").links_df()["link_id"].iloc[0])
    preview = session.dispatch(Widen(link_id=first))
    summary = next(n for n in session.state()["networks"] if n["id"] == preview)
    assert summary["derived_from"] == "rdu-i40" and summary["lineage"] == ["edit: preview", f"edit: widen {first}"]
    assert session.registry.get("rdu-i40").version == 0


# ---------------------------------------------------------------------------- a real entry point

_FAKE_PLUGIN = """
from typing import Literal
from netstead.workbench.plugins import HOST_API, ActionSpec, BaseAction, WorkbenchPlugin


class Ping(BaseAction):
    type: Literal["fake.ping"] = "fake.ping"


def plugin():
    return WorkbenchPlugin(id="fake", name="Fake", version="0.1", requires_api=HOST_API,
                           actions=(ActionSpec(Ping, lambda host, action: "pong"),))
"""


@pytest.mark.plugin_discovery
def test_installed_entry_point_is_discovered_by_default(tmp_path, isolated_env, monkeypatch):
    site = tmp_path / "site"
    dist = site / "netstead_fake_plugin-0.1.dist-info"
    dist.mkdir(parents=True)
    (site / "netstead_fake_plugin.py").write_text(_FAKE_PLUGIN, encoding="utf-8")
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: netstead-fake-plugin\nVersion: 0.1\n", encoding="utf-8"
    )
    (dist / "entry_points.txt").write_text(
        "[netstead.workbench.plugins]\nfake = netstead_fake_plugin:plugin\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.delitem(__import__("sys").modules, "netstead_fake_plugin", raising=False)

    session = Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser())  # plugins=None: discover
    assert _status(session, "fake").state == "loaded"
    assert session.dispatch({"type": "fake.ping"}) == "pong"
    assert session.history[-1].imports == "from netstead_fake_plugin import Ping"


# ---------------------------------------------------------------------------- install is all-or-nothing


class Wave(BaseAction):
    type: Literal["hello.wave"] = "hello.wave"


def test_a_plugin_declaring_a_type_twice_is_an_error_not_an_exception(make_session):
    session = make_session(make_hello(actions=(_spec(Wave), _spec(Greet), _spec(Greet))))
    assert _status(session, "hello").state == "error" and "declared twice" in _status(session, "hello").error
    assert not session.actions.has("hello.wave") and not session.actions.has("hello.greet")


def test_a_registration_failure_rolls_back_the_plugins_earlier_actions(make_session, monkeypatch):
    import netstead.workbench.session as session_module

    monkeypatch.setattr(session_module, "problems", lambda *args: [])  # as if a check were missed
    session = make_session(make_hello(actions=(_spec(Wave), _spec(Greet), _spec(StrTyped))))
    assert _status(session, "hello").state == "error" and "one value" in _status(session, "hello").error
    assert not session.actions.has("hello.wave") and not session.actions.has("hello.greet")
    assert "hello.wave" not in session._handlers and "hello" not in session.plugins
    assert session.dispatch({"type": "clear_selection"}) is None  # parsing still works for core Actions


def test_session_script_with_plugin_and_failed_entries_replays(make_session, rdu_source):
    """ "Copy session as Python" for a mixed core + plugin session, with a failed plugin entry, runs as is."""
    from fastapi.testclient import TestClient
    from netstead.workbench import build_app
    from netstead.workbench.actions import OpenNetwork, Style

    def hello_with_failures(**overrides: Any) -> WorkbenchPlugin:
        plugin = make_hello(**overrides)
        greet = plugin.actions[0].handler

        def picky(host, action: Greet) -> str:
            if action.name == "nobody":
                raise ActionError("nobody to greet")
            return greet(host, action)

        return make_hello(actions=(ActionSpec(Greet, picky),), **overrides)

    session = make_session(hello_with_failures())
    session.dispatch(OpenNetwork(source=rdu_source))
    session.dispatch(Greet(name="Ada"))
    with pytest.raises(ActionError):
        session.dispatch(Greet(name="nobody"))
    session.dispatch(Style(offset=False))
    history = TestClient(build_app(session)).get("/api/history").json()

    # The same assembly as ``sessionScript`` in static/js/history.js.
    lines = [*history["imports"], "", "app = Session()  # or reuse a live session"]
    lines += [e["python"] if e["ok"] else f"# failed: {e['python']}  # {e['error']}" for e in history["entries"]]
    script = "\n".join(lines)
    assert history["imports"][1:] == [f"from {Greet.__module__} import Greet"]
    assert "# failed: app.do(Greet(name='nobody'))" in script

    replay = make_session(hello_with_failures())
    namespace: dict[str, Any] = {}
    exec(script.replace("app = Session()", "app = replay"), {"replay": replay}, namespace)
    assert namespace["Session"].__module__ == "netstead.workbench.session"  # never rebound by a plugin import
    assert replay.state() == session.state()


def test_settings_payload_redacts_plugin_values(make_session):
    """Defence in depth: even a plugin table that bypassed validation reaches the browser redacted."""
    session = make_session(make_hello(), **{"plugins.hello.prefix": "Hi"})
    session.settings.plugins["hello"]["token"] = "MARKER"  # in place: no validator runs
    values = session.settings_payload()["values"]["plugins"]
    assert values == {"hello": {"prefix": "Hi", "token": "[redacted]"}}


# ---------------------------------------------------------------------------- SystemExit vs KeyboardInterrupt


def _raise(exc: BaseException):
    def factory(*args: Any) -> Any:
        raise exc

    return factory


def test_discover_records_a_factory_calling_sys_exit():
    plugins, statuses = discover(eps=[FakeEntryPoint("quits", _raise(SystemExit(3)))])
    assert plugins == [] and statuses[0].state == "error" and "SystemExit" in statuses[0].error


def test_discover_lets_keyboard_interrupt_through():
    with pytest.raises(KeyboardInterrupt):
        discover(eps=[FakeEntryPoint("stop", _raise(KeyboardInterrupt()))])


def test_on_load_calling_sys_exit_marks_the_plugin_error(make_session):
    session = make_session(make_hello(on_load=_raise(SystemExit(1))))
    assert _status(session, "hello").state == "error" and "SystemExit" in _status(session, "hello").error


def test_on_load_keyboard_interrupt_propagates(make_session):
    with pytest.raises(KeyboardInterrupt):
        make_session(make_hello(on_load=_raise(KeyboardInterrupt())))


# ---------------------------------------------------------------------------- the hello example package


def test_hello_example_plugin_works(tmp_path, isolated_env, monkeypatch):
    from pathlib import Path

    example = Path(__file__).resolve().parents[3] / "examples" / "workbench-plugin-hello"
    monkeypatch.syspath_prepend(str(example))
    import netstead_hello

    session = Session(
        project_dir=tmp_path, environ=isolated_env, parser=StubParser(), plugins=[netstead_hello.plugin()]
    )
    assert session.dispatch({"type": "hello.greet", "name": "Ada"}) == "Hello, Ada!"
    assert session.state()["plugins"]["hello"] == {"greeted": 1}
    assert session.history[-1].imports == "from netstead_hello import Greet"
    assert (netstead_hello.plugin().static_dir / "main.js").is_file()


@pytest.mark.plugin_discovery
def test_installed_hello_example_is_discovered_through_its_entry_point(tmp_path, isolated_env):
    """CI installs ``examples/workbench-plugin-hello``, so its real packaging metadata is exercised here."""
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        distribution("netstead-hello")
    except PackageNotFoundError:
        pytest.skip("examples/workbench-plugin-hello is not installed (CI installs it)")
    session = Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser())  # plugins=None: discover
    assert _status(session, "hello").state == "loaded"
    assert _status(session, "hello").frontend == "/plugins/hello/main.js"
    assert session.dispatch({"type": "hello.greet", "name": "Ada"}) == "Hello, Ada!"
