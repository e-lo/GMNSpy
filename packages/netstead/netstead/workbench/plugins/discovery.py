"""Find installed Workbench plugins via the ``netstead.workbench.plugins`` entry-point group.

Mirrors :mod:`corral.quality.registry`: each entry point loads in isolation, so one broken plugin is
recorded (a :class:`PluginStatus` with ``state="error"``) and skipped, never fatal. Disabled entry
points are skipped *before* they are imported.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable
from dataclasses import asdict, dataclass
from importlib.metadata import entry_points
from typing import Any, Literal

from .spec import WorkbenchPlugin

__all__ = ["ENTRY_POINT_GROUP", "PluginState", "PluginStatus", "discover"]

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "netstead.workbench.plugins"

PluginState = Literal["loaded", "disabled", "incompatible", "error"]


@dataclass(frozen=True)
class PluginStatus:
    """What happened to one plugin at startup (shown in the Plugins settings section)."""

    id: str
    name: str
    version: str
    requires_api: str | None
    state: PluginState
    error: str | None = None
    frontend: str | None = None  # URL of the plugin's ES module, when it ships one

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe copy."""
        return asdict(self)


def discover(
    disabled: Collection[str] = (), *, eps: Iterable[Any] | None = None
) -> tuple[list[WorkbenchPlugin], list[PluginStatus]]:
    """Load every plugin entry point except ``disabled`` ones: ``(plugins, statuses of the ones skipped)``.

    ``eps`` replaces the installed entry points (tests). A loaded plugin gets its status when it is
    installed (:meth:`netstead.workbench.session.Session`), which runs the remaining checks.
    """
    found: list[WorkbenchPlugin] = []
    statuses: list[PluginStatus] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP) if eps is None else eps:
        if ep.name in disabled:
            statuses.append(PluginStatus(ep.name, ep.name, "", None, "disabled"))
            continue
        try:
            plugin = ep.load()()
            if not isinstance(plugin, WorkbenchPlugin):
                raise TypeError(f"entry point {ep.name!r} returned {type(plugin).__name__}, not a WorkbenchPlugin")
            if plugin.id != ep.name:
                raise ValueError(f"entry point name {ep.name!r} must equal the plugin id {plugin.id!r}")
        except Exception as exc:  # boundary: third-party code; one bad plugin must not stop the app
            logger.exception("loading workbench plugin %r failed", ep.name)
            statuses.append(PluginStatus(ep.name, ep.name, "", None, "error", f"{type(exc).__name__}: {exc}"))
            continue
        found.append(plugin)
    return found, statuses
