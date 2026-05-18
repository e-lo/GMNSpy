"""Structured exceptions for the ``datagrove.spec`` package.

Per the architecture conventions (architecture.md section 9), every
module uses specific exception subclasses rather than bare
:class:`ValueError`. Both the loader and the version parser route
failures through these types so callers can catch a single base class
(:class:`SpecLoadError`) for any spec-loading failure regardless of
which submodule raised it.
"""

from __future__ import annotations

__all__ = ["InvalidSpecVersionError", "SpecLoadError"]


class SpecLoadError(Exception):
    """Raised when a data-package or schema cannot be loaded.

    The message always includes the source identifier (path, URL, or
    ``"<dict>"``) and a short description of what went wrong. Where
    relevant, the underlying exception is chained as ``__cause__``.

    Examples:
        >>> try:
        ...     raise SpecLoadError("oops at /tmp/missing.json")
        ... except SpecLoadError as e:
        ...     "missing.json" in str(e)
        True
    """


class InvalidSpecVersionError(SpecLoadError):
    """Raised when a string cannot be parsed as a :class:`SpecVersion`.

    Subclasses :class:`SpecLoadError` so that catch-all
    spec-loading handlers (``except SpecLoadError``) still see version
    parse failures, while callers that care specifically about version
    strings can catch the narrower type.

    Examples:
        >>> try:
        ...     raise InvalidSpecVersionError("bad version: 'x.y'")
        ... except SpecLoadError:
        ...     True
        True
    """
