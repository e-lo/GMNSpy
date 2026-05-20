"""Typed exceptions for :mod:`gmnspy.scope`."""

from __future__ import annotations

from gmnspy.network import NetworkError

__all__ = ["ScopeError"]


class ScopeError(NetworkError):
    """A network-aware scope op cannot complete on the given inputs.

    Raised for unknown seed ids, missing required tables (e.g.
    ``from_zone`` with no ``node.zone_id`` column), or invalid
    distance arguments. Subclasses :class:`gmnspy.NetworkError` so
    generic handlers still catch it.
    """
