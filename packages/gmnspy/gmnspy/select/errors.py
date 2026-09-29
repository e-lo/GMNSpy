"""Typed errors for the natural-language selection pipeline."""
from __future__ import annotations

__all__ = ["SelectError", "IntentError", "FacilityNotFound", "AnchorNotFound", "NoPathError"]


class SelectError(Exception):
    """Base class for gmnspy.select errors."""


class IntentError(SelectError, ValueError):
    """A SelectionIntent is structurally invalid."""


class FacilityNotFound(SelectError):
    """No links matched the requested facility ref/name."""


class AnchorNotFound(SelectError):
    """An anchor could not be resolved to a node on the facility."""


class NoPathError(SelectError):
    """No connected path exists between the resolved anchor nodes."""
