"""Editing-framework typed errors (per architecture §9)."""

from __future__ import annotations


class EditingError(Exception):
    """Base class for every error raised by :mod:`datagrove.editing`."""


class UnsupportedEditOp(EditingError):
    """Raised when an :class:`Edit.op` isn't in the apply dispatch table."""


class UnknownTable(EditingError):
    """Raised when an :class:`Edit.table` isn't in the target :class:`Package`."""


class InvalidPayload(EditingError):
    """Raised when an :class:`Edit.payload` is missing a required key for its op."""


class RollbackError(EditingError):
    """Raised when a rollback can't be applied (corrupt log, missing data, etc.)."""
