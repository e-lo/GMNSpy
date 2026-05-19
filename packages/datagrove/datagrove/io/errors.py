"""Structured exceptions raised by the datagrove I/O layer.

Per ``docs/architecture.md`` §9 ("structured exceptions in
errors.py; use specific subclasses, not bare ``ValueError``"), I/O
modules raise these typed subclasses instead of bare built-ins. The
mirror module for the engine layer is :mod:`datagrove.engines.errors`.

The four "format" exceptions used by the registry and dispatcher
(:class:`FormatError`, :class:`FormatNotDetected`,
:class:`AdapterNotAvailableError`, :class:`InvalidAdapterError`) are
defined in :mod:`datagrove.io.base` and re-exported here so that all
io-layer exception types live behind one import. Importing the
canonical name from :mod:`datagrove.io.base` continues to work — both
paths point at the same class objects.

The one new exception introduced by this module is
:class:`WriteUnsupportedForSchemeError`: a typed marker for
"this URL scheme refuses writes" (today only ``http(s)://``). It
inherits from :class:`FormatError` so catching ``FormatError`` continues
to catch every I/O exception.
"""

from __future__ import annotations

from datagrove.io.base import (
    AdapterNotAvailableError,
    FormatError,
    FormatNotDetected,
    InvalidAdapterError,
)


class WriteUnsupportedForSchemeError(FormatError, NotImplementedError):
    """A write was attempted against a URL scheme that is read-only.

    Raised by :class:`~datagrove.io.remote.RemoteAdapter` for
    ``http(s)://`` destinations. Object-store schemes (``s3://`` /
    ``gs://`` / ``az://``) do route through to the inner adapter with
    credentials attached; HTTP is read-only because the broader
    ecosystem (fsspec, the relevant cloud libs) doesn't agree on a
    single HTTP-PUT convention.

    Inherits from :class:`NotImplementedError` so existing
    ``except NotImplementedError`` callers (and tests written against
    the prior bare-builtin behaviour) keep matching. The
    :class:`FormatError` arm gives downstream code a categorical
    "datagrove I/O refused this" handle.
    """


__all__ = [
    "AdapterNotAvailableError",
    "FormatError",
    "FormatNotDetected",
    "InvalidAdapterError",
    "WriteUnsupportedForSchemeError",
]
