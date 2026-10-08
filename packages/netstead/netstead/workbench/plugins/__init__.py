"""Workbench plugins: separately installed packages that add Actions, routes, settings, state and UI.

A plugin package exposes a zero-argument factory returning a :class:`WorkbenchPlugin` under the
``netstead.workbench.plugins`` entry-point group (the entry-point name must equal the plugin id).
Plugins import only what this package exports. See the cookbook page "Write a Workbench plugin".
"""

from ..actions import BaseAction
from .spec import HOST_API, ActionSpec, WorkbenchPlugin

__all__ = ["HOST_API", "ActionSpec", "BaseAction", "WorkbenchPlugin"]
