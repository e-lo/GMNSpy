"""Typed exceptions for :mod:`netstead.clean`."""

from __future__ import annotations

from corral.editing import EditingError

__all__ = ["CleanError"]


class CleanError(EditingError):
    """A :mod:`netstead.clean` op cannot complete on the given inputs.

    Subclass of :class:`corral.editing.EditingError` so generic
    editing-error handlers still catch it. Raised for missing required
    tables, malformed geometry, or invalid op parameters.
    """
