# Workbench P0 (Foundations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-network `gmnspy viz` server with `gmnspy app`, the GMNSpy Workbench. It has a layered settings system and one live `Session`. Every state change goes through a typed Action bus that records history, which can be replayed as Python. State is pushed to a modular, no-build browser front end over SSE.

**Architecture:**
- `gmnspy.config` loads `Settings` with this precedence (lowest first): defaults, user TOML, project TOML, env, session overrides.
- `gmnspy.workbench` holds:
  - a `NetworkRegistry` of `NetworkHandle` bundles (a roadway component now, transit reserved), with caches keyed by version;
  - an `EventBus` that fans events out to SSE;
  - pydantic `Action` schemas;
  - a `Session` whose `dispatch` is the only way state changes.
- FastAPI routes expose `/api/state`, `/api/actions`, `/api/events`, `/api/history` and `/api/settings`, plus per-network data under `/api/n/{net_id}/{component}/...`.
- The front end is the existing viz viewer split into native ES modules around a tiny store.

**Tech Stack:**
- Python 3.11 (`tomllib`), pydantic v2, FastAPI 0.136 / Starlette 1.0 (`StaticFiles`, `StreamingResponse`), uvicorn.
- Browser: MapLibre GL 4.7.1 + deck.gl 9.0.38 from the CDN (unchanged), plain ES modules.
- Tests: pytest + `fastapi.testclient`, and `node --check` for JS syntax.

**Spec:** [2026-10-02-gmnspy-workbench-design.md](2026-10-02-gmnspy-workbench-design.md) (phase P0).

**Branch:** `docs/workbench-design` (off `origin/refactor/v1.0`). Implementation goes on a new branch, `feat/workbench-p0`, cut from it.

**Conventions:**
- Run commands from the repo root.
- Run tests with `uv run --all-extras pytest <path> -q`.
- Lint with `uv run ruff check packages/gmnspy && uv run ruff format --check packages/gmnspy`.
- Ruff enforces Google-style docstrings (`D`) on every public module-level function, class and method outside `tests/` and `__init__.py`. Each code block below already has them.
- Line length is 120.

---

## Scope notes (P0 vs later)

- **In P0:**
  - settings model, load and save;
  - the session, registry, event bus and actions: `open_network`, `close_network`, `set_active_network`, `select`, `clear_selection`, `style`, `navigate`, `set_setting`;
  - per-network data routes;
  - the modular front end at parity with `gmnspy viz`, plus a network switcher, open-by-path and a history strip with "copy as Python";
  - `gmnspy app`, with `viz` and `select-serve` becoming aliases;
  - packaging;
  - a docs page.
- **Deferred:**
  - background jobs (P1, with Build);
  - the Settings UI form (P1; P0 serves `/api/settings` and the `set_setting` action);
  - wiring `Settings` into the OSM/Overture builders and the validation rules (done in the phase that first calls each one: P1 and P2);
  - undo (P2, on `NetworkChange`).
- **Transit:** the registry bundle has a `transit` slot. Routes take a `{component}` segment, and `Select` has a `component` field. Transit requests return 501, or raise `NotSupportedYet`.
- **Package name:** `gmnspy.workbench`, not `gmnspy.app`. That keeps the name `gmnspy.app(net)` free for the P4 notebook handle.

## File structure

| Path | Responsibility |
|---|---|
| `packages/gmnspy/gmnspy/config.py` (new) | `Settings` model, layered `load_settings`, `save_setting`, `get_value`, TOML writer |
| `packages/gmnspy/gmnspy/viz/styling.py` (new) | Moved from `viz/server.py`: `json_scalar`, `styleable_columns`, `property_payload`, `basemap_style` |
| `packages/gmnspy/gmnspy/viz/tables.py` (modify) | Gains `parse_ids`, moved from `viz/server.py` |
| `packages/gmnspy/gmnspy/viz/server.py` (modify) | Imports the moved helpers; marked deprecated |
| `packages/gmnspy/gmnspy/workbench/__init__.py` (new) | Public surface: `Session`, `ActionError`, `build_app`, `serve` |
| `packages/gmnspy/gmnspy/workbench/registry.py` (new) | `NetworkHandle` bundle and `NetworkRegistry` |
| `packages/gmnspy/gmnspy/workbench/events.py` (new) | Thread-safe `EventBus`, `sse_format` |
| `packages/gmnspy/gmnspy/workbench/actions.py` (new) | Action schemas, `parse_action`, `to_python` |
| `packages/gmnspy/gmnspy/workbench/selection.py` (new) | `SelectionResult` → JSON payload (anchors, fragment) |
| `packages/gmnspy/gmnspy/workbench/session.py` (new) | `Session`: dispatch, handlers, history, state |
| `packages/gmnspy/gmnspy/workbench/server.py` (new) | `build_app(session)`: static files, index, routers |
| `packages/gmnspy/gmnspy/workbench/routes/__init__.py` (new) | Empty package marker |
| `packages/gmnspy/gmnspy/workbench/routes/core.py` (new) | `/api/state`, `/api/config`, `/api/settings`, `/api/history`, `/api/actions`, `/api/events` |
| `packages/gmnspy/gmnspy/workbench/routes/network.py` (new) | `/api/n/{net_id}/{component}/...` data routes |
| `packages/gmnspy/gmnspy/workbench/static/index.html`, `app.css`, `js/*.js` (new) | Front end |
| `packages/gmnspy/gmnspy/cli/commands/workbench.py` (new) | `gmnspy app` and `run_workbench` |
| `packages/gmnspy/gmnspy/cli/commands/viz.py`, `select.py`, `cli/app.py` (modify) | Aliases and registration |
| `packages/gmnspy/pyproject.toml` (modify) | Wheel includes the static assets |
| `packages/gmnspy/docs/cookbook/workbench.md`, `mkdocs.yml`, `docs/cookbook/index.md` (new/modify) | User docs |
| `packages/gmnspy/tests/conftest.py` (modify) | `rdu_source` and `isolated_env` fixtures |
| `packages/gmnspy/tests/test_config.py`, `test_viz_styling.py`, `test_workbench_*.py`, `test_cli_workbench.py` (new) | Tests |

---

### Task 0: Branch and shared test fixtures

**Files:**
- Modify: `packages/gmnspy/tests/conftest.py`

- [ ] **Step 1: Cut the branch**

```bash
git checkout -b feat/workbench-p0
```

- [ ] **Step 2: Add fixtures to the end of `packages/gmnspy/tests/conftest.py`**

At the top of the file, add `from importlib import resources` to the imports, next to `import hashlib`. Then append:

```python
@pytest.fixture(scope="session")
def rdu_source() -> str:
    """Path to the committed RDU I-40 parquet fixture network (read-only)."""
    return str(resources.files("gmnspy.fixtures.rdu_i40").joinpath("parquet"))


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, str]:
    """An environ whose gmnspy user-config dir lives under ``tmp_path``, never the real ``~/.config``."""
    return {"GMNSPY_CONFIG_DIR": str(tmp_path / "user")}
```

- [ ] **Step 3: Confirm the suite still collects**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_viz_server.py -q`
Expected: `26 passed` (or the current count, all passing).

- [ ] **Step 4: Commit**

```bash
git add packages/gmnspy/tests/conftest.py
git commit -m "test(gmnspy): shared rdu_source + isolated_env fixtures for workbench tests"
```

---

### Task 1: `Settings` model and layered loader

**Files:**
- Create: `packages/gmnspy/gmnspy/config.py`
- Test: `packages/gmnspy/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for gmnspy.config — layered settings."""

import sys
from pathlib import Path

import pytest
from gmnspy.config import Settings, SettingsError, get_value, load_settings, user_config_path
from gmnspy.spec import DEFAULT_SPEC


def _write_user(env: dict[str, str], text: str) -> Path:
    path = Path(env["GMNSPY_CONFIG_DIR"]) / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_defaults_when_no_files(tmp_path, isolated_env):
    loaded = load_settings(project_dir=tmp_path, environ=isolated_env)
    assert loaded.settings.select.provider == "stub"
    assert loaded.settings.io.spec_version == DEFAULT_SPEC
    assert loaded.settings.app.port == 8850
    assert loaded.sources["select.provider"] == "default"


def test_precedence_user_project_env_session(tmp_path, isolated_env):
    _write_user(isolated_env, '[app]\nport = 9001\nhost = "0.0.0.0"\n[viz]\nbasemap = "esri"\n')
    (tmp_path / "gmnspy.toml").write_text("[app]\nport = 9002\n")
    env = {**isolated_env, "GMNSPY_SELECT__PROVIDER": "claude", "GMNSPY_APP__PORT": "9003"}
    loaded = load_settings(project_dir=tmp_path, environ=env, overrides={"app.port": 9004})
    s = loaded.settings
    assert (s.viz.basemap, s.app.host, s.select.provider, s.app.port) == ("esri", "0.0.0.0", "claude", 9004)
    assert loaded.sources["viz.basemap"] == "user"
    assert loaded.sources["select.provider"] == "env"
    assert loaded.sources["app.port"] == "session"


def test_project_beats_user(tmp_path, isolated_env):
    _write_user(isolated_env, "[app]\nport = 9001\n")
    (tmp_path / "gmnspy.toml").write_text("[app]\nport = 9002\n")
    loaded = load_settings(project_dir=tmp_path, environ=isolated_env)
    assert loaded.settings.app.port == 9002
    assert loaded.sources["app.port"] == "project"


def test_env_json_list_and_unrelated_vars_ignored(tmp_path, isolated_env):
    env = {**isolated_env, "GMNSPY_IO__ALLOWED_ROOTS": '["/data", "/tmp"]', "GMNSPY_AUTO_INDEX_THRESHOLD": "5"}
    loaded = load_settings(project_dir=tmp_path, environ=env)
    assert loaded.settings.io.allowed_roots == ["/data", "/tmp"]


def test_rule_settings_nest_under_validation(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text(
        '[validation.rules.dangling-node]\nenabled = false\nseverity_override = "warning"\n'
    )
    rules = load_settings(project_dir=tmp_path, environ=isolated_env).settings.validation.rules
    assert rules["dangling-node"].enabled is False
    assert rules["dangling-node"].severity_override == "warning"


def test_unknown_key_in_file_rejected(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text("[select]\nbogus = 1\n")
    with pytest.raises(SettingsError, match="project"):
        load_settings(project_dir=tmp_path, environ=isolated_env)


def test_invalid_toml_names_the_file(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text("[app\n")
    with pytest.raises(SettingsError, match="gmnspy.toml"):
        load_settings(project_dir=tmp_path, environ=isolated_env)


def test_bad_env_json_rejected(tmp_path, isolated_env):
    with pytest.raises(SettingsError, match="GMNSPY_IO__ALLOWED_ROOTS"):
        load_settings(project_dir=tmp_path, environ={**isolated_env, "GMNSPY_IO__ALLOWED_ROOTS": "[oops"})


def test_user_config_path_override():
    assert user_config_path({"GMNSPY_CONFIG_DIR": "/cfg"}) == Path("/cfg/config.toml")


@pytest.mark.skipif(sys.platform == "win32", reason="XDG applies off Windows only")
def test_user_config_path_xdg():
    assert user_config_path({"XDG_CONFIG_HOME": "/x"}) == Path("/x/gmnspy/config.toml")


def test_get_value():
    assert get_value(Settings(), "app.port") == 8850
    with pytest.raises(SettingsError, match="unknown setting"):
        get_value(Settings(), "app.nope")
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_config.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'gmnspy.config'`.

- [ ] **Step 3: Implement `packages/gmnspy/gmnspy/config.py`**

```python
"""Layered, persisted gmnspy settings.

