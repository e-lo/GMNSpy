"""Workbench session: the one place state changes, via :meth:`Session.dispatch`.

UI clicks (``POST /api/actions``), Python (``session.dispatch(...)``), and, in
P3, the NL assistant all funnel through ``dispatch``. Each call is recorded as a
:class:`HistoryEntry` carrying its ``to_python`` replay snippet, and publishes
``history`` + ``state`` events for the browser. Network *edits* are not actions
here yet: in P2 they become ProjectCard-shaped ``NetworkChange`` objects.
"""

from __future__ import annotations

import copy
import logging
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
from .errors import ActionError, NotSupportedYet
from .events import EventBus
from .registry import NetworkHandle, NetworkRegistry
from .selection import selection_payload, unparsed_payload

__all__ = ["DEFAULT_STYLE", "ActionError", "HistoryEntry", "NotSupportedYet", "Session"]

logger = logging.getLogger(__name__)

DEFAULT_STYLE: dict[str, Any] = {
    "color_by": "none",
    "ramp": "YlOrRd",
    "offset": True,
    "show_direction": False,
    "show_legend": True,
    "show": {"links": True, "nodes": True, "labels": True, "selection": True},
    "colors": {"links": [46, 64, 110], "nodes": [70, 90, 120], "selection": [255, 140, 59]},
}


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
            except Exception as exc:  # boundary: an unexpected handler failure is still a recorded, user-facing error
                logger.exception("workbench action %s failed", action.type)
                error = f"internal error: {type(exc).__name__}: {exc}"
                result, ok, error_type = None, False, "InternalError"
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
            self.events.publish({"type": "history", "entry": entry.to_dict()})
            if ok:
                self.events.publish({"type": "state", "state": self.state()})
        return entry

    def add_network(
        self, net: Network, *, source: str = "<python>", label: str | None = None, net_id: str | None = None
    ) -> NetworkHandle:
        """Register an already-loaded ``Network`` (the Python path; not an Action because it isn't JSON)."""
        with self._lock:
            handle = self.registry.add(net, source=source, label=label, net_id=net_id)
            self.active = self.active or handle.id
            self.events.publish({"type": "state", "state": self.state()})
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
            _ = (net.links, net.nodes)  # from_source is lazy; force the required tables to surface a bad source now
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
