"""Typed exceptions for :mod:`gmnspy.semantics`."""

from __future__ import annotations

from gmnspy.network import NetworkError

__all__ = ["SemanticsError"]


class SemanticsError(NetworkError):
    """A GMNS-semantics operation cannot be performed on the given network.

    Subclass of :class:`gmnspy.NetworkError` so generic handlers still
    catch it, while callers that care about the source of the failure
    (connectivity vs. geometry vs. TOD) can branch on the more specific
    type.
    """