Precedence, lowest to highest: model defaults < user file
(``~/.config/gmnspy/config.toml``) < project file (``./gmnspy.toml``) <
``GMNSPY_<SECTION>__<FIELD>`` env vars < session overrides (CLI flags, the
workbench's ``set_setting`` action with ``scope="session"``).

Secrets never live here: credentials stay in env/keyring/netrc via
:mod:`datagrove.io.credentials`; ``credentials.keyring_hosts`` only names hosts.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gmnspy.spec import DEFAULT_SPEC

__all__ = [
    "LoadedSettings",
    "Settings",
    "SettingsError",
    "dumps_toml",
    "get_value",
    "load_settings",
    "project_config_path",
    "save_setting",
    "user_config_path",
]

Scope = Literal["user", "project"]
ENV_PREFIX = "GMNSPY_"
PROJECT_FILE = "gmnspy.toml"


class SettingsError(ValueError):
    """A settings file, env var, or override failed to parse or validate."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IOSettings(_Section):
    """Reading/writing networks."""

    spec_version: str = DEFAULT_SPEC
    default_format: Literal["csv", "parquet", "duckdb", "zip"] = "parquet"
    allowed_roots: list[str] = Field(default_factory=list)


class EngineSettings(_Section):
    """DuckDB engine tuning (``None`` = DuckDB's own default)."""

    threads: int | None = None
    memory_limit: str | None = None


class OSMSettings(_Section):
    """OpenStreetMap builds (``None`` = the builder's built-in default)."""

    endpoint: str | None = None
    user_agent: str | None = None
    timeout: int = 180
    retries: int = 3
    mapping_path: str | None = None


class OvertureSettings(_Section):
    """Overture builds (``None`` = the builder's built-in default)."""

    release: str | None = None
    data_root: str | None = None


class RuleSettings(_Section):
    """One quality rule's config (mirrors :class:`datagrove.quality.base.RuleConfig`)."""

    enabled: bool = True
    severity_override: str | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)


class ValidationSettings(_Section):
    """Per-rule quality configuration, keyed by rule name."""

    rules: dict[str, RuleSettings] = Field(default_factory=dict)


class SelectSettings(_Section):
    """Natural-language selection parser."""

    provider: Literal["stub", "claude"] = "stub"
    model: str = "claude-sonnet-5"


class VizSettings(_Section):
    """Map rendering."""

    basemap: Literal["positron", "esri"] = "positron"


class AppSettings(_Section):
    """The workbench web server."""

    host: str = "127.0.0.1"
    port: int = 8850
    console: bool = False


class CredentialSettings(_Section):
    """Names of hosts whose secrets live in keyring. Never the secrets themselves."""

    keyring_hosts: list[str] = Field(default_factory=list)


class Settings(_Section):
    """All user-tunable gmnspy settings."""

    io: IOSettings = Field(default_factory=IOSettings)
    engine: EngineSettings = Field(default_factory=EngineSettings)
    osm: OSMSettings = Field(default_factory=OSMSettings)
    overture: OvertureSettings = Field(default_factory=OvertureSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    select: SelectSettings = Field(default_factory=SelectSettings)
    viz: VizSettings = Field(default_factory=VizSettings)
    app: AppSettings = Field(default_factory=AppSettings)
    credentials: CredentialSettings = Field(default_factory=CredentialSettings)


@dataclass(frozen=True)
class LoadedSettings:
    """Resolved settings plus where each leaf value came from."""

    settings: Settings
    sources: dict[str, str]
    user_path: Path
    project_path: Path


def user_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the user config file path (``GMNSPY_CONFIG_DIR`` overrides the platform default)."""
    env = os.environ if environ is None else environ
    if override := env.get("GMNSPY_CONFIG_DIR"):
        return Path(override) / "config.toml"
    if sys.platform == "win32" and (appdata := env.get("APPDATA")):
        return Path(appdata) / "gmnspy" / "config.toml"
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "gmnspy" / "config.toml"


def project_config_path(project_dir: str | Path | None = None) -> Path:
    """Return the project config file path (``gmnspy.toml`` in ``project_dir``, default cwd)."""
    return Path(project_dir or Path.cwd()) / PROJECT_FILE


def get_value(settings: Settings, key: str) -> Any:
    """Return the JSON-mode value at dotted ``key`` (e.g. ``"app.port"``)."""
    node: Any = settings.model_dump(mode="json")
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise SettingsError(f"unknown setting {key!r}")
        node = node[part]
    return node


def load_settings(
    *,
    project_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> LoadedSettings:
    """Resolve settings from every layer; ``overrides`` maps dotted keys to session values."""
    env = os.environ if environ is None else environ
    user_path, project_path = user_config_path(env), project_config_path(project_dir)
    session_layer: dict[str, Any] = {}
    for key, value in (overrides or {}).items():
        _set_dotted(session_layer, key, value)
    layers = (
        ("user", _read_toml(user_path)),
        ("project", _read_toml(project_path)),
        ("env", _env_layer(env)),
        ("session", session_layer),
    )
    merged: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for name, layer in layers:
        _validate(layer, f"{name} layer")
        merged = _merge(merged, layer)
        sources.update(dict.fromkeys(_leaves(layer), name))
    settings = _validate(merged, "merged layers")
    for key in _leaves(settings.model_dump(mode="json")):
        sources.setdefault(key, "default")
    return LoadedSettings(settings=settings, sources=sources, user_path=user_path, project_path=project_path)


def save_setting(
    key: str,
    value: Any,
    *,
    scope: Scope,
    project_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Persist dotted ``key`` into the ``scope`` file; ``value=None`` removes it (back to default)."""
    env = os.environ if environ is None else environ
    path = user_config_path(env) if scope == "user" else project_config_path(project_dir)
    data = _read_toml(path)
    _set_dotted(data, key, value)
    validated = _validate(data, f"{scope} file {path}")
    if value is not None:
        _set_dotted(data, key, get_value(validated, key))  # store the coerced value ("9100" -> 9100)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_toml(data), encoding="utf-8")
    return path


def dumps_toml(data: Mapping[str, Any]) -> str:
    """Serialise nested dicts of scalars/lists to TOML: the subset settings files use."""
    lines: list[str] = []
    _emit_table(lines, data, ())
    return "\n".join(lines).strip() + "\n"


# --------------------------------------------------------------------------- helpers

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path}: {exc}") from exc


def _validate(data: Mapping[str, Any], origin: str) -> Settings:
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise SettingsError(f"invalid settings ({origin}): {exc}") from exc


def _env_layer(environ: Mapping[str, str]) -> dict[str, Any]:
    layer: dict[str, Any] = {}
    for name, raw in environ.items():
        if not name.startswith(ENV_PREFIX) or "__" not in name:
            continue
        value: Any = raw
        if raw.lstrip().startswith(("[", "{")):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SettingsError(f"{name}: invalid JSON value: {exc}") from exc
        _set_dotted(layer, name[len(ENV_PREFIX) :].lower().replace("__", "."), value)
    return layer


def _set_dotted(data: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = node[part] = {}
        node = child
    if value is None:
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = value


def _merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _leaves(data: Mapping[str, Any], prefix: str = "") -> Iterator[str]:
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            yield from _leaves(value, dotted + ".")
        else:
            yield dotted


def _emit_table(lines: list[str], table: Mapping[str, Any], path: tuple[str, ...]) -> None:
    scalars = [(k, v) for k, v in table.items() if not isinstance(v, dict) and v is not None]
    tables = [(k, v) for k, v in table.items() if isinstance(v, dict)]
    if path and (scalars or not tables):
        lines.extend(["", "[" + ".".join(_toml_key(p) for p in path) + "]"])
    lines.extend(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in scalars)
    for key, value in tables:
        _emit_table(lines, value, (*path, key))


def _toml_key(key: str) -> str:
    return key if _BARE_KEY.match(key) else json.dumps(key)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)  # JSON string escapes are valid TOML basic-string escapes
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise SettingsError(f"cannot write {type(value).__name__} to TOML: {value!r}")
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_config.py -q`
Expected: `11 passed` (10 on Windows).

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/gmnspy/config.py packages/gmnspy/tests/test_config.py
git commit -m "feat(gmnspy): layered Settings (defaults<user<project<env<session) with source tracking"
```

---

### Task 2: Persisting settings (`save_setting`, `dumps_toml`)

**Files:**
- Modify: `packages/gmnspy/tests/test_config.py` (append)
- (Implementation already in `config.py` from Task 1; this task proves it.)

- [ ] **Step 1: Append the tests**

First, merge the new imports into the top-of-file import block (ruff E402 rejects mid-file imports). Add `import tomllib` to the stdlib group, and add `dumps_toml, save_setting` to the existing `from gmnspy.config import ...` line. Then append:

```python

def test_save_setting_round_trips_and_coerces(tmp_path, isolated_env):
    path = save_setting("app.port", "9100", scope="user", environ=isolated_env)
    assert path == Path(isolated_env["GMNSPY_CONFIG_DIR"]) / "config.toml"
    assert "port = 9100" in path.read_text()
    assert load_settings(project_dir=tmp_path, environ=isolated_env).settings.app.port == 9100


def test_save_setting_project_scope_keeps_other_keys(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text('[viz]\nbasemap = "esri"\n')
    save_setting("select.provider", "claude", scope="project", project_dir=tmp_path, environ=isolated_env)
    s = load_settings(project_dir=tmp_path, environ=isolated_env).settings
    assert (s.viz.basemap, s.select.provider) == ("esri", "claude")


def test_save_setting_none_resets_to_default(tmp_path, isolated_env):
    save_setting("app.port", 9100, scope="user", environ=isolated_env)
    save_setting("app.port", None, scope="user", environ=isolated_env)
    loaded = load_settings(project_dir=tmp_path, environ=isolated_env)
    assert loaded.settings.app.port == 8850 and loaded.sources["app.port"] == "default"


def test_save_setting_rejects_unknown_key_without_writing(tmp_path, isolated_env):
    with pytest.raises(SettingsError):
        save_setting("select.bogus", 1, scope="user", environ=isolated_env)
    assert not (Path(isolated_env["GMNSPY_CONFIG_DIR"]) / "config.toml").exists()


def test_dumps_toml_round_trips_nested_tables_and_quoting():
    data = {
        "io": {"allowed_roots": ["/a", 'b "q"'], "spec_version": "0.97"},
        "validation": {"rules": {"dangling-node": {"enabled": False, "thresholds": {"max": 2.5}}, "my rule": {}}},
    }
    assert tomllib.loads(dumps_toml(data)) == data
```

- [ ] **Step 2: Run them**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_config.py -q`
Expected: `16 passed`. If `test_dumps_toml_round_trips…` fails on the empty `"my rule": {}` table, check that `_emit_table` writes a header when a table has neither scalars nor subtables (the `scalars or not tables` branch).

- [ ] **Step 3: Commit**

```bash
git add packages/gmnspy/tests/test_config.py
git commit -m "test(gmnspy): settings persistence round-trip, coercion, reset, rejection"
```

---

### Task 3: Extract the viz styling helpers so the workbench can reuse them

**Files:**
- Create: `packages/gmnspy/gmnspy/viz/styling.py`
- Modify: `packages/gmnspy/gmnspy/viz/tables.py` (add `parse_ids`)
- Modify: `packages/gmnspy/gmnspy/viz/server.py` (import the moved helpers; deprecation note)
- Test: `packages/gmnspy/tests/test_viz_styling.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for gmnspy.viz.styling (shared by viz and the workbench)."""

import pandas as pd
from gmnspy.viz.styling import basemap_style, json_scalar, property_payload, styleable_columns
from gmnspy.viz.tables import parse_ids


def test_styleable_columns_classifies_and_skips_ids():
    links = pd.DataFrame({"link_id": [1, 2], "lanes": [1, 2], "facility_type": ["a", "b"], "geometry": ["x", "y"]})
    assert styleable_columns(links) == [
        {"name": "lanes", "kind": "continuous"},
        {"name": "facility_type", "kind": "categorical"},
    ]


def test_property_payload_continuous_and_unknown():
    links = pd.DataFrame({"lanes": [1, None, 3]})
    p = property_payload(links, "lanes")
    assert p["kind"] == "continuous" and p["values"][1] is None and (p["min"], p["max"]) == (1, 3)
    assert property_payload(links, "nope") is None


def test_json_scalar_handles_nan_and_numpy():
    assert json_scalar(float("nan")) is None
    assert json_scalar(pd.Series([7]).iloc[0]) == 7
    assert type(json_scalar(pd.Series([7]).iloc[0])) is int


def test_basemap_style_is_keyless():
    assert "openfreemap" in basemap_style("positron")
    assert "arcgisonline.com" in basemap_style("esri")["sources"]["basemap"]["tiles"][0]


def test_parse_ids():
    assert parse_ids("1, 2,x,") == [1, 2, "x"]
    assert parse_ids("") is None and parse_ids(None) is None
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_viz_styling.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'gmnspy.viz.styling'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/viz/styling.py`**

These are the helpers from `viz/server.py`, renamed public:

```python
"""Map-styling helpers shared by ``gmnspy viz`` and the workbench.

Pure functions over pandas link frames: which columns can drive color-by, the
per-link values for one property, JSON-safe scalars, and the keyless basemap
style. No FastAPI imports, so the workbench and tests use them directly.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

__all__ = ["basemap_style", "json_scalar", "property_payload", "styleable_columns"]

#: Columns never offered as a color-by property (geometry/opaque or identity).
_SKIP_STYLE_COLS = {"geometry", "osm_node_ids", "osm_way_id", "link_id", "from_node_id", "to_node_id"}
_MAX_CATEGORIES = 25

_ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas"
#: Free, no-key vector Positron (OpenMapTiles/OSM data).
_POSITRON_URL = "https://tiles.openfreemap.org/styles/positron"


def json_scalar(v: Any) -> Any:
    """Return ``v`` as a JSON-safe Python scalar (NaN/NA → ``None``, numpy → builtin)."""
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return getattr(v, "item", lambda: v)()


def styleable_columns(links: pd.DataFrame) -> list[dict]:
    """List columns usable for color-by, classified continuous vs categorical."""
    out = []
    for c in links.columns:
        if c in _SKIP_STYLE_COLS:
            continue
        s = links[c]
        if pd.api.types.is_numeric_dtype(s):
            out.append({"name": c, "kind": "continuous"})
        elif s.nunique(dropna=True) <= _MAX_CATEGORIES:  # skip high-cardinality (e.g. name)
            out.append({"name": c, "kind": "categorical"})
    return out


def property_payload(links: pd.DataFrame, name: str) -> dict | None:
    """Index-aligned values for one color-by property, or ``None`` if the column is absent."""
    if name not in links.columns:
        return None
    s = links[name]
    values = [json_scalar(v) for v in s]
    if pd.api.types.is_numeric_dtype(s):
        nn = [v for v in values if v is not None]
        return {
            "name": name,
            "kind": "continuous",
            "values": values,
            "min": min(nn) if nn else 0,
            "max": max(nn) if nn else 1,
        }
    cats = sorted({str(v) for v in values if v is not None})
    return {
        "name": name,
        "kind": "categorical",
        "values": [None if v is None else str(v) for v in values],
        "categories": cats,
    }


def basemap_style(basemap: str = "positron") -> str | dict:
    """Return a keyless MapLibre style: ``"positron"`` (style URL, default) or ``"esri"`` (raster, ≤z16)."""
    if basemap == "esri":
        return {
            "version": 8,
            "sources": {
                "basemap": {
                    "type": "raster",
                    "tileSize": 256,
                    "maxzoom": 16,
                    "attribution": "Esri, © OpenStreetMap contributors",
                    "tiles": [f"{_ESRI}/World_Light_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}"],
                },
                "labels": {
                    "type": "raster",
                    "tileSize": 256,
                    "maxzoom": 16,
                    "tiles": [f"{_ESRI}/World_Light_Gray_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}"],
                },
            },
            "layers": [
                {"id": "basemap", "type": "raster", "source": "basemap"},
                {"id": "labels", "type": "raster", "source": "labels"},
            ],
        }
    return _POSITRON_URL
```

- [ ] **Step 4: Add `parse_ids` to `packages/gmnspy/gmnspy/viz/tables.py`**

Add `"parse_ids"` to `__all__`, and add this after `primary_key`:

```python
def parse_ids(ids: str | None) -> list | None:
    """Parse a comma-separated ``ids`` querystring into ints (fallback: strings); ``None`` when empty."""
    if not ids:
        return None
    out: list = []
    for tok in ids.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            out.append(tok)
    return out or None
```

- [ ] **Step 5: Point `viz/server.py` at the moved helpers**

In `packages/gmnspy/gmnspy/viz/server.py`, delete these definitions:
- `_parse_ids`, `_json_scalar`, `_SKIP_STYLE_COLS`, `_MAX_CATEGORIES`, `_styleable_columns`, `_property_payload`
- `_ESRI`, `_POSITRON_URL`, `_basemap_style`

Keep `_page` and `_py`. Replace the `from .tables import ...` line with:

```python
from .styling import basemap_style as _basemap_style
from .styling import json_scalar as _json_scalar
from .styling import property_payload as _property_payload
from .styling import styleable_columns as _styleable_columns
from .tables import FilterError, columns_of, page_table, primary_key, table_list_entry, table_schema
from .tables import parse_ids as _parse_ids
```

Then append this paragraph to the module docstring:

```
Deprecated: ``gmnspy viz`` now launches the workbench (:mod:`gmnspy.workbench`);
this single-network app remains only for existing callers and is removed in P1.
```

- [ ] **Step 6: Run the new and existing viz tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_viz_styling.py packages/gmnspy/tests/test_viz_server.py packages/gmnspy/tests/test_viz_tables.py -q`
Expected: all pass.

- [ ] **Step 7: Lint, then commit**

```bash
uv run ruff check packages/gmnspy/gmnspy/viz && uv run ruff format packages/gmnspy/gmnspy/viz packages/gmnspy/tests/test_viz_styling.py
git add packages/gmnspy/gmnspy/viz packages/gmnspy/tests/test_viz_styling.py
git commit -m "refactor(viz): extract styling helpers + parse_ids for reuse by the workbench"
```

---

### Task 4: `NetworkHandle` bundle and `NetworkRegistry`

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/__init__.py` (temporary minimal; finished in Task 8)
- Create: `packages/gmnspy/gmnspy/workbench/registry.py`
- Test: `packages/gmnspy/tests/test_workbench_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the workbench network registry."""

import pytest
from gmnspy import Network
from gmnspy.workbench.registry import NetworkRegistry, default_label


@pytest.fixture(scope="module")
def net(rdu_source):
    return Network.from_source(rdu_source)


def test_default_label_skips_generic_dir_names():
    assert default_label("/x/rdu_i40/parquet") == "rdu_i40"
    assert default_label("/x/leavenworth.csv.zip") == "leavenworth.csv"
    assert default_label("") == "network"


def test_add_assigns_unique_slug_ids(net, rdu_source):
    reg = NetworkRegistry()
    a = reg.add(net, source=rdu_source)
    b = reg.add(net, source=rdu_source)
    assert (a.id, b.id) == ("rdu-i40", "rdu-i40-2")
    assert (a.label, b.label) == ("rdu_i40", "rdu-i40-2")
    assert reg.ids() == ["rdu-i40", "rdu-i40-2"]


def test_get_unknown_raises_keyerror_with_message():
    with pytest.raises(KeyError, match="unknown network 'nope'"):
        NetworkRegistry().get("nope")


def test_handle_frames_summary_and_transit_slot(net, rdu_source):
    h = NetworkRegistry().add(net, source=rdu_source, label="RDU")
    assert len(h.links_df()) == 178 and len(h.nodes_df()) == 143
    assert set(h.tables()) >= {"link", "node"}
    s = h.summary()
    assert s["label"] == "RDU" and s["components"] == ["roadway"] and s["version"] == 0 and s["lineage"] == []
    assert h.transit is None


def test_cache_is_keyed_by_version(net, rdu_source):
    h = NetworkRegistry().add(net, source=rdu_source)
    calls = []
    h.cached("k", lambda: calls.append(1) or "v1")
    h.cached("k", lambda: calls.append(1) or "v1")
    assert calls == [1]
    assert h.bump() == 1
    assert h.cached("k", lambda: "v2") == "v2"


def test_remove(net, rdu_source):
    reg = NetworkRegistry()
    h = reg.add(net, source=rdu_source)
    reg.remove(h.id)
    assert len(reg) == 0
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_registry.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'gmnspy.workbench'`.

- [ ] **Step 3: Create a minimal `packages/gmnspy/gmnspy/workbench/__init__.py`**

```python
"""GMNSpy Workbench: one live session served as a local web app (``gmnspy app``)."""
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/workbench/registry.py`**

```python
"""Open-network registry: one :class:`NetworkHandle` bundle per loaded network.

A handle bundles components (``roadway`` today; ``transit`` is reserved for the
GTFS feed in phase P6) and carries a ``version`` that every mutation bumps.
Derived artifacts (pandas frames, binary map buffers) are cached per version,
so a mutation invalidates them, unlike the old viz app's permanent caches.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from gmnspy import Network

__all__ = ["COMPONENTS", "Component", "NetworkHandle", "NetworkRegistry", "default_label"]

Component = Literal["roadway", "transit"]
COMPONENTS: tuple[Component, ...] = ("roadway", "transit")

#: Other canonical GMNS tables exposed in the data-table view when present (kept lazy).
_EXTRA_TABLES = ("lanes", "segments", "segment_lanes", "zones", "movements", "link_tod")
#: Directory/file stems too generic to name a network by.
_GENERIC_NAMES = {"csv", "parquet", "duckdb", "zip", "data", "network", ""}


def default_label(source: str) -> str:
    """A human label for ``source``: its stem, or its parent's name when the stem is generic."""
    p = Path(str(source).rstrip("/"))
    for candidate in (p.stem, p.parent.name):
        if candidate not in _GENERIC_NAMES:
            return candidate
    return "network"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "network"


def _as_pandas(table: Any) -> pd.DataFrame:
    return table.to_pandas() if hasattr(table, "to_pandas") else table.execute()


def _extra_tables(net: Network) -> dict[str, Any]:
    """Additional GMNS tables the network carries, kept lazy (best-effort), keyed by singular name."""
    out: dict[str, Any] = {}
    for accessor in _EXTRA_TABLES:
        try:
            tbl = getattr(net, accessor)
            if tbl is not None and tbl.count() > 0:
                out[accessor[:-1] if accessor.endswith("s") else accessor] = tbl
        except (AttributeError, KeyError, ValueError, FileNotFoundError):
            continue
    return out


@dataclass
class NetworkHandle:
    """A loaded network bundle plus its per-version derived-data cache."""

    id: str
    label: str
    source: str
    roadway: Network
    transit: Any | None = None
    version: int = 0
    lineage: list[str] = field(default_factory=list)
    _cache: dict[tuple[str, int], Any] = field(default_factory=dict, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def cached(self, key: str, build: Callable[[], Any]) -> Any:
        """Return ``build()`` memoised for the current version."""
        with self._lock:
            slot = (key, self.version)
            if slot not in self._cache:
                self._cache[slot] = build()
            return self._cache[slot]

    def bump(self) -> int:
        """Mark the network mutated: increment ``version`` and drop every cached artifact."""
        with self._lock:
            self.version += 1
            self._cache.clear()
            return self.version

    def links_df(self) -> pd.DataFrame:
        """The roadway ``link`` table as pandas (cached per version)."""
        return self.cached("links_df", lambda: _as_pandas(self.roadway.links))

    def nodes_df(self) -> pd.DataFrame:
        """The roadway ``node`` table as pandas (cached per version)."""
        return self.cached("nodes_df", lambda: _as_pandas(self.roadway.nodes))

    def node_xy(self) -> dict[Any, tuple[float, float]]:
        """``node_id -> (lon, lat)`` for anchor placement (cached per version)."""
        return self.cached(
            "node_xy", lambda: {r.node_id: (float(r.x_coord), float(r.y_coord)) for r in self.nodes_df().itertuples()}
        )

    def tables(self) -> dict[str, Any]:
        """Grid-browsable tables: eager ``link``/``node`` frames plus lazy extras."""
        return self.cached("tables", lambda: {"link": self.links_df(), "node": self.nodes_df(), **_extra_tables(self.roadway)})

    def summary(self) -> dict[str, Any]:
        """JSON-safe description for the session state."""
        return {
            "id": self.id,
            "label": self.label,
            "source": self.source,
            "version": self.version,
            "components": [c for c in COMPONENTS if getattr(self, c) is not None],
            "links": len(self.links_df()),
            "nodes": len(self.nodes_df()),
            "lineage": list(self.lineage),
        }


class NetworkRegistry:
    """Ordered collection of open :class:`NetworkHandle` objects keyed by id."""

    def __init__(self) -> None:
        """Start empty."""
        self._handles: dict[str, NetworkHandle] = {}

    def add(self, net: Network, *, source: str, label: str | None = None, net_id: str | None = None) -> NetworkHandle:
        """Register ``net`` under a unique id derived from ``net_id``/``label``/``source``."""
        derived = default_label(source)
        base = _slug(net_id or label or derived)
        hid, n = base, 2
        while hid in self._handles:
            hid, n = f"{base}-{n}", n + 1
        # an explicit label is kept; a derived one falls back to the unique id on collision
        handle = NetworkHandle(id=hid, label=label or (derived if hid == base else hid), source=source, roadway=net)
        self._handles[hid] = handle
        return handle

    def get(self, net_id: str) -> NetworkHandle:
        """Return the handle for ``net_id`` or raise ``KeyError("unknown network ...")``."""
        try:
            return self._handles[net_id]
        except KeyError:
            raise KeyError(f"unknown network {net_id!r}") from None

    def remove(self, net_id: str) -> None:
        """Forget ``net_id`` (``KeyError`` if unknown)."""
        self.get(net_id)
        del self._handles[net_id]

    def ids(self) -> list[str]:
        """Handle ids in insertion order."""
        return list(self._handles)

    def __iter__(self) -> Iterator[NetworkHandle]:
        """Iterate handles in insertion order."""
        return iter(list(self._handles.values()))

    def __len__(self) -> int:
        """Number of open networks."""
        return len(self._handles)
```

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_registry.py -q`
Expected: `6 passed`.

Two notes:
- `default_label("/x/leavenworth.csv.zip")`: `Path.stem` strips only `.zip`, which gives `leavenworth.csv`, as asserted.
- `KeyError`'s message is shown via `repr`, so `match="unknown network 'nope'"` matches.

- [ ] **Step 6: Commit**

```bash
uv run ruff check packages/gmnspy/gmnspy/workbench && uv run ruff format packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_registry.py
git add packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_registry.py
git commit -m "feat(workbench): NetworkHandle bundle (roadway + reserved transit) with per-version cache"
```

---

### Task 5: Thread-safe `EventBus`

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/events.py`
- Test: `packages/gmnspy/tests/test_workbench_events.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the workbench SSE event bus."""

import asyncio
import json
import threading

from gmnspy.workbench.events import EventBus, sse_format


def test_publish_from_another_thread_reaches_subscriber():
    bus = EventBus()

    async def main():
        q = bus.subscribe()
        t = threading.Thread(target=bus.publish, args=({"type": "ping", "n": 1},))
        t.start()
        t.join()
        return await asyncio.wait_for(q.get(), 1)

    assert asyncio.run(main()) == {"type": "ping", "n": 1}


def test_unsubscribe_stops_delivery():
    bus = EventBus()

    async def main():
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.publish({"type": "ping"})
        await asyncio.sleep(0)
        return q.empty(), bus.subscriber_count

    assert asyncio.run(main()) == (True, 0)


def test_publish_with_no_subscribers_is_a_noop():
    EventBus().publish({"type": "ping"})


def test_sse_format():
    text = sse_format({"type": "state", "x": 1})
    assert text.startswith("event: state\ndata: ") and text.endswith("\n\n")
    assert json.loads(text.split("data: ", 1)[1]) == {"type": "state", "x": 1}
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_events.py -q`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/workbench/events.py`**

```python
"""Fan-out of session events to Server-Sent-Events subscribers.

``publish`` is called from whatever thread ran the action (FastAPI's threadpool,
a notebook thread); each subscriber is an ``asyncio.Queue`` owned by the event
loop serving its SSE response, so delivery hops loops via ``call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

__all__ = ["EventBus", "sse_format"]


class EventBus:
    """Thread-safe publish → per-subscriber asyncio queues."""

    def __init__(self) -> None:
        """Start with no subscribers."""
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        """Return a new queue fed by :meth:`publish`. Must be called inside a running event loop."""
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.append((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Stop delivering to ``queue`` (no-op if already gone)."""
        with self._lock:
            self._subs = [(loop, q) for loop, q in self._subs if q is not queue]

    @property
    def subscriber_count(self) -> int:
        """Number of live subscribers."""
        with self._lock:
            return len(self._subs)

    def publish(self, event: dict[str, Any]) -> None:
        """Deliver ``event`` to every subscriber; subscribers whose loop has closed are dropped."""
        with self._lock:
            subs = list(self._subs)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:  # loop closed: the client went away without unsubscribing
                self.unsubscribe(queue)


def sse_format(event: dict[str, Any]) -> str:
    """Encode ``event`` as one SSE frame named by its ``type``."""
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
```

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_events.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
uv run ruff check packages/gmnspy/gmnspy/workbench && uv run ruff format packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_events.py
git add packages/gmnspy/gmnspy/workbench/events.py packages/gmnspy/tests/test_workbench_events.py
git commit -m "feat(workbench): thread-safe EventBus for SSE fan-out"
```

---

### Task 6: Action schemas and `to_python`

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/actions.py`
- Test: `packages/gmnspy/tests/test_workbench_actions.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_actions.py -q`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/workbench/actions.py`**

```python
"""Typed workbench Actions: the one vocabulary for UI clicks, Python, and the NL assistant.

Every state change in a :class:`~gmnspy.workbench.session.Session` is one of these
pydantic models, discriminated on ``type``. The same JSON schema is what the LLM
sees as tools (P3), so natural language yields validated Actions, never ids or
code. ``mutates`` marks actions the assistant must draft-before-apply.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .registry import Component

__all__ = [
    "Action",
    "ClearSelection",
    "CloseNetwork",
    "Navigate",
    "OpenNetwork",
    "Select",
    "SetActiveNetwork",
    "SetSetting",
    "Style",
    "action_json_schema",
    "parse_action",
    "to_python",
]

RGB = Annotated[list[Annotated[int, Field(ge=0, le=255)]], Field(min_length=3, max_length=3)]


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mutates: ClassVar[bool] = False


class OpenNetwork(_Action):
    """Load a GMNS network from a local path or URL and make it active."""

    type: Literal["open_network"] = "open_network"
    source: str
    label: str | None = None
    net_id: str | None = None


class CloseNetwork(_Action):
    """Close an open network."""

    type: Literal["close_network"] = "close_network"
    net_id: str


class SetActiveNetwork(_Action):
    """Switch which open network the map and tables show."""

    type: Literal["set_active_network"] = "set_active_network"
    net_id: str


class Select(_Action):
    """Select features by natural-language utterance or explicit ids (``net_id`` defaults to active)."""

    type: Literal["select"] = "select"
    net_id: str | None = None
    component: Component = "roadway"
    utterance: str | None = None
    link_ids: list[int | str] | None = None

    @model_validator(mode="after")
    def _one_target(self) -> Select:
        if (self.utterance is None) == (self.link_ids is None):
            raise ValueError("give exactly one of utterance or link_ids")
        return self


class ClearSelection(_Action):
    """Clear the current selection."""

    type: Literal["clear_selection"] = "clear_selection"


class Style(_Action):
    """Partially update the map style; omitted fields are unchanged."""

    type: Literal["style"] = "style"
    color_by: str | None = None
    ramp: Literal["YlOrRd", "Blues", "Viridis"] | None = None
    show: dict[Literal["links", "nodes", "labels", "selection"], bool] | None = None
    colors: dict[Literal["links", "nodes", "selection"], RGB] | None = None
    offset: bool | None = None
    show_direction: bool | None = None
    show_legend: bool | None = None


class Navigate(_Action):
    """Move the map camera to a bbox, the active network, or the selection."""

    type: Literal["navigate"] = "navigate"
    bbox: tuple[float, float, float, float] | None = None
    to_network: bool = False
    to_selection: bool = False

    @model_validator(mode="after")
    def _one_target(self) -> Navigate:
        if sum([self.bbox is not None, self.to_network, self.to_selection]) != 1:
            raise ValueError("give exactly one of bbox, to_network, to_selection")
        return self


class SetSetting(_Action):
    """Change a setting (dotted key) for this session, or persist it to the user/project file."""

    type: Literal["set_setting"] = "set_setting"
    mutates: ClassVar[bool] = True
    key: str
    value: Any = None
    scope: Literal["session", "user", "project"] = "session"


Action = Annotated[
    OpenNetwork | CloseNetwork | SetActiveNetwork | Select | ClearSelection | Style | Navigate | SetSetting,
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)


def parse_action(data: dict[str, Any]) -> Action:
    """Validate a JSON dict into an Action (raises ``pydantic.ValidationError``)."""
    return _ADAPTER.validate_python(data)


def action_json_schema() -> dict[str, Any]:
    """JSON schema of the Action union (the assistant's tool vocabulary)."""
    return _ADAPTER.json_schema()


def to_python(action: _Action) -> str:
    """The Python call that replays ``action`` against a live workbench handle named ``app``."""
    fields = action.model_dump(exclude_defaults=True, exclude={"type"})
    args = ", ".join(f"{k}={v!r}" for k, v in fields.items())
    return f"app.do({type(action).__name__}({args}))"
```

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_actions.py -q`
Expected: `9 passed`.

If `test_action_json_schema_lists_every_type` fails because pydantic emits each variant under `$defs` with `type` as `{"const": ...}` nested differently, print `action_json_schema()["$defs"]["OpenNetwork"]["properties"]["type"]` and adjust the test's extraction. Do not change the schema.

- [ ] **Step 5: Commit**

```bash
uv run ruff check packages/gmnspy/gmnspy/workbench && uv run ruff format packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_actions.py
git add packages/gmnspy/gmnspy/workbench/actions.py packages/gmnspy/tests/test_workbench_actions.py
git commit -m "feat(workbench): typed Action union with to_python replay snippets"
```

---

### Task 7: `Session`: dispatch, handlers, history, state

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/selection.py`
- Create: `packages/gmnspy/gmnspy/workbench/session.py`
- Test: `packages/gmnspy/tests/test_workbench_session.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_session.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'gmnspy.workbench.session'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/workbench/selection.py`**

```python
"""Turn a :class:`~gmnspy.select.result.SelectionResult` into the workbench's JSON selection payload."""

from __future__ import annotations

from typing import Any

from gmnspy.select.emit import to_fragment
from gmnspy.viz.styling import json_scalar

from .registry import NetworkHandle

__all__ = ["selection_payload", "unparsed_payload"]


def selection_payload(handle: NetworkHandle, result: Any, *, utterance: str | None = None) -> dict[str, Any]:
    """JSON-safe selection: status, link ids, located from/to anchors, fragment, diagnostics."""
    node_xy = handle.node_xy()
    anchors = []
    for role, match in (("from", result.from_match), ("to", result.to_match)):
        if match and match.node_id is not None and match.node_id in node_xy:
            lon, lat = node_xy[match.node_id]
            anchors.append(
                {
                    "role": role,
                    "node_id": json_scalar(match.node_id),
                    "lon": lon,
                    "lat": lat,
                    "kind": match.kind,
                    "detail": match.detail,
                }
            )
    return {
        "net_id": handle.id,
        "component": "roadway",
        "status": result.status,
        "utterance": utterance,
        "link_ids": [json_scalar(i) for i in result.link_ids],
        "anchors": anchors,
        "fragment": to_fragment(result) if result.status == "resolved" else None,
        "diagnostics": list(result.diagnostics),
    }


def unparsed_payload(handle: NetworkHandle, utterance: str, error: Exception) -> dict[str, Any]:
    """A ``not_found`` selection for an utterance the parser could not read."""
    return {
        "net_id": handle.id,
        "component": "roadway",
        "status": "not_found",
        "utterance": utterance,
        "link_ids": [],
        "anchors": [],
        "fragment": None,
        "diagnostics": [f"could not parse: {error}"],
    }
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/workbench/session.py`**

```python
"""Workbench session: the one place state changes, via :meth:`Session.dispatch`.

UI clicks (``POST /api/actions``), Python (``session.dispatch(...)``), and, in
P3, the NL assistant all funnel through ``dispatch``. Each call is recorded as a
:class:`HistoryEntry` carrying its ``to_python`` replay snippet, and publishes
``history`` + ``state`` events for the browser. Network *edits* are not actions
here yet: in P2 they become ProjectCard-shaped ``NetworkChange`` objects.
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from gmnspy import Network
from gmnspy.config import LoadedSettings, Settings, SettingsError, get_value, load_settings, save_setting
from gmnspy.select.intent import SelectionIntent
from gmnspy.select.parse import ClaudeParser, StubParser
from gmnspy.select.resolve import resolve_frames
from gmnspy.viz.styling import styleable_columns

from .actions import (
    Action,
    ClearSelection,
    CloseNetwork,
    Navigate,
    OpenNetwork,
    Select,
    SetActiveNetwork,
    SetSetting,
    Style,
    parse_action,
    to_python,
)
from .events import EventBus
from .registry import NetworkHandle, NetworkRegistry
from .selection import selection_payload, unparsed_payload

__all__ = ["DEFAULT_STYLE", "ActionError", "HistoryEntry", "NotSupportedYet", "Session"]

DEFAULT_STYLE: dict[str, Any] = {
    "color_by": "none",
    "ramp": "YlOrRd",
    "offset": True,
    "show_direction": False,
    "show_legend": True,
    "show": {"links": True, "nodes": True, "labels": True, "selection": True},
    "colors": {"links": [46, 64, 110], "nodes": [70, 90, 120], "selection": [255, 140, 59]},
}


class ActionError(Exception):
    """An action could not be applied; the message is shown to the user."""


class NotSupportedYet(ActionError):
    """The action is in the schema but its handler ships in a later phase."""


@dataclass
class HistoryEntry:
    """One dispatched action, successful or not."""

    seq: int
    action: dict[str, Any]
    python: str
    ok: bool
    error: str | None
    error_type: str | None
    result: Any
    ts: float

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe copy."""
        return asdict(self)


class Session:
    """Live workbench state: open networks, selection, style, settings, history."""

    def __init__(
        self,
        *,
        project_dir: str | Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        parser: Any = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """Load settings (raises :class:`~gmnspy.config.SettingsError` on bad config) and start empty."""
        self.project_dir = project_dir
        self._environ = environ
        self._overrides: dict[str, Any] = dict(overrides or {})
        self.loaded: LoadedSettings = load_settings(project_dir=project_dir, overrides=self._overrides, environ=environ)
        self.registry = NetworkRegistry()
        self.events = EventBus()
        self.active: str | None = None
        self.selection: dict[str, Any] | None = None
        self.style: dict[str, Any] = copy.deepcopy(DEFAULT_STYLE)
        self.history: list[HistoryEntry] = []
        self._injected_parser = parser
        self._parser = parser
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ public API

    @property
    def settings(self) -> Settings:
        """The currently resolved settings."""
        return self.loaded.settings

    def parser(self) -> Any:
        """The NL parser chosen by ``select.provider`` (built lazily; an injected parser wins)."""
        if self._parser is None:
            sel = self.settings.select
            self._parser = ClaudeParser(model=sel.model) if sel.provider == "claude" else StubParser()
        return self._parser

    def dispatch(self, action: Action | dict[str, Any]) -> Any:
        """Apply ``action`` and return its result; raise :class:`ActionError` if it failed (still recorded)."""
        entry = self.dispatch_recorded(action)
        if not entry.ok:
            raise (NotSupportedYet if entry.error_type == "NotSupportedYet" else ActionError)(entry.error)
        return entry.result

    do = dispatch

    def dispatch_recorded(self, action: Action | dict[str, Any]) -> HistoryEntry:
        """Apply ``action``, record and publish it, and return the entry (never raises ``ActionError``)."""
        if isinstance(action, dict):
            action = parse_action(action)
        handler = getattr(self, f"_do_{action.type}")
        with self._lock:
            try:
                result, ok, error, error_type = handler(action), True, None, None
            except ActionError as exc:  # includes NotSupportedYet
                result, ok, error, error_type = None, False, str(exc), type(exc).__name__
            entry = HistoryEntry(
                seq=len(self.history) + 1,
                action=action.model_dump(mode="json"),
                python=to_python(action),
                ok=ok,
                error=error,
                error_type=error_type,
                result=copy.deepcopy(result),
                ts=time.time(),
            )
            self.history.append(entry)
            state = self.state() if ok else None
        self.events.publish({"type": "history", "entry": entry.to_dict()})
        if state is not None:
            self.events.publish({"type": "state", "state": state})
        return entry

    def add_network(
        self, net: Network, *, source: str = "<python>", label: str | None = None, net_id: str | None = None
    ) -> NetworkHandle:
        """Register an already-loaded ``Network`` (the Python path; not an Action because it isn't JSON)."""
        with self._lock:
            handle = self.registry.add(net, source=source, label=label, net_id=net_id)
            self.active = self.active or handle.id
            state = self.state()
        self.events.publish({"type": "state", "state": state})
        return handle

    def state(self) -> dict[str, Any]:
        """JSON-safe snapshot pushed to the browser."""
        with self._lock:
            return {
                "networks": [h.summary() for h in self.registry],
                "active": self.active,
                "selection": copy.deepcopy(self.selection),
                "style": copy.deepcopy(self.style),
            }

    def settings_payload(self) -> dict[str, Any]:
        """Settings values, per-key sources, JSON schema, and file paths (for the Settings UI)."""
        return {
            "values": self.settings.model_dump(mode="json"),
            "sources": dict(self.loaded.sources),
            "schema": Settings.model_json_schema(),
            "paths": {"user": str(self.loaded.user_path), "project": str(self.loaded.project_path)},
        }

    # ------------------------------------------------------------------ handlers

    def _handle(self, net_id: str | None) -> NetworkHandle:
        target = net_id or self.active
        if target is None:
            raise ActionError("no network is open")
        try:
            return self.registry.get(target)
        except KeyError as exc:
            raise ActionError(exc.args[0]) from exc

    def _do_open_network(self, action: OpenNetwork) -> dict[str, Any]:
        try:
            net = Network.from_source(action.source, spec_version=self.settings.io.spec_version)
        except Exception as exc:  # boundary: any load failure is a user-facing error, not a crash
            raise ActionError(f"could not open {action.source}: {exc}") from exc
        handle = self.registry.add(net, source=action.source, label=action.label, net_id=action.net_id)
        self.active = handle.id
        return {"net_id": handle.id}

    def _do_close_network(self, action: CloseNetwork) -> None:
        self._handle(action.net_id)
        self.registry.remove(action.net_id)
        if self.selection and self.selection["net_id"] == action.net_id:
            self.selection = None
        if self.active == action.net_id:
            ids = self.registry.ids()
            self.active = ids[0] if ids else None

    def _do_set_active_network(self, action: SetActiveNetwork) -> None:
        self.active = self._handle(action.net_id).id

    def _do_select(self, action: Select) -> dict[str, Any]:
        if action.component != "roadway":
            raise NotSupportedYet("transit selection arrives with the transit component (phase P6)")
        handle = self._handle(action.net_id)
        if action.utterance is not None:
            try:
                intent = self.parser().parse(action.utterance)
            except Exception as exc:  # any parse failure is a normal "not_found" selection
                self.selection = unparsed_payload(handle, action.utterance, exc)
                return self.selection
        else:
            intent = SelectionIntent(link_ids=list(action.link_ids or []))
        result = resolve_frames(intent, handle.links_df(), handle.nodes_df())
        self.selection = selection_payload(handle, result, utterance=action.utterance)
        return self.selection

    def _do_clear_selection(self, action: ClearSelection) -> None:
        self.selection = None

    def _do_style(self, action: Style) -> dict[str, Any]:
        patch = action.model_dump(exclude_none=True, exclude={"type"})
        color_by = patch.get("color_by")
        if color_by not in (None, "none"):
            names = {c["name"] for c in styleable_columns(self._handle(None).links_df())}
            if color_by not in names:
                raise ActionError(f"cannot color by {color_by!r}; choose one of {sorted(names)}")
        for key, value in patch.items():
            self.style[key] = {**self.style[key], **value} if isinstance(value, dict) else value
        return copy.deepcopy(self.style)

    def _do_navigate(self, action: Navigate) -> None:
        if action.to_selection and not self.selection:
            raise ActionError("nothing is selected")
        self.events.publish({"type": "navigate", **action.model_dump(mode="json", exclude={"type"})})

    def _do_set_setting(self, action: SetSetting) -> dict[str, Any]:
        try:
            if action.scope == "session":
                overrides = {**self._overrides, action.key: action.value}
                loaded = load_settings(project_dir=self.project_dir, overrides=overrides, environ=self._environ)
                self._overrides = overrides
            else:
                save_setting(
                    action.key, action.value, scope=action.scope, project_dir=self.project_dir, environ=self._environ
                )
                loaded = load_settings(project_dir=self.project_dir, overrides=self._overrides, environ=self._environ)
            value = get_value(loaded.settings, action.key)
        except SettingsError as exc:
            raise ActionError(str(exc)) from exc
        self.loaded = loaded
        if action.key.startswith("select.") and self._injected_parser is None:
            self._parser = None  # rebuilt from the new provider/model on next use
        return {"key": action.key, "value": value, "source": loaded.sources.get(action.key)}
```

Two notes:
- `test_navigate_publishes_event` expects `bbox` serialised as `None` for `to_network`. `model_dump(mode="json")` gives `{"bbox": None, "to_network": True, "to_selection": False}`.
- `test_set_setting_rejects_bad_value` expects the `SettingsError` text `invalid settings (...)` from Task 1's `_validate`.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_session.py -q`
Expected: `19 passed`.

- [ ] **Step 6: Commit**

```bash
uv run ruff check packages/gmnspy/gmnspy/workbench && uv run ruff format packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_session.py
git add packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_session.py
git commit -m "feat(workbench): Session action bus with recorded history and state snapshots"
```

---

### Task 8: Server core routes (state, actions, history, settings, config, SSE)

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/routes/__init__.py` (empty docstring module)
- Create: `packages/gmnspy/gmnspy/workbench/routes/core.py`
- Create: `packages/gmnspy/gmnspy/workbench/server.py`
- Create: `packages/gmnspy/gmnspy/workbench/static/index.html` (placeholder replaced in Task 10; a one-line `<!DOCTYPE html><title>GMNSpy Workbench</title>` for now)
- Modify: `packages/gmnspy/gmnspy/workbench/__init__.py`
- Test: `packages/gmnspy/tests/test_workbench_server.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_server.py -q`
Expected: FAIL, `ImportError: cannot import name 'Session' from 'gmnspy.workbench'`.

- [ ] **Step 3: Replace `packages/gmnspy/gmnspy/workbench/__init__.py`**

```python
"""GMNSpy Workbench: one live session served as a local web app (``gmnspy app``).

``Session`` is the action bus; ``build_app``/``serve`` need the ``[server]``
extra (FastAPI + uvicorn) and are imported lazily so ``Session`` works without it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .session import ActionError, NotSupportedYet, Session

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["ActionError", "NotSupportedYet", "Session", "build_app", "serve"]


def build_app(session: Session) -> FastAPI:
    """Return the workbench FastAPI app over ``session``."""
    from .server import build_app as _build_app

    return _build_app(session)


def serve(session: Session) -> None:
    """Serve ``session`` with uvicorn at ``settings.app.host:port`` (blocks)."""
    import uvicorn

    app_settings = session.settings.app
    uvicorn.run(build_app(session), host=app_settings.host, port=app_settings.port)
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/workbench/routes/__init__.py`**

```python
"""FastAPI routers for the workbench."""
```

- [ ] **Step 5: Create `packages/gmnspy/gmnspy/workbench/routes/core.py`**

```python
"""Session-level routes: state, actions, history, settings, basemap config, and the SSE stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from gmnspy.viz.styling import basemap_style

from ..events import sse_format
from ..session import Session

__all__ = ["core_router"]

#: Seconds between SSE keep-alive comments (keeps proxies from closing idle streams).
KEEPALIVE_S = 15.0


def core_router(session: Session) -> APIRouter:
    """Build the ``/api`` router bound to ``session``."""
    router = APIRouter(prefix="/api")

    @router.get("/state")
    def state() -> dict[str, Any]:
        return session.state()

    @router.get("/config")
    def config() -> dict[str, Any]:
        return {"style": basemap_style(session.settings.viz.basemap)}

    @router.get("/settings")
    def settings() -> dict[str, Any]:
        return session.settings_payload()

    @router.get("/history")
    def history() -> dict[str, Any]:
        return {"entries": [e.to_dict() for e in list(session.history)]}

    @router.post("/actions")
    def actions(body: dict = Body(...)) -> JSONResponse:  # noqa: B008  (FastAPI Body default)
        try:
            entry = session.dispatch_recorded(body)
        except ValidationError as exc:
            detail = exc.errors(include_url=False, include_context=False)
            return JSONResponse({"error": "invalid action", "detail": jsonable_encoder(detail)}, status_code=422)
        payload = {"ok": entry.ok, "result": entry.result, "error": entry.error, "entry": entry.to_dict()}
        return JSONResponse(jsonable_encoder(payload), status_code=200 if entry.ok else 400)

    @router.get("/events")
    async def events(request: Request, max_events: int | None = None) -> StreamingResponse:
        """SSE stream: a ``state`` snapshot first, then every published event.

        ``max_events`` closes the stream after that many events (tests and scripted clients).
        """
        queue = session.events.subscribe()

        async def stream() -> AsyncIterator[str]:
            sent = 0
            try:
                snapshot = await asyncio.to_thread(session.state)
                yield sse_format({"type": "state", "state": snapshot})
                sent += 1
                while max_events is None or sent < max_events:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield sse_format(event)
                    sent += 1
            finally:
                session.events.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return router
```

- [ ] **Step 6: Create `packages/gmnspy/gmnspy/workbench/server.py`**

```python
"""Assemble the workbench FastAPI app: static front end + API routers."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routes.core import core_router
from .session import Session

__all__ = ["STATIC_DIR", "build_app"]

STATIC_DIR = Path(__file__).parent / "static"


def build_app(session: Session) -> FastAPI:
    """Return the FastAPI app serving ``session``."""
    app = FastAPI(title="GMNSpy Workbench")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(core_router(session))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    return app
```

- [ ] **Step 7: Create the placeholder `packages/gmnspy/gmnspy/workbench/static/index.html`**

```html
<!DOCTYPE html><title>GMNSpy Workbench</title>
```

- [ ] **Step 8: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_server.py -q`
Expected: `8 passed`.

If `test_events_stream_starts_with_state_snapshot` hangs, check that `max_events=1` ends the generator straight after the first `yield`. The `while` condition `sent < max_events` must already be false.

- [ ] **Step 9: Commit**

```bash
uv run ruff check packages/gmnspy/gmnspy/workbench && uv run ruff format packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_server.py
git add packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_server.py
git commit -m "feat(workbench): core API routes (state/actions/history/settings) + SSE event stream"
```

---

### Task 9: Per-network data routes

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/routes/network.py`
- Modify: `packages/gmnspy/gmnspy/workbench/server.py` (include the router)
- Test: `packages/gmnspy/tests/test_workbench_network_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for /api/n/{net_id}/{component}/... routes."""

import json

import pytest
from fastapi.testclient import TestClient
from gmnspy.select.parse import StubParser
from gmnspy.viz.buffers import unpack_network
from gmnspy.workbench import Session, build_app

BASE = "/api/n/rdu-i40/roadway"


@pytest.fixture(scope="module")
def client(tmp_path_factory, rdu_source):
    tmp = tmp_path_factory.mktemp("wb")
    s = Session(project_dir=tmp, environ={"GMNSPY_CONFIG_DIR": str(tmp / "user")}, parser=StubParser())
    s.dispatch({"type": "open_network", "source": rdu_source})
    return TestClient(build_app(s))


def test_network_bin_unpacks(client):
    r = client.get(f"{BASE}/network.bin")
    assert r.headers["content-type"] == "application/octet-stream"
    net = unpack_network(r.content)
    assert net["links"]["count"] == 178 and net["nodes"]["count"] == 143


def test_attrs_index_aligned(client):
    j = client.get(f"{BASE}/network.attrs.json").json()
    assert len(j["link_id"]) == len(j["facility_type"]) == 178


def test_properties_and_property(client):
    props = {p["name"]: p["kind"] for p in client.get(f"{BASE}/properties").json()["properties"]}
    assert props["lanes"] == "continuous"
    p = client.get(f"{BASE}/property/lanes").json()
    assert p["kind"] == "continuous" and len(p["values"]) == 178
    assert client.get(f"{BASE}/property/nope").status_code == 404


def test_feature_lookup(client):
    lid = client.get(f"{BASE}/network.attrs.json").json()["link_id"][0]
    j = client.get(f"{BASE}/feature/link/{lid}").json()
    assert j["pk"] == "link_id" and j["attributes"]["link_id"] == lid and "geometry" not in j["attributes"]
    assert client.get(f"{BASE}/feature/link/999999999").status_code == 404


def test_tables_schema_rows(client):
    names = [t["name"] for t in client.get(f"{BASE}/tables").json()["tables"]]
    assert names[:2] == ["link", "node"]
    assert client.get(f"{BASE}/table/link/schema").json()["primary_key"] == "link_id"
    rows = client.get(f"{BASE}/table/link/rows", params={"limit": 5, "sort": "link_id", "dir": "desc"}).json()
    assert rows["total"] == 178 and len(rows["rows"]) == 5


def test_rows_filter_and_ids(client):
    spec = json.dumps([{"col": "facility_type", "op": "contains", "val": "motorway"}])
    j = client.get(f"{BASE}/table/link/rows", params={"filter": spec}).json()
    assert 0 < j["total"] < 178
    lid = client.get(f"{BASE}/network.attrs.json").json()["link_id"][0]
    assert client.get(f"{BASE}/table/link/rows", params={"ids": str(lid)}).json()["total"] == 1


def test_bad_filter_is_400(client):
    assert client.get(f"{BASE}/table/link/rows", params={"filter": "{"}).status_code == 400
    bad = json.dumps([{"col": "nope", "op": "eq", "val": 1}])
    assert client.get(f"{BASE}/table/link/rows", params={"filter": bad}).status_code == 400


def test_unknown_network_table_component(client):
    assert client.get("/api/n/nope/roadway/properties").status_code == 404
    assert client.get(f"{BASE}/table/nope/schema").status_code == 404
    assert client.get("/api/n/rdu-i40/bogus/properties").status_code == 404
    assert client.get("/api/n/rdu-i40/transit/properties").status_code == 501
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_network_routes.py -q`
Expected: FAIL, with 404s on every data route.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/workbench/routes/network.py`**

```python
"""Per-network data routes: ``/api/n/{net_id}/{component}/...``.

The ``component`` segment is ``roadway`` today; ``transit`` answers 501 until the
GTFS component lands (P6). Heavy payloads are cached on the handle per version.
"""

from __future__ import annotations

import json as _json
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from gmnspy.viz.buffers import network_attrs, pack_network
from gmnspy.viz.styling import json_scalar, property_payload, styleable_columns
from gmnspy.viz.tables import (
    FilterError,
    columns_of,
    page_table,
    parse_ids,
    primary_key,
    table_list_entry,
    table_schema,
)

from ..registry import NetworkHandle
from ..session import Session

__all__ = ["network_router"]


def _coerce_key(raw: str) -> Any:
    try:
        return int(raw)
    except ValueError:
        return raw


def network_router(session: Session) -> APIRouter:
    """Build the ``/api/n/{net_id}/{component}`` router bound to ``session``."""
    router = APIRouter(prefix="/api/n/{net_id}/{component}")

    def handle(net_id: str, component: str) -> NetworkHandle:
        if component == "transit":
            raise HTTPException(501, "the transit component is not supported yet (phase P6)")
        if component != "roadway":
            raise HTTPException(404, f"unknown component {component!r}")
        try:
            return session.registry.get(net_id)
        except KeyError as exc:
            raise HTTPException(404, exc.args[0]) from exc

    def table(h: NetworkHandle, name: str) -> Any:
        tables = h.tables()
        if name not in tables:
            raise HTTPException(404, f"unknown table {name!r}")
        return tables[name]

    @router.get("/network.bin")
    def network_bin(net_id: str, component: str) -> Response:
        h = handle(net_id, component)
        data = h.cached("network.bin", lambda: pack_network(h.links_df(), h.nodes_df()))
        return Response(data, media_type="application/octet-stream")

    @router.get("/network.attrs.json")
    def network_attrs_json(net_id: str, component: str) -> dict[str, Any]:
        h = handle(net_id, component)
        return h.cached("network.attrs", lambda: network_attrs(h.links_df()))

    @router.get("/properties")
    def properties(net_id: str, component: str) -> dict[str, Any]:
        return {"properties": styleable_columns(handle(net_id, component).links_df())}

    @router.get("/property/{name}")
    def property_values(net_id: str, component: str, name: str) -> dict[str, Any]:
        payload = property_payload(handle(net_id, component).links_df(), name)
        if payload is None:
            raise HTTPException(404, f"unknown property {name!r}")
        return payload

    @router.get("/feature/{table_name}/{pk_value}")
    def feature(net_id: str, component: str, table_name: str, pk_value: str) -> dict[str, Any]:
        src = table(handle(net_id, component), table_name)
        pk = primary_key(table_name, columns_of(src))
        if pk is None:
            raise HTTPException(404, f"table {table_name!r} has no primary key")
        key = _coerce_key(pk_value)
        page = page_table(src, limit=1, ids=[key], pk=pk)
        if not page["rows"]:
            raise HTTPException(404, f"{table_name} {pk_value} not found")
        return {
            "table": table_name,
            "pk": pk,
            "id": json_scalar(key),
            "attributes": dict(zip(page["columns"], page["rows"][0], strict=True)),
        }

    @router.get("/tables")
    def tables_list(net_id: str, component: str) -> dict[str, Any]:
        return {"tables": [table_list_entry(n, src) for n, src in handle(net_id, component).tables().items()]}

    @router.get("/table/{table_name}/schema")
    def table_schema_ep(net_id: str, component: str, table_name: str) -> dict[str, Any]:
        return table_schema(table_name, table(handle(net_id, component), table_name))

    @router.get("/table/{table_name}/rows")
    def table_rows(
        net_id: str,
        component: str,
        table_name: str,
        offset: int = 0,
        limit: int = 100,
        sort: str | None = None,
        dir: str = "asc",
        filter: str | None = None,
        ids: str | None = None,
    ) -> dict[str, Any]:
        src = table(handle(net_id, component), table_name)
        try:
            spec = _json.loads(filter) if filter else None
        except _json.JSONDecodeError as exc:
            raise HTTPException(400, f"bad filter json: {exc}") from exc
        try:
            payload = page_table(
                src,
                offset=offset,
                limit=limit,
                sort=sort,
                direction=dir,
                filter_spec=spec,
                ids=parse_ids(ids),
                pk=primary_key(table_name, columns_of(src)),
            )
        except FilterError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"name": table_name, **payload}

    return router
```

- [ ] **Step 4: Include the router in `server.py`**

In `packages/gmnspy/gmnspy/workbench/server.py`, add `from .routes.network import network_router` next to the `core_router` import, and add `app.include_router(network_router(session))` after `app.include_router(core_router(session))`.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_network_routes.py packages/gmnspy/tests/test_workbench_server.py -q`
Expected: all pass. If `test_rows_filter_and_ids`'s motorway filter returns 0, check the fixture's `facility_type` values with `uv run --all-extras python -c "import pandas as pd; from importlib import resources; print(pd.read_parquet(resources.files('gmnspy.fixtures.rdu_i40').joinpath('parquet/link.parquet'))['facility_type'].value_counts())"`. Then use a value that exists but doesn't cover every row.

- [ ] **Step 6: Commit**

```bash
uv run ruff check packages/gmnspy/gmnspy/workbench && uv run ruff format packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_network_routes.py
git add packages/gmnspy/gmnspy/workbench packages/gmnspy/tests/test_workbench_network_routes.py
git commit -m "feat(workbench): per-network data routes namespaced by net_id and component"
```

---

### Task 10: Modular front end

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/static/index.html` (replace placeholder)
- Create: `packages/gmnspy/gmnspy/workbench/static/app.css`
- Create: `packages/gmnspy/gmnspy/workbench/static/js/{dom,api,store,netbuf,palette,map,side,table,panels,header,history,main}.js`
- Test: `packages/gmnspy/tests/test_workbench_static.py`

Module dependency direction, with no cycles:
- `dom`, `api`, `store`, `netbuf` and `palette` are leaves.
- `map` imports `dom`, `palette`, `netbuf` and `store`.
- `side` imports `api`, `dom` and `store`.
- `table` imports `api`, `dom`, `map`, `side` and `store`.
- `panels` imports `api`, `dom`, `map` and `palette`.
- `header` imports `api`, `dom` and `map`.
- `history` imports `api` and `dom`.
- `main` imports all of them.

- [ ] **Step 1: Write the failing tests**

```python
"""Static front-end checks: served, module graph consistent, JS syntax valid."""

import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from gmnspy.workbench import Session, build_app
from gmnspy.workbench.server import STATIC_DIR

JS_DIR = STATIC_DIR / "js"
_IMPORT = re.compile(r'import\s*\{([^}]*)\}\s*from\s*"\./([\w-]+\.js)"')
_EXPORT = re.compile(r"export\s+(?:async\s+)?(?:function|const|let)\s+(\w+)")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("wb")
    return TestClient(build_app(Session(project_dir=tmp, environ={"GMNSPY_CONFIG_DIR": str(tmp / "u")})))


def test_index_loads_main_module(client):
    html = client.get("/").text
    assert '<script type="module" src="/static/js/main.js">' in html
    assert "/static/app.css" in html


@pytest.mark.parametrize("name", sorted(p.name for p in JS_DIR.glob("*.js")))
def test_every_module_is_served_as_javascript(client, name):
    r = client.get(f"/static/js/{name}")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]


def test_relative_imports_resolve_to_real_exports():
    exports = {p.name: set(_EXPORT.findall(p.read_text())) for p in JS_DIR.glob("*.js")}
    for path in JS_DIR.glob("*.js"):
        for names, target in _IMPORT.findall(path.read_text()):
            assert target in exports, f"{path.name} imports missing module {target}"
            for name in (n.strip() for n in names.split(",") if n.strip()):
                assert name in exports[target], f"{path.name} imports {name!r} not exported by {target}"


def test_every_element_id_used_by_js_exists_in_index():
    html = (STATIC_DIR / "index.html").read_text()
    ids = set(re.findall(r'id="([\w-]+)"', html))
    for path in JS_DIR.glob("*.js"):
        for used in re.findall(r'\$\("([\w-]+)"\)', path.read_text()):
            assert used in ids, f"{path.name} uses #{used} which index.html lacks"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_syntax(tmp_path):
    for path in JS_DIR.glob("*.js"):
        target = tmp_path / (path.stem + ".mjs")
        target.write_text(path.read_text())
        proc = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{path.name}: {proc.stderr}"
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_static.py -q`
Expected: FAIL. `test_index_loads_main_module` fails because the placeholder has no module script.

- [ ] **Step 3: Create `app.css` from the viz stylesheet, plus workbench additions**

```bash
sed -n '11,141p' packages/gmnspy/gmnspy/viz/templates/index.html > packages/gmnspy/gmnspy/workbench/static/app.css
cat >> packages/gmnspy/gmnspy/workbench/static/app.css <<'EOF'

  /* ---- workbench additions ---- */
  #app { grid-template-rows:auto 1fr auto; }
  #net-select { background:#0c0e12; color:var(--ink); border:1px solid var(--edge); border-radius:8px;
                padding:7px 8px; max-width:180px; }
  #open-src { width:220px; padding:8px 10px; border:1px solid var(--edge); border-radius:8px;
              background:#0c0e12; color:var(--ink); }
  footer#history { grid-column:1 / -1; display:flex; align-items:center; gap:10px; padding:6px 16px; min-width:0;
                   background:var(--panel); border-top:1px solid var(--edge); font-size:12px; color:var(--muted); }
  #hist-py { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ink);
             font-family:ui-monospace,monospace; }
  #hist-py.fail { color:var(--to); }
  #hist-panel { position:fixed; top:auto; bottom:44px; right:12px; width:min(640px, calc(100vw - 24px));
                max-height:50vh; overflow:auto; }
  #toast { position:fixed; left:50%; bottom:56px; transform:translateX(-50%); z-index:10; max-width:80vw;
           background:#3a1517; color:#ffd7d5; border:1px solid var(--to); border-radius:8px; padding:8px 14px;
           font-size:12.5px; display:none; }
  #toast.show { display:block; }
EOF
```

Expected: `head -1` of the file is the `:root { --bg:...` line, and `grep -c '</style>'` is `0`.

- [ ] **Step 4: Write `static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>GMNSpy Workbench</title>
<link href="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
<link href="/static/app.css" rel="stylesheet" />
<script src="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://cdn.jsdelivr.net/npm/deck.gl@9.0.38/dist.min.js"></script>
<script type="module" src="/static/js/main.js"></script>
</head>
<body>
<div id="app">
  <header>
    <h1>GMNSpy Workbench</h1>
    <select id="net-select" aria-label="Active network"></select>
    <input id="open-src" placeholder="Open network: path or URL" aria-label="Open network" />
    <button id="open-go" class="mini">Open</button>
    <div id="viewmode">
      <button data-mode="map" class="on">Map</button>
      <button data-mode="split">Split</button>
      <button data-mode="table">Table</button>
    </div>
    <input id="utterance" placeholder='e.g. "I-40 EB between South Miami Boulevard and Airport Boulevard"' aria-label="Selection utterance" />
    <button id="go">Select</button>
    <span id="count"></span>
  </header>
  <div id="stage" data-mode="map">
    <div id="map">
      <div id="map-btns">
        <button class="iconbtn" id="btn-pick" data-tip="Pick links (click; shift-drag box)" aria-label="Pick links">&#9647;</button>
        <button class="iconbtn" id="btn-fitnet" data-tip="Zoom to full network" aria-label="Zoom to full network">&#9974;</button>
        <button class="iconbtn" id="btn-fitsel" data-tip="Zoom to selection" aria-label="Zoom to selection">&#9673;</button>
        <button class="iconbtn" id="btn-layers" data-tip="Layers" aria-label="Layers">&#9635;</button>
        <button class="iconbtn" id="btn-settings" data-tip="Map settings" aria-label="Map settings">&#9881;</button>
      </div>
      <div class="panel" id="layers-panel">
        <h4>Layers</h4>
        <div class="row"><label class="sw"><input type="checkbox" id="tg-links"><span></span></label>
          <span class="lbl">Links</span><input type="color" class="swatch" id="col-links"></div>
        <div class="row"><label class="sw"><input type="checkbox" id="tg-nodes"><span></span></label>
          <span class="lbl">Nodes</span><input type="color" class="swatch" id="col-nodes"></div>
        <div class="row"><label class="sw"><input type="checkbox" id="tg-selection"><span></span></label>
          <span class="lbl">Selection</span><input type="color" class="swatch" id="col-selection"></div>
        <div class="row"><label class="sw"><input type="checkbox" id="tg-labels"><span></span></label>
          <span class="lbl">Basemap labels</span></div>
        <h4 style="margin-top:14px">Color links by</h4>
        <div class="row"><select id="colorby"><option value="none">None (single color)</option></select></div>
        <div class="row" id="ramp-row" style="display:none"><span class="lbl">Ramp</span>
          <select id="ramp"><option>YlOrRd</option><option>Blues</option><option>Viridis</option></select></div>
      </div>
      <div class="panel" id="settings-panel">
        <h4>Map settings</h4>
        <div class="row"><span class="lbl">Offset directions</span>
          <label class="sw"><input type="checkbox" id="tg-offset"><span></span></label></div>
        <div class="row"><span class="lbl">Show direction</span>
          <label class="sw"><input type="checkbox" id="tg-direction"><span></span></label></div>
        <div class="row"><span class="lbl">Show legend</span>
          <label class="sw"><input type="checkbox" id="tg-legend"><span></span></label></div>
      </div>
      <div id="legend"></div>
      <div id="boxsel"></div>
    </div>
    <div id="tablepane">
      <div id="tbl-rail"></div>
      <div id="tbl-main">
        <div id="tbl-bar"><span class="tname" id="tbl-name">—</span><span id="tbl-total"></span>
          <label class="sw" style="margin-left:auto"><input type="checkbox" id="tbl-tosel"><span></span></label>
          <span>Filter to map selection</span></div>
        <div id="tbl-grid-wrap"><table id="tbl-grid"></table></div>
        <div id="tbl-pager"><button id="tbl-prev">&#8592; Prev</button>
          <span id="tbl-range">—</span><button id="tbl-next">Next &#8594;</button></div>
      </div>
    </div>
  </div>
  <aside id="side">
    <div id="status-wrap"></div>
    <div class="label">Picked links <span id="pick-count" class="pcount">0</span></div>
    <div id="pick-wrap">
      <span class="empty" id="pick-hint">Turn on <b>Pick</b> (&#9647;), then click links or shift-drag a box.</span>
      <div id="pick-actions" style="display:none">
        <button class="mini" id="pick-select">Select picked</button>
        <button class="mini ghost" id="pick-clear">Clear</button>
      </div>
    </div>
    <div class="label">Link details</div>
    <div id="details"><span class="empty">Click a link on the map.</span></div>
    <div class="label">Anchors</div>
    <div id="anchors"><span class="empty">—</span></div>
    <div class="label">Fragment</div>
    <pre id="fragment">—</pre>
    <div class="label">Diagnostics</div>
    <div id="diag"><span class="empty">—</span></div>
  </aside>
  <footer id="history">
    <span id="hist-seq">—</span>
    <code id="hist-py">No actions yet.</code>
    <button class="mini ghost" id="hist-copy">Copy</button>
    <button class="mini ghost" id="hist-all">Session as Python</button>
  </footer>
</div>
<div class="panel" id="hist-panel">
  <h4>Session as Python</h4>
  <pre id="hist-script"></pre>
  <div class="row"><button class="mini" id="hist-copy-all">Copy all</button></div>
</div>
<div id="toast" role="status"></div>
</body>
</html>
```

- [ ] **Step 5: Write `static/js/dom.js`**

```js
// Small DOM helpers shared by the workbench modules.
export const $ = id => document.getElementById(id);

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = v => String(v).replace(/[&<>"']/g, c => ESC[c]);

let toastTimer = null;
export function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 5000);
}
```

- [ ] **Step 6: Write `static/js/api.js`**

```js
// Fetch + SSE client for the workbench API. Every state change goes through dispatch().
async function readJSON(r) {
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || j.detail || r.statusText);
  return j;
}

export const getJSON = path => fetch(path).then(readJSON);

export async function getBuffer(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.arrayBuffer();
}

export async function dispatch(action) {
  const r = await fetch("/api/actions", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(action),
  });
  return (await readJSON(r)).result;
}

export const netPath = (netId, rest) => `/api/n/${encodeURIComponent(netId)}/roadway/${rest}`;

export function subscribe(handlers) {
  const source = new EventSource("/api/events");
  for (const [type, fn] of Object.entries(handlers)) source.addEventListener(type, e => fn(JSON.parse(e.data)));
  return source;
}
```

- [ ] **Step 7: Write `static/js/store.js`**

```js
// Minimal pub/sub store. `server` mirrors the session state pushed over SSE;
// every other key is per-tab view state that never reaches the server.
export function createStore(initial) {
  const state = { ...initial };
  const subs = new Set();
  return {
    get: () => state,
    set(patch) {
      const changed = Object.keys(patch).filter(k => state[k] !== patch[k]);
      if (!changed.length) return;
      Object.assign(state, patch);
      for (const s of subs) if (s.keys.some(k => changed.includes(k))) s.fn(state);
    },
    subscribe(keys, fn) { const s = { keys, fn }; subs.add(s); return () => subs.delete(s); },
  };
}

export const store = createStore({
  server: null,               // {networks, active, selection, style}
  netKey: null,               // "<id>@<version>" of the decoded active network
  net: null, attrs: null, properties: [], prop: null,
  pickMode: false, picks: new Set(), marker: null,
});

export function activeSelection(s) {
  const sel = s.server && s.server.selection;
  return sel && sel.net_id === s.server.active ? sel : null;
}
```

- [ ] **Step 8: Write `static/js/netbuf.js`**

```js
// Decode the binary network payload from /network.bin (layout: gmnspy.viz.buffers.pack_network).
export function widthForLanes(lanes) { return Math.max(1.2, Math.min(9, 0.9 + 0.8 * lanes)); }

const take = (buf, off, bytes, Ctor) => new Ctor(buf.slice(off, off + bytes));

function buildArrows(L, linkStart, P) {
  const arrows = [];
  for (let i = 0; i < L.count; i++) {
    const s = linkStart[i], e = linkStart[i + 1];
    if (e - s < 2) continue;
    const m = Math.max(s + 1, Math.floor((s + e) / 2));
    const x1 = P[(m - 1) * 2], y1 = P[(m - 1) * 2 + 1], x2 = P[m * 2], y2 = P[m * 2 + 1];
    arrows.push({ position: [(x1 + x2) / 2, (y1 + y2) / 2], angle: -Math.atan2(x2 - x1, y2 - y1) * 180 / Math.PI });
  }
  return arrows;
}

export function decodeNetwork(buf) {
  const hlen = new DataView(buf).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hlen)));
  const L = header.links, N = header.nodes;
  let off = 4 + hlen;
  const linkPositions = take(buf, off, L.positionsBytes, Float32Array); off += L.positionsBytes;
  const linkStart = take(buf, off, L.startIndicesBytes, Uint32Array); off += L.startIndicesBytes;
  const linkIds = take(buf, off, L.idsBytes, Float64Array); off += L.idsBytes;
  const linkLanes = take(buf, off, L.lanesBytes, Uint8Array); off += L.lanesBytes;
  const nodePositions = take(buf, off, N.positionsBytes, Float32Array); off += N.positionsBytes;
  const nodeIds = take(buf, off, N.idsBytes, Float64Array);
  const id2idx = new Map(), nodeId2idx = new Map();
  for (let i = 0; i < linkIds.length; i++) id2idx.set(linkIds[i], i);
  for (let i = 0; i < nodeIds.length; i++) nodeId2idx.set(nodeIds[i], i);
  const linkWidths = new Float32Array(linkStart[L.count]);
  for (let i = 0; i < L.count; i++) {
    const w = widthForLanes(linkLanes[i]);
    for (let v = linkStart[i]; v < linkStart[i + 1]; v++) linkWidths[v] = w;
  }
  return {
    L, N, linkPositions, linkStart, linkIds, linkLanes, linkWidths, nodePositions, nodeIds, id2idx, nodeId2idx,
    arrows: buildArrows(L, linkStart, linkPositions),
  };
}
```

- [ ] **Step 9: Write `static/js/palette.js`**

```js
// Color palettes, ramps, and per-vertex link colors for color-by.
export const FT_PALETTE = {
  motorway: [214, 69, 65], motorway_link: [242, 150, 120], trunk: [232, 119, 34], trunk_link: [245, 182, 132],
  primary: [236, 160, 20], primary_link: [249, 214, 120], secondary: [86, 158, 70], secondary_link: [160, 200, 130],
  tertiary: [56, 150, 140], tertiary_link: [150, 202, 196], residential: [120, 130, 160],
  service: [176, 184, 196], unclassified: [150, 150, 165], living_street: [150, 150, 165], road: [150, 150, 165],
};
export const CAT_PALETTE = [[228, 66, 62], [57, 126, 184], [77, 175, 74], [152, 78, 163], [255, 140, 40],
  [212, 190, 40], [166, 86, 40], [247, 129, 191], [120, 130, 160], [60, 170, 160]];
export const RAMPS = {
  YlOrRd: [[255, 237, 160], [254, 178, 76], [240, 59, 32]],
  Blues: [[222, 235, 247], [107, 174, 214], [8, 81, 156]],
  Viridis: [[68, 1, 84], [33, 145, 140], [253, 231, 37]],
};
const NULL_COLOR = [205, 208, 214];

export const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
export const hex2rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
export const rgb2hex = c => "#" + c.map(x => x.toString(16).padStart(2, "0")).join("");
export const fmt = v => (Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * 10) / 10);

export function ramp(name, t) {
  const s = RAMPS[name] || RAMPS.YlOrRd, x = Math.max(0, Math.min(1, t)) * (s.length - 1);
  const i = Math.min(s.length - 2, Math.floor(x)), f = x - i, a = s[i], b = s[i + 1];
  return [0, 1, 2].map(k => Math.round(a[k] + (b[k] - a[k]) * f));
}

export function catColor(prop, cat, i) {
  return (prop && prop.name === "facility_type" && FT_PALETTE[cat]) || CAT_PALETTE[i % CAT_PALETTE.length];
}

function linkColor(i, style, prop) {
  if (!prop) return style.colors.links;
  const v = prop.values[i];
  if (v === null || v === undefined) return NULL_COLOR;
  if (prop.kind === "continuous") return ramp(style.ramp, prop.max > prop.min ? (v - prop.min) / (prop.max - prop.min) : 0.5);
  return catColor(prop, v, prop.categories.indexOf(v));
}

export function buildLinkColors(net, style, prop) {
  const p = prop && style.color_by !== "none" && prop.name === style.color_by ? prop : null;
  const c = new Uint8Array(net.linkStart[net.L.count] * 4);
  for (let i = 0; i < net.L.count; i++) {
    const [r, g, b] = linkColor(i, style, p);
    for (let v = net.linkStart[i]; v < net.linkStart[i + 1]; v++) { c[v * 4] = r; c[v * 4 + 1] = g; c[v * 4 + 2] = b; c[v * 4 + 3] = 222; }
  }
  return c;
}
```

- [ ] **Step 10: Write `static/js/map.js`**

```js
// deck.gl-over-MapLibre network rendering, picking, and camera moves.
import { $ } from "./dom.js";
import { widthForLanes } from "./netbuf.js";
import { buildLinkColors } from "./palette.js";
import { activeSelection, store } from "./store.js";

const OFFSET_EXT = typeof deck.PathStyleExtension === "function" ? new deck.PathStyleExtension({ offset: true }) : null;
const OFFSET_AMT = 0.8, ARROW_ZOOM = 13;
const PICK_COLOR = [45, 210, 230];
const ARROW_SVG = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><polygon points="12,3 20,21 12,16 4,21" fill="white"/></svg>');
const TOOLTIP_STYLE = { background: "#11151a", color: "#e6e8ec", fontSize: "12px", padding: "6px 8px",
  borderRadius: "6px", border: "1px solid #2a2f3a" };

let map = null, overlay = null, onLinkClick = () => {};
let colorCache = { key: null, colors: null };
let labelsShown = true;

export const hasOffset = () => OFFSET_EXT !== null;

export function initMap(style, handlers) {
  onLinkClick = handlers.onLinkClick;
  map = new maplibregl.Map({ container: "map", style, center: [-98.5, 39.8], zoom: 3 });
  map.addControl(new maplibregl.NavigationControl(), "top-left");
  overlay = new deck.MapboxOverlay({ interleaved: false, layers: [], getTooltip });
  map.addControl(overlay);
  new ResizeObserver(() => map.resize()).observe($("map"));
  map.on("zoomend", () => { const s = store.get(); if (s.server && s.server.style.show_direction) render(); });
  map.on("load", handlers.onReady);
  wireBoxSelect();
}

export function resizeSoon() { if (map) setTimeout(() => map.resize(), 60); }

function linkColors(s) {
  const st = s.server.style;
  const key = JSON.stringify([s.netKey, st.color_by, st.ramp, st.colors.links, s.prop && s.prop.name]);
  if (colorCache.key !== key) colorCache = { key, colors: buildLinkColors(s.net, st, s.prop) };
  return colorCache.colors;
}

function baseLayers(net, style, colors) {
  const layers = [];
  if (style.show.nodes) layers.push(new deck.ScatterplotLayer({ id: "nodes",
    data: { length: net.N.count, attributes: { getPosition: { value: net.nodePositions, size: 2 } } },
    getRadius: 1.8, radiusUnits: "pixels", radiusMinPixels: 1,
    getFillColor: [...style.colors.nodes, 150], pickable: false }));
  if (style.show.links) {
    const props = { id: "links", _pathType: "open",
      data: { length: net.L.count, startIndices: net.linkStart,
        attributes: { getPath: { value: net.linkPositions, size: 2 }, getWidth: { value: net.linkWidths, size: 1 },
                      getColor: { value: colors, size: 4 } } },
      widthUnits: "pixels", widthMinPixels: 1, capRounded: true, jointRounded: true,
      pickable: true, autoHighlight: true, highlightColor: [255, 140, 59, 235],
      onClick: info => { if (info && info.index >= 0) onLinkClick(store.get().attrs.link_id[info.index]); } };
    if (OFFSET_EXT) { props.extensions = [OFFSET_EXT]; props.getOffset = style.offset ? OFFSET_AMT : 0; }
    layers.push(new deck.PathLayer(props));
    if (style.show_direction && map.getZoom() >= ARROW_ZOOM) layers.push(new deck.IconLayer({ id: "arrows",
      data: net.arrows, getIcon: () => ({ url: ARROW_SVG, width: 24, height: 24, anchorY: 12 }),
      getPosition: d => d.position, getAngle: d => d.angle, getSize: 13, sizeUnits: "pixels",
      getColor: [40, 52, 78, 230], pickable: false }));
  }
  return layers;
}

// A highlight PathLayer over a set of link ids (shared by selection + picks).
function idPathLayer(net, layerId, ids, color, extraWidth) {
  const positions = [], startIndices = [0], widths = [];
  for (const id of ids) {
    const i = net.id2idx.get(id);
    if (i == null) continue;
    const w = widthForLanes(net.linkLanes[i]) + extraWidth;
    for (let k = net.linkStart[i] * 2; k < net.linkStart[i + 1] * 2; k += 2) {
      positions.push(net.linkPositions[k], net.linkPositions[k + 1]); widths.push(w);
    }
    startIndices.push(positions.length / 2);
  }
  if (startIndices.length < 2) return null;
  return new deck.PathLayer({ id: layerId, _pathType: "open",
    data: { length: startIndices.length - 1, startIndices: new Uint32Array(startIndices),
      attributes: { getPath: { value: new Float32Array(positions), size: 2 }, getWidth: { value: new Float32Array(widths), size: 1 } } },
    getColor: color, widthUnits: "pixels", widthMinPixels: 3, capRounded: true, jointRounded: true,
    parameters: { depthTest: false } });
}

function selectionLayers(net, style, sel) {
  const layers = [];
  const path = idPathLayer(net, "selection", sel.link_ids, [...style.colors.selection, 255], 3);
  if (path) layers.push(path);
  if (sel.anchors.length) layers.push(new deck.ScatterplotLayer({ id: "anchors", data: sel.anchors,
    getPosition: a => [a.lon, a.lat], getRadius: 7, radiusUnits: "pixels",
    getFillColor: a => (a.role === "from" ? [53, 196, 106] : [224, 82, 77]),
    getLineColor: [17, 21, 26], lineWidthMinPixels: 2, stroked: true, parameters: { depthTest: false } }));
  return layers;
}

function markerLayer(marker) {
  return new deck.ScatterplotLayer({ id: "marker", data: [marker], getPosition: m => [m.lon, m.lat],
    getRadius: 7, radiusUnits: "pixels", getFillColor: [45, 210, 230], getLineColor: [17, 21, 26],
    lineWidthMinPixels: 2, stroked: true, parameters: { depthTest: false } });
}

function setLabels(show) {
  if (show === labelsShown || !map.isStyleLoaded()) return;
  labelsShown = show;
  for (const l of map.getStyle().layers || [])
    if (l.type === "symbol" || l.id === "labels") map.setLayoutProperty(l.id, "visibility", show ? "visible" : "none");
}

export function render() {
  if (!overlay) return;
  const s = store.get();
  if (!s.net || !s.server) { overlay.setProps({ layers: [] }); return; }
  const style = s.server.style, sel = activeSelection(s);
  const layers = baseLayers(s.net, style, linkColors(s));
  if (style.show.selection && sel) layers.push(...selectionLayers(s.net, style, sel));
  if (s.picks.size) { const l = idPathLayer(s.net, "picked", s.picks, [...PICK_COLOR, 255], 2.5); if (l) layers.push(l); }
  if (s.marker) layers.push(markerLayer(s.marker));
  overlay.setProps({ layers });
  setLabels(style.show.labels);
}

function getTooltip({ layer, index }) {
  const attrs = store.get().attrs;
  if (!layer || layer.id !== "links" || index == null || index < 0 || !attrs) return null;
  const id = attrs.link_id[index], nm = attrs.name[index], rf = attrs.ref[index], ft = attrs.facility_type[index];
  const text = (v) => String(v).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  return { html: `<b>link ${text(id)}</b><br>${nm ? text(nm) : "<i>unnamed</i>"}${rf ? " · " + text(rf) : ""}` +
    `<br><span style="color:#8a93a3">${ft ? text(ft) : ""}</span>`, style: TOOLTIP_STYLE };
}

function fit(bounds, padding) { if (!bounds.isEmpty()) map.fitBounds(bounds, { padding, maxZoom: 15, duration: 500 }); }

export function fitNetwork() {
  const net = store.get().net;
  if (!map || !net) return;
  const b = new maplibregl.LngLatBounds();
  for (let i = 0; i < net.nodePositions.length; i += 2) b.extend([net.nodePositions[i], net.nodePositions[i + 1]]);
  fit(b, 60);
}

export function fitLinks(ids) {
  const net = store.get().net;
  if (!map || !net || !ids || !ids.length) return;
  const b = new maplibregl.LngLatBounds();
  for (const id of ids) {
    const i = net.id2idx.get(id);
    if (i == null) continue;
    for (let k = net.linkStart[i] * 2; k < net.linkStart[i + 1] * 2; k += 2) b.extend([net.linkPositions[k], net.linkPositions[k + 1]]);
  }
  fit(b, 80);
}

export function fitBbox(bbox) { if (map) map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 40, duration: 500 }); }

export function flyToNode(nodeId) {
  const net = store.get().net, i = net && net.nodeId2idx.get(nodeId);
  if (i == null) return;
  const lon = net.nodePositions[i * 2], lat = net.nodePositions[i * 2 + 1];
  store.set({ marker: { lon, lat } });
  map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 15), duration: 500 });
}

// shift-drag box select over the links layer (deck region picking) adds to picks
function wireBoxSelect() {
  const mapEl = $("map"), box = $("boxsel");
  let start = null;
  const deckInstance = () => overlay._deck || (overlay.props && overlay.props.deck) || null;
  mapEl.addEventListener("pointerdown", e => {
    if (!store.get().pickMode || !e.shiftKey || e.button !== 0) return;
    e.preventDefault(); map.dragPan.disable();
    const r = mapEl.getBoundingClientRect();
    start = { x: e.clientX - r.left, y: e.clientY - r.top, rect: r };
    Object.assign(box.style, { display: "block", left: start.x + "px", top: start.y + "px", width: "0px", height: "0px" });
  });
  mapEl.addEventListener("pointermove", e => {
    if (!start) return;
    const x = e.clientX - start.rect.left, y = e.clientY - start.rect.top;
    Object.assign(box.style, { left: Math.min(x, start.x) + "px", top: Math.min(y, start.y) + "px",
      width: Math.abs(x - start.x) + "px", height: Math.abs(y - start.y) + "px" });
  });
  const finish = e => {
    if (!start) return;
    const x = e.clientX - start.rect.left, y = e.clientY - start.rect.top;
    const x0 = Math.min(x, start.x), y0 = Math.min(y, start.y), w = Math.abs(x - start.x), h = Math.abs(y - start.y);
    box.style.display = "none"; map.dragPan.enable(); start = null;
    const dk = deckInstance(), s = store.get();
    if (!dk || !s.net || w <= 2 || h <= 2) return;
    const picks = new Set(s.picks);
    for (const p of dk.pickObjects({ x: x0, y: y0, width: w, height: h, layerIds: ["links"] }))
      if (p.index != null && p.index >= 0) picks.add(s.net.linkIds[p.index]);
    store.set({ picks });
  };
  mapEl.addEventListener("pointerup", finish);
  mapEl.addEventListener("pointerleave", e => { if (start) finish(e); });
}
```

- [ ] **Step 11: Write `static/js/side.js`**

```js
// Right-hand panel: selection result, link details, and interactive picks.
import { dispatch, getJSON, netPath } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { store } from "./store.js";

const HINT = '<span class="empty">Click a link for details; hover to inspect; type an utterance to select.</span>';

export function renderSelection(sel) {
  $("status-wrap").innerHTML = sel
    ? `<span class="status ${esc(sel.status)}">${esc(sel.status.replace("_", " "))}</span>` +
      (sel.utterance ? ` <span class="diag">${esc(sel.utterance)}</span>` : "")
    : HINT;
  const anchors = sel ? sel.anchors : [];
  $("anchors").innerHTML = anchors.length
    ? anchors.map(a => `<div><span class="dot" style="background:${a.role === "from" ? "#35c46a" : "#e0524d"}"></span>` +
        `<b>${esc(a.role)}</b> · node ${esc(a.node_id)} · ${esc(a.kind)} <span class="diag">(${esc(a.detail)})</span></div>`).join("")
    : '<span class="empty">—</span>';
  $("fragment").textContent = sel && sel.fragment ? JSON.stringify(sel.fragment, null, 2) : "—";
  const diags = sel ? sel.diagnostics : [];
  $("diag").innerHTML = diags.length ? diags.map(d => `<div class="diag">• ${esc(d)}</div>`).join("") : '<span class="empty">—</span>';
}

export async function showLinkDetails(linkId) {
  const el = $("details"), head = `<div class="lid">link ${esc(linkId)}</div>`;
  el.innerHTML = `${head}<span class="empty">loading…</span>`;
  try {
    const j = await getJSON(netPath(store.get().server.active, `feature/link/${encodeURIComponent(linkId)}`));
    const rows = Object.entries(j.attributes).filter(([k, v]) => k !== "link_id" && v !== null && v !== "")
      .map(([k, v]) => `<tr><td class="k">${esc(k)}</td><td class="v">${esc(v)}</td></tr>`).join("");
    el.innerHTML = `${head}<table>${rows}</table>`;
  } catch (e) {
    el.innerHTML = `${head}<span class="empty">error: ${esc(e.message)}</span>`;
  }
}

export function renderPicks(picks) {
  $("pick-count").textContent = picks.size;
  $("pick-hint").style.display = picks.size ? "none" : "";
  $("pick-actions").style.display = picks.size ? "flex" : "none";
}

export function wireSide() {
  $("pick-select").onclick = async () => {
    const ids = [...store.get().picks];
    if (!ids.length) return;
    try { await dispatch({ type: "select", link_ids: ids }); } catch (e) { toast(e.message); }
  };
  $("pick-clear").onclick = () => store.set({ picks: new Set() });
}
```

- [ ] **Step 12: Write `static/js/table.js`**

```js
// Data-table view: server-paged/sorted/filtered grid linked to the map selection.
import { dispatch, getJSON, netPath } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { fitLinks, flyToNode, resizeSoon } from "./map.js";
import { showLinkDetails } from "./side.js";
import { activeSelection, store } from "./store.js";

const TBL = { loaded: false, name: null, schema: null, offset: 0, limit: 100, sort: null, dir: "asc",
  filters: {}, total: 0, toSel: false };
const VIEW_KEY = "gmnspy.viewmode";
let filterTimer = null, lastSelKey = null;

const activeId = () => { const s = store.get().server; return s && s.active; };
const fail = e => toast(e.message);

export function setViewMode(mode) {
  $("stage").dataset.mode = mode;
  for (const b of document.querySelectorAll("#viewmode button")) b.classList.toggle("on", b.dataset.mode === mode);
  try { localStorage.setItem(VIEW_KEY, mode); } catch (e) { /* storage unavailable: mode just isn't remembered */ }
  if (mode !== "map" && !TBL.loaded) loadTables().catch(fail);
  resizeSoon();
}

export function onNetworkChanged() {
  Object.assign(TBL, { loaded: false, name: null, schema: null });
  $("tbl-rail").innerHTML = ""; $("tbl-grid").innerHTML = ""; $("tbl-name").textContent = "—";
  if ($("stage").dataset.mode !== "map") loadTables().catch(fail);
}

export function onSelectionChanged() {
  const sel = activeSelection(store.get());
  const key = JSON.stringify(sel ? [sel.link_ids, sel.anchors.map(a => a.node_id)] : null);
  if (key === lastSelKey) return;
  lastSelKey = key;
  if (TBL.schema) loadRows().catch(fail);
}

async function loadTables() {
  const id = activeId();
  if (!id) return;
  TBL.loaded = true;
  const j = await getJSON(netPath(id, "tables"));
  const rail = $("tbl-rail");
  rail.innerHTML = "";
  for (const t of j.tables) {
    const el = document.createElement("div");
    el.className = "tbl-item"; el.dataset.name = t.name;
    el.innerHTML = `<span>${esc(t.name)}</span><span class="rc">${t.rows.toLocaleString()}</span>`;
    el.onclick = () => selectTable(t.name).catch(fail);
    rail.appendChild(el);
  }
  if (j.tables.length) await selectTable(TBL.name || j.tables[0].name);
}

async function selectTable(name) {
  Object.assign(TBL, { name, offset: 0, sort: null, dir: "asc", filters: {} });
  for (const el of document.querySelectorAll(".tbl-item")) el.classList.toggle("on", el.dataset.name === name);
  TBL.schema = await getJSON(netPath(activeId(), `table/${encodeURIComponent(name)}/schema`));
  $("tbl-name").textContent = name;
  buildGridHeader();
  await loadRows();
}

const gridColumns = () => TBL.schema.columns.filter(c => c.kind !== "geom");

function buildGridHeader() {
  const arrow = c => (TBL.sort === c ? `<span class="ar">${TBL.dir === "asc" ? "▲" : "▼"}</span>` : "");
  const th = gridColumns().map(c => `<th><span class="cn" data-col="${esc(c.name)}">${esc(c.name)}${arrow(c.name)}</span>` +
    `<input data-fcol="${esc(c.name)}" placeholder="filter" value="${esc(TBL.filters[c.name] || "")}"></th>`).join("");
  $("tbl-grid").innerHTML = `<thead><tr>${th}</tr></thead><tbody></tbody>`;
  for (const el of document.querySelectorAll("#tbl-grid .cn")) el.onclick = () => toggleSort(el.dataset.col);
  for (const el of document.querySelectorAll("#tbl-grid input[data-fcol]")) el.oninput = () => {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(() => {
      const v = el.value.trim();
      if (v) TBL.filters[el.dataset.fcol] = v; else delete TBL.filters[el.dataset.fcol];
      TBL.offset = 0; loadRows().catch(fail);
    }, 250);
  };
}

function toggleSort(col) {
  if (TBL.sort === col) TBL.dir = TBL.dir === "asc" ? "desc" : "asc"; else { TBL.sort = col; TBL.dir = "asc"; }
  TBL.offset = 0; buildGridHeader(); loadRows().catch(fail);
}

function selIdsForTable() {
  const pk = TBL.schema && TBL.schema.primary_key, sel = activeSelection(store.get());
  if (!pk || !sel) return null;
  if (pk === "link_id") return sel.link_ids;
  if (pk === "node_id") return sel.anchors.map(a => a.node_id);
  return null;
}

async function loadRows() {
  const p = new URLSearchParams({ offset: TBL.offset, limit: TBL.limit });
  if (TBL.sort) { p.set("sort", TBL.sort); p.set("dir", TBL.dir); }
  const spec = Object.entries(TBL.filters).map(([col, val]) => ({ col, op: "contains", val }));
  if (spec.length) p.set("filter", JSON.stringify(spec));
  if (TBL.toSel) { const ids = selIdsForTable(); if (ids && ids.length) p.set("ids", ids.join(",")); }
  const j = await getJSON(netPath(activeId(), `table/${encodeURIComponent(TBL.name)}/rows?${p}`));
  TBL.total = j.total;
  renderRows(j.columns, j.rows);
  const to = Math.min(TBL.offset + TBL.limit, j.total);
  $("tbl-total").textContent = `· ${j.total.toLocaleString()} row(s)`;
  $("tbl-range").textContent = j.total ? `${TBL.offset + 1}–${to} of ${j.total.toLocaleString()}` : "0";
  $("tbl-prev").disabled = TBL.offset <= 0;
  $("tbl-next").disabled = to >= j.total;
}

function renderRows(cols, rows) {
  const pkIdx = cols.indexOf(TBL.schema.primary_key);
  const selIds = new Set((selIdsForTable() || []).map(String));
  const body = $("tbl-grid").tBodies[0];
  body.innerHTML = rows.map(r => {
    const pv = pkIdx >= 0 ? r[pkIdx] : null;
    const sel = pv != null && selIds.has(String(pv)) ? " sel" : "";
    const tds = r.map(v => `<td>${v === null ? '<span class="empty">·</span>' : esc(v)}</td>`).join("");
    return `<tr class="data${sel}" data-pk="${pv == null ? "" : esc(pv)}">${tds}</tr>`;
  }).join("");
  for (const tr of body.querySelectorAll("tr.data")) tr.onclick = () => tableRowClick(tr.dataset.pk);
}

async function tableRowClick(pkVal) {
  if (pkVal === "" || !TBL.schema) return;
  const n = Number(pkVal), id = Number.isNaN(n) ? pkVal : n;
  const pk = TBL.schema.primary_key, net = store.get().net;
  if (pk === "link_id" && net && net.id2idx.has(id)) {
    try { await dispatch({ type: "select", link_ids: [id] }); fitLinks([id]); showLinkDetails(id); } catch (e) { fail(e); }
  } else if (pk === "node_id") {
    flyToNode(id);
  }
}

export function wireTable() {
  for (const b of document.querySelectorAll("#viewmode button")) b.onclick = () => setViewMode(b.dataset.mode);
  $("tbl-prev").onclick = () => { if (TBL.offset > 0) { TBL.offset = Math.max(0, TBL.offset - TBL.limit); loadRows().catch(fail); } };
  $("tbl-next").onclick = () => { if (TBL.offset + TBL.limit < TBL.total) { TBL.offset += TBL.limit; loadRows().catch(fail); } };
  $("tbl-tosel").onchange = e => { TBL.toSel = e.target.checked; TBL.offset = 0; loadRows().catch(fail); };
}

export function restoreViewMode() {
  try { const m = localStorage.getItem(VIEW_KEY); if (m) setViewMode(m); } catch (e) { /* storage unavailable */ }
}
```

- [ ] **Step 13: Write `static/js/panels.js`**

```js
// Layers / map-settings panels and the legend. Every control change is a `style` action.
import { dispatch } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { hasOffset } from "./map.js";
import { RAMPS, catColor, fmt, hex2rgb, rgb, rgb2hex } from "./palette.js";

const style = patch => dispatch({ type: "style", ...patch }).catch(e => toast(e.message));

const SWITCHES = [
  ["tg-links", st => st.show.links, v => ({ show: { links: v } })],
  ["tg-nodes", st => st.show.nodes, v => ({ show: { nodes: v } })],
  ["tg-selection", st => st.show.selection, v => ({ show: { selection: v } })],
  ["tg-labels", st => st.show.labels, v => ({ show: { labels: v } })],
  ["tg-offset", st => st.offset, v => ({ offset: v })],
  ["tg-direction", st => st.show_direction, v => ({ show_direction: v })],
  ["tg-legend", st => st.show_legend, v => ({ show_legend: v })],
];
const COLORS = [["col-links", "links"], ["col-nodes", "nodes"], ["col-selection", "selection"]];

export function wirePanels() {
  const sp = $("settings-panel"), lp = $("layers-panel"), bs = $("btn-settings"), bl = $("btn-layers");
  const open = which => {
    const toS = which === "s" && !sp.classList.contains("open"), toL = which === "l" && !lp.classList.contains("open");
    sp.classList.toggle("open", toS); lp.classList.toggle("open", toL);
    bs.classList.toggle("on", toS); bl.classList.toggle("on", toL);
  };
  bs.onclick = () => open("s");
  bl.onclick = () => open("l");
  $("colorby").onchange = e => style({ color_by: e.target.value });
  $("ramp").onchange = e => style({ ramp: e.target.value });
  for (const [id, , patch] of SWITCHES) $(id).onchange = e => style(patch(e.target.checked));
  for (const [id, key] of COLORS) $(id).onchange = e => style({ colors: { [key]: hex2rgb(e.target.value) } });
  if (!hasOffset()) $("tg-offset").disabled = true;
}

export function populateColorby(props) {
  const sel = $("colorby");
  sel.innerHTML = '<option value="none">None (single color)</option>';
  for (const p of props) {
    const o = document.createElement("option");
    o.value = p.name; o.dataset.kind = p.kind;
    o.textContent = p.name + (p.kind === "continuous" ? " (num)" : "");
    sel.appendChild(o);
  }
}

export function syncControls(st) {
  $("colorby").value = st.color_by;
  $("ramp").value = st.ramp;
  const opt = $("colorby").selectedOptions[0];
  $("ramp-row").style.display = opt && opt.dataset.kind === "continuous" ? "flex" : "none";
  for (const [id, get] of SWITCHES) $(id).checked = get(st);
  for (const [id, key] of COLORS) $(id).value = rgb2hex(st.colors[key]);
}

export function renderLegend(st, prop) {
  const el = $("legend");
  if (!st.show_legend || st.color_by === "none" || !prop || prop.name !== st.color_by) { el.style.display = "none"; return; }
  el.style.display = "block";
  let html = `<div class="lg-title">${esc(prop.name)}</div>`;
  if (prop.kind === "continuous") {
    html += `<div class="lg-grad" style="background:linear-gradient(90deg, ${RAMPS[st.ramp].map(rgb).join(", ")})"></div>` +
      `<div class="lg-scale"><span>${fmt(prop.min)}</span><span>${fmt(prop.max)}</span></div>`;
  } else {
    html += prop.categories.map((c, i) =>
      `<div class="lg-item"><span class="lg-sw" style="background:${rgb(catColor(prop, c, i))}"></span>${esc(c)}</div>`).join("");
  }
  el.innerHTML = html;
}
```

- [ ] **Step 14: Write `static/js/header.js`**

```js
// Header: network switcher, open-by-path, and the utterance box. All via actions.
import { dispatch } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { fitLinks } from "./map.js";

async function run(action, after) {
  try { const result = await dispatch(action); if (after) after(result); } catch (e) { toast(e.message); }
}

export function renderHeader(server) {
  const sel = $("net-select");
  sel.innerHTML = server.networks.length
    ? server.networks.map(n => `<option value="${esc(n.id)}"${n.id === server.active ? " selected" : ""}>${esc(n.label)}</option>`).join("")
    : '<option value="">No network open</option>';
  sel.disabled = !server.networks.length;
  const h = server.networks.find(n => n.id === server.active);
  $("count").textContent = h ? `${h.links.toLocaleString()} links · ${h.nodes.toLocaleString()} nodes` : "";
}

export function wireHeader() {
  $("net-select").onchange = e => run({ type: "set_active_network", net_id: e.target.value });
  const open = () => {
    const source = $("open-src").value.trim();
    if (source) run({ type: "open_network", source }, () => { $("open-src").value = ""; });
  };
  $("open-go").onclick = open;
  $("open-src").onkeydown = e => { if (e.key === "Enter") open(); };
  const select = async () => {
    const utterance = $("utterance").value.trim();
    if (!utterance) return;
    $("go").disabled = true;
    await run({ type: "select", utterance }, sel => fitLinks(sel.link_ids));
    $("go").disabled = false;
  };
  $("go").onclick = select;
  $("utterance").onkeydown = e => { if (e.key === "Enter") select(); };
}
```

- [ ] **Step 15: Write `static/js/history.js`**

```js
// History strip: the last action as replayable Python, plus the whole session as a script.
import { getJSON } from "./api.js";
import { $, toast } from "./dom.js";

async function copy(text) {
  try { await navigator.clipboard.writeText(text); } catch (e) { toast(`copy failed: ${e.message}`); }
}

export function showEntry(entry) {
  $("hist-seq").textContent = `#${entry.seq}`;
  const py = $("hist-py");
  py.textContent = entry.ok ? entry.python : `${entry.python}  # failed: ${entry.error}`;
  py.classList.toggle("fail", !entry.ok);
}

export function sessionScript(entries) {
  const lines = ["# GMNSpy Workbench session: replay against a live workbench handle named `app`"];
  for (const e of entries) lines.push(e.ok ? e.python : `# failed: ${e.python}  # ${e.error}`);
  return lines.join("\n");
}

export function wireHistory() {
  $("hist-copy").onclick = () => copy($("hist-py").textContent);
  $("hist-all").onclick = async () => {
    if (!$("hist-panel").classList.toggle("open")) return;
    try { $("hist-script").textContent = sessionScript((await getJSON("/api/history")).entries); } catch (e) { toast(e.message); }
  };
  $("hist-copy-all").onclick = () => copy($("hist-script").textContent);
}
```

- [ ] **Step 16: Write `static/js/main.js`**

```js
// Workbench boot: wire modules to the store and the server's SSE stream.
import { getBuffer, getJSON, netPath, subscribe } from "./api.js";
import { $, toast } from "./dom.js";
import { renderHeader, wireHeader } from "./header.js";
import { showEntry, wireHistory } from "./history.js";
import { fitBbox, fitLinks, fitNetwork, initMap, render } from "./map.js";
import { decodeNetwork } from "./netbuf.js";
import { populateColorby, renderLegend, syncControls, wirePanels } from "./panels.js";
import { renderPicks, renderSelection, showLinkDetails, wireSide } from "./side.js";
import { activeSelection, store } from "./store.js";
import { onNetworkChanged, onSelectionChanged, restoreViewMode, wireTable } from "./table.js";

let loadingKey = null;

async function loadActiveNetwork() {
  const { server, netKey } = store.get();
  const h = server.networks.find(n => n.id === server.active);
  const key = h ? `${h.id}@${h.version}` : null;
  if (key === netKey || key === loadingKey) return;
  if (!h) { store.set({ netKey: null, net: null, attrs: null, properties: [], prop: null, marker: null }); return; }
  loadingKey = key;
  try {
    const [buf, attrs, props] = await Promise.all([
      getBuffer(netPath(h.id, "network.bin")), getJSON(netPath(h.id, "network.attrs.json")), getJSON(netPath(h.id, "properties")),
    ]);
    const switched = !netKey || !netKey.startsWith(`${h.id}@`);
    store.set({ netKey: key, net: decodeNetwork(buf), attrs, properties: props.properties, prop: null, marker: null });
    if (switched) fitNetwork();
  } finally {
    loadingKey = null;
  }
}

async function loadColorProperty() {
  const { server, net, netKey, prop } = store.get();
  const name = server.style.color_by;
  if (!net || name === "none" || (prop && prop.name === name && prop.netKey === netKey)) return;
  const p = await getJSON(netPath(server.active, `property/${encodeURIComponent(name)}`));
  store.set({ prop: { ...p, netKey } });
}

async function onState(server) {
  store.set({ server });
  try { await loadActiveNetwork(); await loadColorProperty(); } catch (e) { toast(e.message); }
}

function onNavigate(ev) {
  if (ev.bbox) fitBbox(ev.bbox);
  else if (ev.to_network) fitNetwork();
  else if (ev.to_selection) { const sel = activeSelection(store.get()); if (sel) fitLinks(sel.link_ids); }
}

function onLinkClick(linkId) {
  const s = store.get();
  if (!s.pickMode) { showLinkDetails(linkId); return; }
  const picks = new Set(s.picks);
  if (picks.has(linkId)) picks.delete(linkId); else picks.add(linkId);
  store.set({ picks });
}

function wireMapButtons() {
  $("btn-fitnet").onclick = () => fitNetwork();
  $("btn-fitsel").onclick = () => { const sel = activeSelection(store.get()); if (sel) fitLinks(sel.link_ids); };
  $("btn-pick").onclick = () => store.set({ pickMode: !store.get().pickMode });
}

function wireStore() {
  store.subscribe(["server", "net", "prop", "picks", "marker"], () => render());
  store.subscribe(["server"], s => {
    renderHeader(s.server); syncControls(s.server.style); renderSelection(activeSelection(s)); onSelectionChanged();
  });
  store.subscribe(["server", "prop"], s => renderLegend(s.server.style, s.prop));
  store.subscribe(["properties"], s => { populateColorby(s.properties); syncControls(s.server.style); });
  store.subscribe(["netKey"], () => { onNetworkChanged(); store.set({ picks: new Set() }); });
  store.subscribe(["picks"], s => renderPicks(s.picks));
  store.subscribe(["pickMode"], s => { $("btn-pick").classList.toggle("on", s.pickMode); $("map").classList.toggle("picking", s.pickMode); });
}

async function boot() {
  wireStore(); wirePanels(); wireSide(); wireTable(); wireHeader(); wireHistory(); wireMapButtons();
  const [cfg, server] = await Promise.all([getJSON("/api/config"), getJSON("/api/state")]);
  store.set({ server });
  restoreViewMode();
  initMap(cfg.style, {
    onLinkClick,
    onReady: async () => {
      await onState(store.get().server);
      subscribe({ state: e => onState(e.state), history: e => showEntry(e.entry), navigate: onNavigate });
    },
  });
}

boot().catch(e => toast(e.message));
```

- [ ] **Step 17: Run the static tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_static.py -q`
Expected: all pass. That is 12 parametrised "served" cases plus 4 others; the node test is skipped if node is absent. If `test_every_element_id_used_by_js_exists_in_index` fails, add the missing id to `index.html`, or fix the typo in the JS.

- [ ] **Step 18: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/static packages/gmnspy/tests/test_workbench_static.py
git commit -m "feat(workbench): modular no-build front end (store + SSE + history strip, viz parity)"
```

---

### Task 11: CLI `gmnspy app`, aliases, packaging

**Files:**
- Create: `packages/gmnspy/gmnspy/cli/commands/workbench.py`
- Modify: `packages/gmnspy/gmnspy/cli/commands/viz.py` (becomes an alias)
- Modify: `packages/gmnspy/gmnspy/cli/commands/select.py` (`select-serve` becomes an alias)
- Modify: `packages/gmnspy/gmnspy/cli/app.py` (register)
- Modify: `packages/gmnspy/gmnspy/select/webapp.py` (deprecation note in the module docstring)
- Modify: `packages/gmnspy/pyproject.toml` (wheel include)
- Test: `packages/gmnspy/tests/test_cli_workbench.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for `gmnspy app` and its viz / select-serve aliases."""

import pytest
from gmnspy.cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def served(monkeypatch, tmp_path):
    """Capture the session handed to serve() instead of starting uvicorn; isolate config."""
    monkeypatch.setenv("GMNSPY_CONFIG_DIR", str(tmp_path / "user"))
    monkeypatch.chdir(tmp_path)
    captured = []
    monkeypatch.setattr("gmnspy.workbench.serve", captured.append)
    return captured


def test_app_opens_sources_and_applies_flag_overrides(served, rdu_source):
    result = runner.invoke(app, ["app", rdu_source, "--port", "9301", "--basemap", "esri"])
    assert result.exit_code == 0, result.output
    (session,) = served
    assert session.registry.ids() == ["rdu-i40"]
    assert (session.settings.app.port, session.settings.viz.basemap) == (9301, "esri")
    assert session.loaded.sources["app.port"] == "session"
    assert "http://127.0.0.1:9301" in result.output


def test_app_with_no_sources_starts_empty(served):
    assert runner.invoke(app, ["app"]).exit_code == 0
    assert len(served[0].registry) == 0


def test_app_bad_source_exits_1(served, tmp_path):
    result = runner.invoke(app, ["app", str(tmp_path / "missing")])
    assert result.exit_code == 1 and "could not open" in result.output and served == []


def test_app_bad_flag_value_exits_2(served):
    result = runner.invoke(app, ["app", "--provider", "gpt"])
    assert result.exit_code == 2 and "invalid settings" in result.output


def test_viz_is_an_alias(served, rdu_source):
    result = runner.invoke(app, ["viz", rdu_source, "--port", "9302"])
    assert result.exit_code == 0 and "gmnspy app" in result.output
    assert served[0].settings.app.port == 9302


def test_select_serve_is_an_alias(served, rdu_source):
    result = runner.invoke(app, ["select-serve", rdu_source, "--provider", "stub"])
    assert result.exit_code == 0 and served[0].registry.ids() == ["rdu-i40"]
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_cli_workbench.py -q`
Expected: FAIL, with no such command `app`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/cli/commands/workbench.py`**

```python
"""``gmnspy app`` — the GMNSpy Workbench: map + tables + selection over one live session.

Requires the ``[server]`` extra. ``gmnspy viz`` and ``gmnspy select-serve`` are
aliases that call :func:`run_workbench`.
"""

from __future__ import annotations

from collections.abc import Sequence

import typer

__all__ = ["register", "run_workbench"]


def run_workbench(
    sources: Sequence[str],
    *,
    provider: str | None = None,
    basemap: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Build a session from settings + flag overrides, open ``sources``, and serve it (blocks)."""
    from gmnspy import workbench
    from gmnspy.config import SettingsError
    from gmnspy.workbench.actions import OpenNetwork

    flags = {"select.provider": provider, "viz.basemap": basemap, "app.host": host, "app.port": port}
    try:
        session = workbench.Session(overrides={k: v for k, v in flags.items() if v is not None})
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    for source in sources:
        try:
            session.dispatch(OpenNetwork(source=str(source)))
        except workbench.ActionError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
    app_settings = session.settings.app
    opened = ", ".join(session.registry.ids()) or "none (open one from the header)"
    typer.echo(f"GMNSpy Workbench on http://{app_settings.host}:{app_settings.port}  (networks: {opened})")
    workbench.serve(session)


def register(app: typer.Typer) -> None:
    """Register the ``app`` command on ``app``."""

    @app.command(name="app")
    def app_cmd(
        sources: list[str] = typer.Argument(None, help="GMNS network paths/URLs to open."),
        provider: str = typer.Option(None, "--provider", help="NL parser: stub | claude (default: settings)."),
        basemap: str = typer.Option(None, "--basemap", help="Basemap: positron | esri (default: settings)."),
        host: str = typer.Option(None, "--host", help="Bind host (default: settings, 127.0.0.1)."),
        port: int = typer.Option(None, "--port", help="Bind port (default: settings, 8850)."),
    ) -> None:
        """Serve the GMNSpy Workbench: open, inspect, and select on GMNS networks in the browser."""
        run_workbench(sources or [], provider=provider, basemap=basemap, host=host, port=port)
```

Note that `typer.Exit(2)` echoes the error. The test checks `result.output`, and CliRunner mixes stderr into `output` by default (`mix_stderr` defaults to True in the installed click). If the test can't see the message, switch the tests to `result.stdout + result.stderr`.

- [ ] **Step 4: Rewrite `packages/gmnspy/gmnspy/cli/commands/viz.py` as an alias**

```python
"""``gmnspy viz`` — alias of ``gmnspy app SOURCE`` (the viewer is now the GMNSpy Workbench)."""

from __future__ import annotations

from pathlib import Path

import typer

from .workbench import run_workbench

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the ``viz`` alias on ``app``."""

    @app.command(name="viz")
    def viz(
        source: Path = typer.Argument(..., help="Path/URL to a GMNS network."),
        provider: str = typer.Option(None, "--provider", help="NL parser: stub | claude."),
        engine: str = typer.Option(None, "--engine", help="Ignored: DuckDB is the only engine (kept for compatibility)."),
        basemap: str = typer.Option(None, "--basemap", help="Basemap: positron | esri (both keyless)."),
        host: str = typer.Option(None, "--host", help="Bind host."),
        port: int = typer.Option(None, "--port", help="Bind port."),
    ) -> None:
        """Serve the network viewer: now an alias of ``gmnspy app SOURCE``."""
        del engine  # accepted for backward compatibility only
        typer.echo("note: `gmnspy viz` is now `gmnspy app`", err=True)
        run_workbench([str(source)], provider=provider, basemap=basemap, host=host, port=port)
```

- [ ] **Step 5: Turn `select-serve` into an alias in `packages/gmnspy/gmnspy/cli/commands/select.py`**

Replace the whole `select_serve` function, from `@app.command(name="select-serve")` through its `uvicorn.run(...)` line, with:

```python
    @app.command(name="select-serve")
    def select_serve(
        source: Path = typer.Argument(..., help="Path/URL to a GMNS network."),
        provider: str = typer.Option(None, "--provider", help="Parser: stub | claude."),
        engine: str = typer.Option(None, "--engine", help="Ignored: DuckDB is the only engine (kept for compatibility)."),
        host: str = typer.Option(None, "--host", help="Bind host."),
        port: int = typer.Option(None, "--port", help="Bind port."),
    ) -> None:
        """Serve the interactive selection map: now an alias of ``gmnspy app SOURCE``."""
        from .workbench import run_workbench

        del engine  # accepted for backward compatibility only
        typer.echo("note: `gmnspy select-serve` is now `gmnspy app`", err=True)
        run_workbench([str(source)], provider=provider, host=host, port=port)
```

Then remove any imports that are now unused (`Network`, `resolve_engine`), but only if `ruff check` reports them unused; the `select` command may still use them.

- [ ] **Step 6: Register the command in `packages/gmnspy/gmnspy/cli/app.py`**

Add `workbench,` to the `from .commands import (...)` list, keeping it alphabetical after `viz`. Add `workbench.register(gmnspy_app)` directly after `viz.register(gmnspy_app)`.

- [ ] **Step 7: Mark `select/webapp.py` deprecated**

Append this paragraph to its module docstring:

```
Deprecated: ``gmnspy select-serve`` now launches the workbench
(:mod:`gmnspy.workbench`); this prototype is removed in P1.
```

- [ ] **Step 8: Ship the static assets in the wheel**

In `packages/gmnspy/pyproject.toml`, under `[tool.hatch.build.targets.wheel] include`, add these lines after `"gmnspy/viz/templates/*.html",`:

```toml
    # GMNSpy Workbench static front end (gmnspy.workbench; served by `gmnspy app`).
    "gmnspy/workbench/static/*.html",
    "gmnspy/workbench/static/*.css",
    "gmnspy/workbench/static/js/*.js",
```

- [ ] **Step 9: Run the CLI tests and the CLI/doc contract tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_cli_workbench.py packages/gmnspy/tests/test_documented_cli_contract.py packages/gmnspy/tests/test_cli.py -q`
Expected: all pass.

- [ ] **Step 10: Check the wheel contains the assets**

```bash
uv build --wheel packages/gmnspy -o /tmp/claude-wheel-check && unzip -l /tmp/claude-wheel-check/gmnspy-*.whl | grep workbench/static
```

Expected: 14 lines: `index.html`, `app.css` and 12 `js/*.js` files.

- [ ] **Step 11: Commit**

```bash
uv run ruff check packages/gmnspy && uv run ruff format packages/gmnspy/gmnspy/cli packages/gmnspy/tests/test_cli_workbench.py
git add packages/gmnspy/gmnspy/cli packages/gmnspy/gmnspy/select/webapp.py packages/gmnspy/pyproject.toml packages/gmnspy/tests/test_cli_workbench.py
git commit -m "feat(cli): gmnspy app (workbench); viz + select-serve become aliases; ship static assets"
```

---

### Task 12: Docs page, full suite, and end-to-end browser check

**Files:**
- Create: `packages/gmnspy/docs/cookbook/workbench.md`
- Modify: `packages/gmnspy/mkdocs.yml` (nav)
- Modify: `packages/gmnspy/docs/cookbook/index.md` (link)

- [ ] **Step 1: Write `packages/gmnspy/docs/cookbook/workbench.md`**

````markdown
---
title: Explore networks in the GMNSpy Workbench
audience: users
kind: howto
summary: Open one or more GMNS networks in a local browser app. The map and tables are linked, natural-language selection is built in, and every action can be replayed as Python.
---

# Explore networks in the GMNSpy Workbench

## When to use this

You want to look around a network interactively. That means panning the map, browsing tables, checking
what a selection phrase resolves to, and copying the exact Python that reproduces what you did.
For a single self-contained HTML file to send someone, see [View a network on a map](view-your-network.md).

## Quick start

```bash
uv run gmnspy app ./my-network
```

Open <http://127.0.0.1:8850>. You can open more networks from the header (a path or URL) and switch between
them with the network picker. `gmnspy viz` and `gmnspy select-serve` are aliases of `gmnspy app`.

```bash
uv run gmnspy app ./base ./build --port 8900 --basemap esri --provider claude
```

## Settings

The workbench reads layered settings. From lowest to highest precedence:

1. built-in defaults
2. `~/.config/gmnspy/config.toml`
3. `./gmnspy.toml`
4. `GMNSPY_<SECTION>__<FIELD>` environment variables
5. command-line flags

```toml
# ./gmnspy.toml
[app]
port = 8900

[viz]
basemap = "esri"

[select]
provider = "claude"
```

## Every action is replayable

Everything you do in the browser is a typed action: open, select, style, navigate, change a setting.
The strip at the bottom shows the last action as Python. **Session as Python** shows the whole session as
a script you can copy.
````

- [ ] **Step 2: Add the page to the nav and the cookbook index**

In `packages/gmnspy/mkdocs.yml`, under `- Cookbook:`, add this line directly after `- View a network on a map: cookbook/view-your-network.md`:

```yaml
      - Explore in the Workbench: cookbook/workbench.md
```

In `packages/gmnspy/docs/cookbook/index.md`, add the bullet `- [Explore networks in the GMNSpy Workbench](workbench.md)` next to the "View a network on a map" entry, matching that list's format.

- [ ] **Step 3: Run the full gmnspy suite and lint**

Run: `uv run --all-extras pytest packages/gmnspy -q && uv run ruff check packages && uv run ruff format --check packages`
Expected: all tests pass (including both documented-contract tests, which scan the new page) and lint is clean.

- [ ] **Step 4: Check the app end to end in the browser pane**

Create `.claude/launch.json` (do not commit it) with:

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "workbench",
      "runtimeExecutable": "uv",
      "runtimeArgs": ["run", "--all-extras", "gmnspy", "app", "packages/gmnspy/gmnspy/fixtures/rdu_i40/parquet", "--port", "8850"],
      "port": 8850
    }
  ]
}
```

Start it with `preview_start` (`name: "workbench"`). Then check each item, using `read_console_messages` for errors and screenshots for visuals:

1. The map fits to the RDU network. The header shows `rdu_i40` and `178 links · 143 nodes`. The console has no errors.
2. Type `I-40 EB between South Miami Boulevard and Airport Boulevard` and press Enter:
   - the selection highlights, with green/red anchors;
   - the status reads "resolved";
   - the history strip shows `app.do(Select(utterance='I-40 EB …'))`.
3. Switch to Split view, choose the `link` table, and turn on "Filter to map selection". Only the selected rows are listed and they are highlighted. Click a row: the map zooms to that link and Link details fills in.
4. In Layers, set Color by to `lanes`. The ramp row and legend appear, and the history strip shows a `Style(color_by='lanes')` entry.
5. Turn on Pick, click two links, then press "Select picked". The selection replaces the old one, and the Fragment panel shows JSON.
6. Type the same fixture path in the Open box. A second network, labelled `rdu-i40-2`, appears in the picker. Switching to it reloads the map.
7. Click **Session as Python**. The panel lists every action in order.
8. Run `curl -s -XPOST localhost:8850/api/actions -H 'content-type: application/json' -d '{"type":"style","show":{"nodes":false}}'` from a terminal. The nodes disappear in the open browser with no reload, which proves server→browser SSE push.

Stop the preview with `preview_stop`. Record any defects as new failing tests or fixes before continuing.

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/docs/cookbook/workbench.md packages/gmnspy/mkdocs.yml packages/gmnspy/docs/cookbook/index.md
git commit -m "docs(gmnspy): Workbench cookbook page (gmnspy app, settings layers, replayable actions)"
```

---

## Self-review notes (completed while writing)

- **Spec coverage (P0 row):**
  - `config.py`: Tasks 1–2.
  - Session, Registry, Action bus, SSE: Tasks 4–8.
  - ES-module front end at viz parity: Task 10.
  - `gmnspy app` and the retired `select-serve`/`viz`: Task 11.
  - The transit slot (bundle, `{component}` routes, `Select.component`, `NotSupportedYet`): Tasks 4, 6, 7, 9.
  - Deferred items are listed under Scope notes, and the design doc's phasing row has been amended to match.
- **Type consistency:**
  - `Session.dispatch` and `dispatch_recorded`, `HistoryEntry.to_dict`, and the `NetworkHandle` methods (`links_df`, `nodes_df`, `node_xy`, `tables`, `cached`, `bump`, `summary`) are used the same way in Tasks 7–9.
  - The JS exports imported by `main.js` all exist; `test_relative_imports_resolve_to_real_exports` enforces this.
- **Known follow-ups for P1:**
  - delete `viz/server.py`, `select/webapp.py` and their tests;
  - the Settings UI form over `/api/settings`;
  - background jobs and Build;
  - the basemap setting needs a page reload to take effect.
