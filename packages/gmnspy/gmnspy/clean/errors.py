"""Typed exceptions for :mod:`gmnspy.clean`."""

from __future__ import annotations

from datagrove.editing import EditingError

__all__ = ["CleanError"]


class CleanError(EditingError):
    """A :mod:`gmnspy.clean` op cannot complete on the given inputs.

    Subclass of :class:`datagrove.editing.EditingError` so generic
    editing-error handlers still catch it. Raised for missing required
    tables, malformed geometry, or invalid op parameters.
    """
