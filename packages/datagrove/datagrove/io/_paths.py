"""Internal path-coercion helpers shared by every FormatAdapter.

Before this module the csv / parquet / duckdb / zipcsv / remote adapters
each had their own ``_coerce_path`` / ``_coerce_path_str`` / ``_as_path``
helper. They differed in subtle ways (which dict shape they accepted,
which exception they raised, whether they handled URL schemes) and the
duplication kept drifting. This module is the single source of truth.

The public surface (two thin functions) is intentionally tiny — any
adapter that needs special handling (e.g. the duckdb adapter's
``duckdb://`` URL stripping) wraps these helpers in a small local
function rather than forking the implementation.

Not part of the public API; the leading underscore makes that explicit.
"""

from __future__ import annotations

from pathlib import Path

from datagrove.engines.errors import UnsupportedSourceError
from datagrove.types import SourceRef

__all__ = ["normalize_to_path", "normalize_to_str"]


def normalize_to_str(source: SourceRef, *, adapter: str = "datagrove.io") -> str:
    """Coerce ``source`` to a filesystem path string.

    Accepts the ``str`` and ``Path`` arms of :data:`SourceRef`. The
    ``dict`` arm is a structured engine handle (e.g.
    ``{"format": "duckdb", "path": "...", "table": "link"}``) and is
    rejected with a clear :class:`UnsupportedSourceError` — adapters
    don't try to dig a path out of a dict because that's the dispatcher's
    job and dicts carry meaning beyond their path key.

    Args:
        source: The source reference to normalize.
        adapter: Short identifier of the calling adapter (used only in
            error messages so the user knows which adapter rejected the
            input).

    Returns:
        The path as a plain string.

    Raises:
        UnsupportedSourceError: If ``source`` is a ``dict`` (caller must
            pass an explicit ``format=`` so dispatch skips sniffing) or
            an unsupported type.
    """
    if isinstance(source, Path):
        return str(source)
    if isinstance(source, str):
        return source
    if isinstance(source, dict):
        raise UnsupportedSourceError(
            f"{adapter}: cannot sniff a dict source handle; pass an explicit "
            "format= so the dispatcher skips sniffing. dict handles are "
            "intended for engine-side use after dispatch has resolved an "
            "adapter (supported shapes: {'data': [...]} for inline data; "
            "{'format': 'duckdb', 'path': ..., 'table': ...} for a duckdb handle)."
        )
    raise UnsupportedSourceError(
        f"{adapter}: unsupported SourceRef type {type(source).__name__!r} (expected str or Path)"
    )


def normalize_to_path(source: SourceRef, *, adapter: str = "datagrove.io") -> Path:
    """Coerce ``source`` to a :class:`Path` for filesystem checks.

    Convenience wrapper around :func:`normalize_to_str` that returns a
    :class:`pathlib.Path`. Same accept/reject contract.
    """
    return Path(normalize_to_str(source, adapter=adapter))
