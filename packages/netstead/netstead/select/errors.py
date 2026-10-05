"""Typed errors for the natural-language selection pipeline."""

from __future__ import annotations

__all__ = ["AnchorNotFound", "FacilityNotFound", "IntentError", "NoPathError", "SelectError"]


class SelectError(Exception):
    """Base class for netstead.select errors."""


class IntentError(SelectError, ValueError):
    """A SelectionIntent is structurally invalid."""


class FacilityNotFound(SelectError):
    """No links matched the requested facility ref/name."""


class AnchorNotFound(SelectError):
    """An anchor could not be resolved to a node on the facility."""


class NoPathError(SelectError):
    """No connected path exists between the resolved anchor nodes."""
