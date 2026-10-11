---
title: Write a Workbench plugin
audience: contributors
kind: howto
summary: Package Actions, settings, state, an API router and a front-end module as a pip-installable plugin that the Netstead Workbench loads at startup, without editing Workbench core.
---

# Write a Workbench plugin

## When to use this

You want the [Workbench](workbench.md) to do something it doesn't do yet, such as authoring project
cards, managing a scenario catalog or running a domain check, and you don't want to fork netstead
to get it. A plugin is a separate pip package. Install it next to netstead and `netstead app`
picks it up.

The plugin API is **provisional until netstead v1.0** (see [Versioning](#versioning)).

## What a plugin is

A plugin is a Python package that declares an entry point in the `netstead.workbench.plugins`
group. The entry-point name must equal the plugin id, and it points at a zero-argument factory that
returns a `netstead.workbench.plugins.WorkbenchPlugin`:

```toml
[project.entry-points."netstead.workbench.plugins"]
hello = "netstead_hello:plugin"
```

At startup each `netstead app` session discovers the installed entry points, checks each plugin,
and installs the ones that pass. A plugin that fails is recorded with its reason and skipped. It
never stops the app (see [Startup outcomes](#startup-outcomes)).

### Trust model

**Plugins are full-trust code running inside the Workbench process**, the same as pytest plugins.
Nothing sandboxes them. A plugin can do anything your user account can do: read and write any
file, call the network, and read the OS keyring. The `Host` API is the *supported* surface, not a
security boundary. The `io.allowed_roots` sandbox that `host.writable` applies only helps plugins
that choose to use it. Install only plugins you would also run as a script.

The `--host 0.0.0.0` warning from [Explore in the Workbench](workbench.md) applies with more force
here. An exposed bind has no authentication, and every loaded plugin's routes
(`/api/plugins/<id>/...`) and Actions (`POST /api/actions`) are exposed with it. While the server
binds to a loopback address, plugin routes sit behind the same `Host`-header and cross-origin
write guards as every core route. Those guards do not run on an exposed bind.

## The UX contract

The Workbench stays coherent only if every plugin follows the same rules. These are condensed from
the design. Core enforces some of them and plugins are expected to follow the rest.

1. **Core owns the shared network nouns; plugins may own domain nouns.** Core owns networks
   (including derived networks and their lineage), the **one shared selection**, the map and
   tables, jobs, history and settings. A plugin never forks the selection or brings a second map.
   A plugin may add domain nouns of its own (a *card*, a *scenario*), and these follow three rules:
    - **Namespaced and exposed.** They live in plugin state (`plugins.<id>.*` in `/api/state`) and
      change only through that plugin's namespaced Actions, so other plugins, Python and NL can see
      and act on them.
    - **Projected onto core nouns, never duplicating them.** A card *resolves to* a core selection
      (highlighting it is an ordinary `Select`). A scenario *materializes as* a core derived
      network, so the map, tables and validation work on it unchanged.
    - **Referenceable by a stable id** of the form `{plugin}:{kind}/{id}`, for example
      `catalog:card/I80-hov-2035`, so history and "copy as Python" stay replayable.

    **Cross-plugin interaction is by Action.** Check for the other plugin's Action with
    `host.has_action("catalog.add_card")` and dispatch it, or fall back. That is a *soft*
    dependency, and core has no service registry. If you need another plugin's Python API, declare
    a normal pip dependency on it.
2. **Selection → verb → form → preview → commit.** The user selects, picks a verb, fills a form
   prefilled from the selection, sees a preview on the map, and commits. Present your workflows in
   this shape.
3. **Nothing mutates silently.** Previews and scenarios are derived networks (`host.derive`) and
   leave the base untouched. Make in-place changes (`host.mutate`) inside an Action handler: the
   Action is recorded in history and replays in "copy as Python", and if the handler fails the
   change is undone. A `mutate` from anywhere else (a `submit_job` function, a plugin route) still
   appears in history, as a `<id>.mutate` entry, but it can't be replayed: the copied script shows
   it only as a comment.
4. **Everything is an Action, plugins included.** Plugin Action types are namespaced
   (`<id>.<name>`) and get the same history, "copy as Python", replay and HTTP dispatch as core
   Actions.
5. **Schema-driven forms.** Plugin Actions render from their JSON Schema through one core form
   component, so a new Action needs no form code and every form looks alike. (The browser side
   arrives with the plugin front end.)
6. **Workspaces as tabs, with predictable placement.** Plugins contribute workspaces, dock panels,
   commands (palette, context menus, the NL assistant) and map layers. They don't add ad-hoc UI.
7. **Dirty state is always visible.** Unsaved drafts, uncommitted cards and derived networks are
   badged in the network switcher and on workspace tabs.
8. **Plugins are accountable.** Every installed plugin reports its id, version, required API and
   load error. A broken plugin degrades to "not loaded, with this error" and never takes down the
   app.

## Walk through the `hello` example

[`examples/workbench-plugin-hello`](https://github.com/e-lo/netstead/tree/main/examples/workbench-plugin-hello)
is a complete plugin. Copy it as a starting point:

```bash
uv pip install -e examples/workbench-plugin-hello
uv run netstead app
```

### Actions

An Action is a module-level subclass of `netstead.workbench.plugins.BaseAction`. Its `type`
field is a single-value `Literal` named `"<plugin id>.<name>"`:

<!-- doctest: skip -->
```python
from typing import Literal

from netstead.workbench.plugins import BaseAction


class Greet(BaseAction):
    type: Literal["hello.greet"] = "hello.greet"
    name: str
```

Each Action is paired with its handler in a `netstead.workbench.plugins.ActionSpec`. The handler
signature is `handler(host, action) -> result`. It runs under the session lock. Its return value
is what `session.dispatch` returns, and over HTTP it is the `result` field of the `POST /api/actions`
response, next to `ok`, `error` and the recorded history `entry`. Set `mutates: ClassVar[bool] = True`
on an Action that changes a network in place, so the assistant drafts it for the user to confirm
instead of applying it. Plugin Actions can't be `runs_as_job`. For slow work, call `host.submit_job`
from the handler.

Two rules keep "copy session as Python" working:

- **The class must be importable.** Define it at the top level of a module (not in a function and
  not in `__main__`), and give it a class name no core Action or other plugin uses. The copied
  script imports it as `from <its module> import <Class>`. For the example that is
  `from netstead_hello import Greet`.
- **Field values must round-trip through `repr`.** The replay line is
  `app.do(Greet(name='Ada'))`, built from `repr(value)` of each field. Use str, numbers, bools,
  `None`, lists, dicts and tuples of those, or nested pydantic models. A value whose `repr` isn't
  valid Python (a numpy array, a datetime without an import, an open file) makes the copied script
  fail.

The startup checks enforce the namespacing, the single `Literal`, importability and unique class
names. The `repr` rule is yours to keep.

### The plugin object

<!-- doctest: skip -->
```python
from pathlib import Path

from netstead.workbench.plugins import HOST_API, ActionSpec, Host, WorkbenchPlugin
from pydantic import BaseModel, ConfigDict


class HelloSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prefix: str = "Hello"


def plugin() -> WorkbenchPlugin:
    greeted = {"count": 0}  # per-session state lives in the factory's closure

    def greet(host: Host, action: Greet) -> str:
        greeted["count"] += 1
        host.publish("greeted", {"name": action.name})
        return f"{host.settings.prefix}, {action.name}!"

    return WorkbenchPlugin(
        id="hello",
        name="Hello",
        version="0.1.0",
        requires_api=HOST_API,
        actions=(ActionSpec(Greet, greet),),
        router=router,  # see below
        static_dir=Path(__file__).parent / "static",
        settings_model=HelloSettings,
        state=lambda host: {"greeted": greeted["count"]},
    )
```

| Field | What it does |
|---|---|
| `id` | The namespace for Action types, routes, state, settings and static files. Must match `[a-z][a-z0-9_]*` and equal the entry-point name. |
| `requires_api` | The plugin API version you wrote against. Pass `HOST_API` from the netstead you develop with. |
| `actions` | A tuple of `ActionSpec(model, handler)`. |
| `settings_model` | A pydantic model that validates the `[plugins.<id>]` table. Read the result as `host.settings`. |
| `state(host)` | Returns a JSON-safe dict merged into `/api/state` under `plugins.<id>`. Keep it cheap, because it runs on every state push. |
| `router(host)` | Returns a FastAPI `APIRouter`, mounted at `/api/plugins/<id>`. Called once, at install. |
| `static_dir` / `frontend` | A directory served at `/plugins/<id>/`, and the ES module in it the browser loads (default `main.js`). |
| `on_load(host)` | Runs once at install, before the router is built and the Actions register. If it raises, the plugin isn't installed, but whatever it did before raising (files written, threads started) is not undone. The same holds if the router or static dir then fails. |

The factory runs once per session, so state kept in its closure belongs to that session.

### Settings

Settings come from the same layers as every other setting (user config, project `netstead.toml`,
env, session):

```toml
# ./netstead.toml
[plugins.hello]
prefix = "Howdy"
```

Bad values mark the plugin `error` at startup. Through the Workbench's settings API they are refused
before anything is written. **Credentials are never settings.** A secret-named key (`api_key`,
`token`, `password` and so on), a value shaped like an API key, or a URL carrying a password under
`[plugins.<id>]` is refused in every layer, and the settings fail to load. Read keys from the OS
keyring or the environment in your own code instead.

### Routes and front end

<!-- doctest: skip -->
```python
from fastapi import APIRouter


def router(host: Host) -> APIRouter:
    api = APIRouter()

    @api.get("/count")  # served at GET /api/plugins/hello/count
    def count() -> dict:
        return {"greeted": greeted["count"]}

    return api
```

`static_dir` is served at `/plugins/<id>/`. Requests can't escape it (`..` and its encoded forms
get a 404). The browser loader that imports `frontend` and calls its `activate(wb)` arrives with the
Workbench's plugin front end. Until then the file is only served. `router(host)` is called once,
when the session installs the plugin. If it raises or returns something other than an `APIRouter`,
or `static_dir` isn't a directory, the plugin isn't installed: it is marked `error`, none of its
Actions register, its state isn't merged, and nothing of it is mounted.

## The `Host` reference

A plugin never sees the `Session`. Every handler, `router`, `state` and `on_load` gets a
`netstead.workbench.plugins.Host` bound to that plugin's id.

| Member | What it gives you |
|---|---|
| `host.plugin_id` | This plugin's id. |
| `host.settings` | The validated `[plugins.<id>]` model, or `None` if there is no `settings_model`. Re-read on each access, so it reflects setting changes. |
| `host.active` | The active network's id, or `None`. |
| `host.selection` | A copy of the shared selection payload (the same dict `/api/state` carries), or `None`. |
| `host.network(net_id=None)` | The network handle (default: the active one). Read it, but change it only through `mutate`. |
| `host.mutate(net_id, edits, note=...)` | Applies `corral.editing.Edit`s to a network's roadway **all or nothing**. The edits run on a draft, so a failing edit leaves the network (and its caches) untouched and re-raises. On success it bumps the version, appends `"<id>: <note>"` to the lineage and pushes state. It returns the `EditResult`s (the rollback data). Inside a handler, the change is undone if the handler fails. Outside one (a job, a route), it is recorded as a non-replayable `<id>.mutate` history entry. |
| `host.derive(net_id, label=..., note=...)` | Registers a **copy-on-write** copy of a network (a preview or scenario) and returns its id. Edits to the copy never touch the base. The copy records `derived_from` and inherits the lineage. Inside a handler that fails, the copy is unregistered again. |
| `host.has_action(type)` | Whether core or any loaded plugin registered that Action type. Use it for soft cross-plugin dependencies. |
| `host.dispatch(action)` | Dispatches any Action (a model or a dict). Called from a handler, it is recorded in history as nested in that handler's Action (`parent_seq`): "copy as Python" shows it as a comment, since replaying the outer Action runs it again, and it is undone if the outer handler fails. Job Actions (`open_network`, `build_network`) can't be dispatched from a handler, because waiting for them would deadlock. Use `host.submit_job` for slow work instead. |
| `host.publish(name, payload)` | Sends the browser a `{"type": "plugin", "plugin": <id>, "name": ..., "payload": ...}` event over the session's event stream. |
| `host.submit_job(label, fn)` | Runs `fn(ctx)` on a background job, with progress and cancel in the jobs panel, and returns the job id. `mutate` and `derive` are safe to call from it. |
| `host.writable(path)` | Resolves a path for writing inside `io.allowed_roots`. Raises `PathNotAllowed` outside it. |

A preview, following "nothing mutates silently":

<!-- doctest: skip -->
```python
from corral.editing import Edit


def widen(host: Host, action: Widen) -> str:
    preview = host.derive(None, label="Preview: widen", note="preview")
    payload = {"predicate": lambda t: t.link_id == action.link_id, "set": {"lanes": action.lanes}}
    host.mutate(preview, [Edit(op="update_rows", table="link", payload=payload)], note=f"widen {action.link_id}")
    return preview  # the base network is untouched
```

### Exposing Actions to the NL assistant

Build the assistant's tool vocabulary from the **session's** registry, `session.actions.json_schema()`.
It holds the core Actions plus every loaded plugin's. The module-level
`netstead.workbench.actions.action_json_schema` covers core Actions only, so a tool list built from
it would silently leave out every plugin.

## Test a plugin

There is no special harness. Build a `Session` with your plugin passed in explicitly, which skips
entry-point discovery, and drive it:

<!-- doctest: skip -->
```python
import pytest
from netstead.select.parse import StubParser
from netstead.workbench import Session

from netstead_hello import Greet, plugin


@pytest.fixture
def session(tmp_path):
    environ = {"NETSTEAD_CONFIG_DIR": str(tmp_path / "user")}  # never read your real user config
    return Session(plugins=[plugin()], project_dir=tmp_path, environ=environ, parser=StubParser())


def test_greet(session):
    assert session.dispatch(Greet(name="Ada")) == "Hello, Ada!"
    assert session.dispatch({"type": "hello.greet", "name": "Bo"}) == "Hello, Bo!"  # as the browser sends it
    assert session.state()["plugins"]["hello"] == {"greeted": 2}
    assert session.history[-1].imports == "from netstead_hello import Greet"
    assert next(s for s in session.plugin_status if s.id == "hello").state == "loaded"
```

Pass `overrides={"plugins.hello.prefix": "Howdy"}` to test settings. For the HTTP side, wrap the
session in `TestClient(build_app(session))` from `netstead.workbench`.

## Startup outcomes

Every plugin seen at startup gets a `netstead.workbench.plugins.PluginStatus`, listed by
`GET /api/plugins` together with the host's `host_api`:

| State | Meaning |
|---|---|
| `loaded` | Installed. Its Actions dispatch, and its routes and static files are mounted. `frontend` is the module URL (`/plugins/<id>/main.js`). |
| `disabled` | Listed in `[app] disabled_plugins`. It is skipped before its package is even imported. |
| `incompatible` | Its `requires_api` doesn't match this netstead's `HOST_API`. |
| `error` | Something failed: importing the entry point, the startup checks (id, namespacing, duplicates, class names), the settings, `on_load`, the router, or the static dir. `error` holds the reason. |

To turn a plugin off without uninstalling it:

```toml
[app]
disabled_plugins = ["hello"]
```

`app.disabled_plugins` is read at startup, so restart `netstead app` after changing it. Dispatching
an Action of a plugin that isn't loaded fails like any unknown Action type (HTTP 422).

## Versioning

`HOST_API` (in `netstead.workbench.plugins`) is a `major.minor` string. A plugin's `requires_api`
is compatible when the major versions are equal and the host's minor is at least the plugin's. A
plugin written against `1.0` runs on `1.3`, but not on `2.0`, and a `1.3` plugin doesn't run on `1.0`.
A minor bump only adds to the API and a major bump breaks it.

**The plugin API is provisional until netstead v1.0.** Until then it may change without a major
bump. Pin the netstead versions you support in your package's dependencies, and check the changelog
when you upgrade.
