"""Optional-extra import helper for gmnspy CLI commands.

Replaces the 5 sites that called ``importlib.import_module()`` with their
own divergent error-handling. One helper, one consistent error message,
one place to add caching / dev-time warnings later.

This lives in :mod:`gmnspy.cli` (not ``gmnspy.clean`` / ``gmnspy.server`` /
``gmnspy.mcp``) so the import-linter contract
``gmnspy.cli ↛ gmnspy.{clean,server,mcp}`` keeps holding — the import-linter
scans static imports only, so runtime discovery via :func:`importlib.import_module`
is the architecture-blessed way to thread a CLI entry point into an optional
submodule.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import typer

__all__ = ["require_extra"]


def require_extra(module_name: str, extra_name: str) -> ModuleType:
    """Import ``module_name`` or exit the CLI with a helpful install hint.

    Replaces the prior pattern of inline ``try/except ImportError`` in each
    command (which diverged across 5 sites — some printed ``clean`` even for
    ``server`` imports). Centralising this means future enhancements (caching,
    version probes, dev-time warnings) land in exactly one place.

    Args:
        module_name: The submodule (e.g. ``"gmnspy.server"``,
            ``"gmnspy.clean"``).
        extra_name: The pip extra to suggest (e.g. ``"server"``,
            ``"clean"``).

    Returns:
        The imported module.

    Raises:
        typer.Exit: With code 1 and a red error printed to stderr when
            the import fails. The error message tells the user exactly
            which extra to install.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        typer.secho(
            f"{module_name} requires the [{extra_name}] extra: pip install 'gmnspy[{extra_name}]' ({e})",
            fg="red",
            err=True,
        )
        raise typer.Exit(code=1) from None
