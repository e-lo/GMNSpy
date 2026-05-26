"""GMNS-specific Python toolkit.

Builds on datagrove with network semantics, quality rules, editing, and
surfaces (CLI / notebook / API / MCP).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from gmnspy.network import Network, NetworkError
from gmnspy.spec import DEFAULT_SPEC, SUPPORTED_SPECS, get_spec_path, load_gmns_spec

if TYPE_CHECKING:
    from datagrove.engines.base import Engine


def read(
    source: str | Path,
    *,
    engine: Engine | None = None,
    spec_version: str | None = None,
    tables: Iterable[str] | None = None,
) -> Network:
    """Load a GMNS network from ``source``. The I/O front door.

    Thin convenience wrapper around :meth:`Network.from_source` — exists
    so the documented top-level form ``gmnspy.read(...)`` works without
    callers needing to know which class to import.

    Args:
        source: Local path, ``s3://`` / ``https://`` / ``duckdb://`` URL,
            or directory of CSV / Parquet / DuckDB / zipped-CSV files
            containing the GMNS package.
        engine: Engine to materialise through. Defaults to the
            datagrove default (typically the ibis + DuckDB engine).
        spec_version: GMNS spec version to validate against. Defaults
            to :data:`DEFAULT_SPEC` (currently ``"0.97"``); must be one
            of :data:`SUPPORTED_SPECS`.
        tables: Optional iterable of table names to partial-load.

    Returns:
        A :class:`Network` whose tables are lazy ibis expressions.

    Examples:
        >>> import gmnspy
        >>> from gmnspy.fixtures import leavenworth
        >>> net = gmnspy.read(leavenworth.csv_dir())
        >>> net.links.count()
        214
    """
    return Network.from_source(
        source,
        engine=engine,
        spec_version=spec_version,
        tables=tables,
    )


__all__ = [
    "DEFAULT_SPEC",
    "SUPPORTED_SPECS",
    "Network",
    "NetworkError",
    "get_spec_path",
    "load_gmns_spec",
    "read",
]
