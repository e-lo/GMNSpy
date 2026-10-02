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
