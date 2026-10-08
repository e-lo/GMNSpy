"""Typed workbench Actions: the one vocabulary for UI clicks, Python, and the NL assistant.

Every state change in a :class:`~netstead.workbench.session.Session` is one of these
pydantic models, discriminated on ``type``. The same JSON schema is what the LLM
sees as tools (P3), so natural language yields validated Actions, never ids or
code. ``mutates`` marks actions the assistant must draft-before-apply;
``runs_as_job`` marks actions whose slow work runs on a background job thread
(see :mod:`netstead.workbench.jobs`); ``replay_overrides`` are fields forced in
the ``to_python`` replay snippet.
"""

from __future__ import annotations

import functools
import operator
import re
from collections.abc import Iterable, Iterator, Mapping
from pathlib import PurePath
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from netstead.llm.secrets import looks_like_secret

from .area import Area
from .registry import Component, default_label

__all__ = [
    "CORE_ACTIONS",
    "Action",
    "ActionRegistry",
    "BaseAction",
    "BuildNetwork",
    "ClearSelection",
    "CloseNetwork",
    "Navigate",
    "OpenNetwork",
    "Select",
    "SetActiveNetwork",
    "SetSetting",
    "Style",
    "action_json_schema",
    "import_line",
    "is_secret_name",
    "parse_action",
    "script_imports",
    "to_python",
]

RGB = Annotated[list[Annotated[int, Field(ge=0, le=255)]], Field(min_length=3, max_length=3)]


class BaseAction(BaseModel):
    """Base class for every Workbench Action, core and plugin.

    A subclass declares ``type: Literal["<type>"] = "<type>"`` (plugins: ``"<plugin id>.<name>"``)
    and its fields. ``mutates`` marks actions the assistant must draft before applying;
    ``runs_as_job`` (core only) runs the slow work on a background job thread; ``replay_overrides``
    are fields forced in the ``to_python`` replay snippet.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)  # errors never echo a value (keys)
    mutates: ClassVar[bool] = False
    runs_as_job: ClassVar[bool] = False
    replay_overrides: ClassVar[dict[str, Any]] = {}
    if TYPE_CHECKING:  # every concrete Action declares its own ``type`` field; not a field of the base
        type: str

    @classmethod
    def action_type(cls) -> str | None:
        """The ``type`` discriminator this class carries (``None`` when it declares none)."""
        field_info = cls.model_fields.get("type")
        default = field_info.default if field_info is not None else None
        return default if isinstance(default, str) and default else None

    def job_label(self) -> str:
        """The label a ``runs_as_job`` action's background job shows in the jobs panel."""
        return self.type.replace("_", " ")


class OpenNetwork(BaseAction):
    """Load a GMNS network from a local path (inside ``io.allowed_roots``) or URL and make it active."""

    type: Literal["open_network"] = "open_network"
    runs_as_job: ClassVar[bool] = True
    source: str
    label: str | None = None
    net_id: str | None = None

    def job_label(self) -> str:
        """``open <name>``, named after the source."""
        return f"open {default_label(self.source)}"


class CloseNetwork(BaseAction):
    """Close an open network."""

    type: Literal["close_network"] = "close_network"
    net_id: str


class SetActiveNetwork(BaseAction):
    """Switch which open network the map and tables show."""

    type: Literal["set_active_network"] = "set_active_network"
    net_id: str


class Select(BaseAction):
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


class ClearSelection(BaseAction):
    """Clear the current selection."""

    type: Literal["clear_selection"] = "clear_selection"


class Style(BaseAction):
    """Partially update the map style; omitted fields are unchanged."""

    type: Literal["style"] = "style"
    color_by: str | None = None
    ramp: Literal["YlOrRd", "Blues", "Viridis"] | None = None
    show: dict[Literal["links", "nodes", "labels", "selection"], bool] | None = None
    colors: dict[Literal["links", "nodes", "selection"], RGB] | None = None
    offset: bool | None = None
    show_direction: bool | None = None
    show_legend: bool | None = None


class Navigate(BaseAction):
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


class SetSetting(BaseAction):
    """Change a setting (dotted key) for this session, or persist it to the user/project file.

    Refuses API-key-shaped values *at validation*, before anything is recorded: keys are set
    through the write-only ``/api/llm/keys`` route (or ``netstead llm set-key``), never as settings.
    (``io.allowed_roots`` is refused later, by the session, at every scope.)
    """

    type: Literal["set_setting"] = "set_setting"
    mutates: ClassVar[bool] = True
    key: str
    value: Any = None
    scope: Literal["session", "user", "project"] = "session"

    @model_validator(mode="after")
    def _no_secrets(self) -> SetSetting:
        # Messages never echo the key or value; ``hide_input_in_errors`` keeps pydantic's own text clean too.
        if looks_like_secret(self.key) or looks_like_secret(self.value):
            raise ValueError(
                "that value looks like an API key; set keys in Settings → Language models (they are never settings)"
            )
        names = [self.key.rsplit(".", 1)[-1], *_nested_keys(self.value)]
        if any(is_secret_name(n) for n in names):
            raise ValueError(
                "keys, tokens and passwords are never settings; set API keys in Settings → Language models"
            )
        if any(_URL_USERINFO.match(text) for text in (self.key, *_strings(self.value))):
            raise ValueError("URLs in settings must not contain a username, password or token")
        base_urls = [self.value] if names[0] == "base_url" else []
        base_urls += _values_under(self.value, "base_url")
        if any(isinstance(u, str) and ("?" in u or "#" in u) for u in base_urls):
            raise ValueError("base_url must not contain a query string or fragment")
        return self


