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


class BuildSettings(_Section):
    """Defaults the Open / Import wizard prefills for OSM and Overture builds."""

    network_type: str = "drive"
    buffer_m: float = Field(default=1000.0, gt=0)
    extra_tags: list[str] = Field(default_factory=list)


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
    approve_above_s: float = Field(default=90.0, ge=0)


class CredentialSettings(_Section):
    """Names of hosts whose secrets live in keyring. Never the secrets themselves."""

    keyring_hosts: list[str] = Field(default_factory=list)


class Settings(_Section):
    """All user-tunable gmnspy settings."""

    io: IOSettings = Field(default_factory=IOSettings)
    engine: EngineSettings = Field(default_factory=EngineSettings)
    osm: OSMSettings = Field(default_factory=OSMSettings)
    overture: OvertureSettings = Field(default_factory=OvertureSettings)
    build: BuildSettings = Field(default_factory=BuildSettings)
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
