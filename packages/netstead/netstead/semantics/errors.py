"""Typed exceptions for :mod:`netstead.semantics`."""

from __future__ import annotations

from netstead.network import NetworkError

__all__ = ["SemanticsError"]


class SemanticsError(NetworkError):
    """A GMNS-semantics operation cannot be performed on the given network.

    Subclass of :class:`netstead.NetworkError` so generic handlers still
    catch it, while callers that care about the source of the failure
    (connectivity vs. geometry vs. TOD) can branch on the more specific
    type.
    """
