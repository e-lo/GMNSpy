"""Import an optional-extra module at runtime (``[osm]``, ``[overture]``), as a user-facing error if missing.

Runtime :func:`importlib.import_module` rather than a static import keeps the import-linter contract
"gmnspy core (incl. ``gmnspy.cli``, which imports the workbench) must not require optional extras".
"""

from __future__ import annotations

import importlib
from types import ModuleType

from .errors import ActionError

__all__ = ["optional_module"]


def optional_module(name: str, extra: str) -> ModuleType:
    """Return module ``name``, or raise :class:`ActionError` naming the extra to install."""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise ActionError(f"this needs the [{extra}] extra: pip install 'gmnspy[{extra}]' ({exc})") from exc
