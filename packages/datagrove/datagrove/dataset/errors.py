"""Structured exceptions raised by the datagrove dataset layer.

Per ``docs/architecture.md`` §9 ("structured exceptions in
errors.py; use specific subclasses, not bare ``ValueError``"), the
dataset layer raises typed exceptions instead of bare built-ins. The
mirror modules are :mod:`datagrove.io.errors` and
:mod:`datagrove.engines.errors`.

Today the only dataset-layer exception is :class:`PackageError`, a
typed marker for "this :class:`~datagrove.dataset.Package` cannot
satisfy the requested operation" — used by :meth:`Package.write` when
no engine is attached, and reserved for future load/scope/write
failures that don't already have a more specific I/O-layer exception
(``FormatNotDetected``, ``WriteUnsupportedForSchemeError``).
"""

from __future__ import annotations


class PackageError(Exception):
    """A dataset-layer operation on a :class:`~datagrove.dataset.Package` failed.

    Raised when the package itself can't satisfy the requested
    operation (no engine attached, write target ambiguous in a way the
    I/O layer can't see, etc.). Format-resolution failures continue to
    raise :class:`~datagrove.io.FormatNotDetected` from the I/O layer;
    this exception is the dataset-level catch-all for everything else.
    """


__all__ = ["PackageError"]
