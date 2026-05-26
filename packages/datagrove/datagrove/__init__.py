"""Generic Frictionless-aligned tabular-data-package engine.

Top-level re-exports cover the most common entry points. Submodules
hold the full surface (:mod:`datagrove.engines`, :mod:`datagrove.io`,
:mod:`datagrove.validation`, :mod:`datagrove.dataset`, ...).

Examples:
    >>> from datagrove import Package, Table, read
    >>> Package is not None and Table is not None and read is not None
    True
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .dataset import OutOfSyncError, OutOfSyncWarning, Package, Table

if TYPE_CHECKING:
    from .engines.base import Engine
    from .spec import DataPackage


def read(
    source: str | Path,
    *,
    engine: Engine | None = None,
    spec: DataPackage | str | Path | None = None,
    tables: Any | None = None,
    **kwargs: Any,
) -> Package:
    """Load a Frictionless data package from ``source``. The I/O front door.

    Thin convenience wrapper around :meth:`Package.from_source` — exists
    so the documented top-level form ``datagrove.read(...)`` works
    without callers needing to know which class to import.

    Args:
        source: Local path, ``s3://`` / ``https://`` / ``duckdb://`` URL,
            or directory of CSV / Parquet / DuckDB / zipped-CSV files.
        engine: Engine to materialise through. Defaults to the registry
            default (typically the ibis + DuckDB engine).
        spec: A :class:`~datagrove.spec.DataPackage` instance, or a
            path to a ``datapackage.json`` to load. When omitted,
            :meth:`Package.from_source` looks for one alongside
            ``source``.
        tables: Optional iterable of table names to partial-load.
        **kwargs: Forwarded to :meth:`Package.from_source` — see that
            method for the full signature.

    Returns:
        A :class:`Package` whose tables are lazy engine expressions.

    Examples:
        >>> from datagrove import read
        >>> from gmnspy.fixtures import leavenworth
        >>> pkg = read(leavenworth.parquet_dir())
        >>> len(pkg.tables)
        9
    """
    return Package.from_source(
        source,
        engine=engine,
        spec=spec,
        tables=tables,
        **kwargs,
    )


__all__ = [
    "OutOfSyncError",
    "OutOfSyncWarning",
    "Package",
    "Table",
    "read",
]