#: Setting names that could only hold a credential (last key segment, or any key nested in the value).
_SECRET_NAME = re.compile(
    r"(?i)(^|[_.-])(api_?key|key|token|secret|password|passwd|authorization|bearer|credential)s?$"
)
#: Legitimate names that match :data:`_SECRET_NAME`: ``credentials`` only names keyring hosts;
#: ``key_env`` names env vars.
_SECRET_NAME_ALLOWED = frozenset({"credentials", "key_env"})


def is_secret_name(name: str) -> bool:
    """Whether a setting named ``name`` could only hold a credential (``api_key``, ``token``, ...).

    >>> is_secret_name("api_key"), is_secret_name("credentials"), is_secret_name("basemap")
    (True, False, False)
    """
    return bool(_SECRET_NAME.search(name)) and name.lower() not in _SECRET_NAME_ALLOWED


#: ``scheme://user[:pass]@`` at the start of a string: a URL carrying credentials.
_URL_USERINFO = re.compile(r"^\s*[A-Za-z][A-Za-z0-9+.-]*://[^/?#@]*@")


def _nested_keys(value: Any) -> Iterator[str]:
    """Every dict key nested anywhere in ``value``."""
    if isinstance(value, Mapping):
        for k, v in value.items():
            yield str(k)
            yield from _nested_keys(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _nested_keys(v)


def _strings(value: Any) -> Iterator[str]:
    """Every string in ``value``, dict keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _strings(v)


def _values_under(value: Any, name: str) -> Iterator[Any]:
    """Every value stored under a dict key ``name`` anywhere in ``value``."""
    if isinstance(value, Mapping):
        for k, v in value.items():
            if k == name:
                yield v
            yield from _values_under(v, name)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _values_under(v, name)


#: Name suffixes that imply an output format; a ``BuildNetwork.name`` ending in one must match it.
_OUTPUT_SUFFIXES = frozenset({".zip", ".duckdb", ".csv", ".parquet"})


class BuildNetwork(BaseAction):
    """Build a GMNS network from OSM or Overture, write it to ``output_dir``, then open it from disk.

    Give exactly one of ``area`` (fetch from the service) or ``input_file`` (a local ``.osm`` /
    Overpass ``.json`` for OSM, or a local snapshot folder for Overture). Without ``approved``, a
    build whose estimate is over ``app.approve_above_s``, or cannot be estimated, fails with
    :class:`~netstead.workbench.errors.ApprovalRequired` (carrying the estimate). A replayed snippet
    always passes ``approved=True``: re-running a recorded build counts as approval.
    """

    type: Literal["build_network"] = "build_network"
    mutates: ClassVar[bool] = True
    runs_as_job: ClassVar[bool] = True
    replay_overrides: ClassVar[dict[str, Any]] = {"approved": True}
    source: Literal["osm", "overture"]
    area: Area | None = None
    input_file: str | None = None
    output_dir: str
    output_format: Literal["parquet", "csv", "duckdb", "zip"]
    name: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9_-])?$", max_length=100)
    network_type: str = "drive"
    extra_tags: list[str] | None = None
    spec_version: str | None = None
    overture_release: str | None = None
    label: str | None = None
    approved: bool = False

    @model_validator(mode="after")
    def _one_input(self) -> BuildNetwork:
        if (self.area is None) == (self.input_file is None):
            raise ValueError("give exactly one of area or input_file")
        if self.overture_release is not None and self.source != "overture":
            raise ValueError("overture_release only applies to source='overture'")
        suffix = PurePath(self.name).suffix.lower()
        if suffix in _OUTPUT_SUFFIXES and suffix != f".{self.output_format}":
            raise ValueError(f"name {self.name!r} ends in {suffix} but output_format is {self.output_format!r}")
        return self

    def job_label(self) -> str:
        """``build <name>``, named after the output."""
        return f"build {self.name}"


Action = Annotated[
    OpenNetwork
    | BuildNetwork
    | CloseNetwork
    | SetActiveNetwork
    | Select
    | ClearSelection
    | Style
    | Navigate
    | SetSetting,
    Field(discriminator="type"),
]
#: The Actions every session understands, in registry order (``to_python`` imports them from ``netstead.workbench``).
CORE_ACTIONS: tuple[type[BaseAction], ...] = (
    OpenNetwork,
    BuildNetwork,
    CloseNetwork,
    SetActiveNetwork,
    Select,
    ClearSelection,
    Style,
    Navigate,
    SetSetting,
)


class ActionRegistry:
    """The Action types one session understands: the core ones plus any its plugins register."""

    def __init__(self, models: Iterable[type[BaseAction]] = CORE_ACTIONS) -> None:
        """Start with ``models`` registered (default: :data:`CORE_ACTIONS`)."""
        self._models: dict[str, type[BaseAction]] = {}
        self._adapter: TypeAdapter[Any] | None = None
        for model in models:
            self.register(model)

    def register(self, model: type[BaseAction]) -> None:
        """Add ``model``; raises ``TypeError`` for a non-Action, ``ValueError`` for a missing or taken ``type``."""
        if not (isinstance(model, type) and issubclass(model, BaseAction)):
            raise TypeError(f"{model!r} is not a BaseAction subclass")
        action_type = model.action_type()
        if action_type is None:
            raise ValueError(f"{model.__name__} needs a `type: Literal[...]` field with a default")
        if action_type in self._models:
            raise ValueError(f"action type {action_type!r} is already registered")
        self._models[action_type] = model
        self._adapter = None

    def has(self, action_type: str) -> bool:
        """Whether ``action_type`` is registered."""
        return action_type in self._models

    def types(self) -> list[str]:
        """Registered types, in registration order."""
        return list(self._models)

    def model(self, action_type: str) -> type[BaseAction]:
        """The class registered for ``action_type`` (``KeyError`` if none)."""
        return self._models[action_type]

    def parse(self, data: Mapping[str, Any]) -> BaseAction:
        """Validate a JSON dict into a registered Action (raises ``pydantic.ValidationError``)."""
        return self._get_adapter().validate_python(data)

    def json_schema(self) -> dict[str, Any]:
        """JSON schema of every registered Action (the assistant's tool vocabulary)."""
        return self._get_adapter().json_schema()

    def _get_adapter(self) -> TypeAdapter[Any]:
        if self._adapter is None:
            union = functools.reduce(operator.or_, self._models.values())
            self._adapter = TypeAdapter(
                Annotated[union, Field(discriminator="type")], config=ConfigDict(hide_input_in_errors=True)
            )
        return self._adapter


#: The core-only registry behind the module-level helpers (a session has its own, see ``Session.actions``).
_CORE_REGISTRY = ActionRegistry()


def parse_action(data: dict[str, Any]) -> Action:
    """Validate a JSON dict into a core Action (raises ``pydantic.ValidationError``)."""
    return _CORE_REGISTRY.parse(data)  # type: ignore[return-value]  # core registry: always a core Action


def action_json_schema() -> dict[str, Any]:
    """JSON schema of the core Action union (the assistant's tool vocabulary)."""
    return _CORE_REGISTRY.json_schema()


def import_line(action: BaseAction) -> str:
    """The ``from ... import ...`` line a replayed ``to_python`` snippet needs for ``action``."""
    return _import_line(type(action))


def _import_line(cls: type[BaseAction]) -> str:
    module = "netstead.workbench" if cls in CORE_ACTIONS else cls.__module__
    return f"from {module} import {cls.__name__}"


def script_imports(lines: Iterable[str]) -> list[str]:
    """The import lines heading a replayed session script, given its entries' :func:`import_line` values.

    The first line is always ``Session`` plus every core Action from ``netstead.workbench`` (so a
    core-only script is unchanged from before plugins existed); each other line follows once, in order.

    >>> script_imports(["from netstead.workbench import Select", "from hello import Greet"])[1:]
    ['from hello import Greet']
    """
    core = {_import_line(model) for model in CORE_ACTIONS}
    head = ", ".join(["Session", *(model.__name__ for model in CORE_ACTIONS)])
    return [f"from netstead.workbench import {head}", *dict.fromkeys(ln for ln in lines if ln not in core)]


def to_python(action: BaseAction) -> str:
    """The Python call that replays ``action`` against a live workbench handle named ``app``.

    Top-level fields equal to their default are omitted; nested models (an ``area``) are written
    in full, so their discriminator survives. ``replay_overrides`` are applied last.
    """
    defaults = {name: f.get_default(call_default_factory=True) for name, f in type(action).model_fields.items()}
    fields = {k: v for k, v in action.model_dump(exclude={"type"}).items() if v != defaults[k]}
    fields.update(type(action).replay_overrides)
    args = ", ".join(f"{k}={v!r}" for k, v in fields.items())
    return f"app.do({type(action).__name__}({args}))"
