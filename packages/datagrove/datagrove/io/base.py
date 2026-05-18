"""FormatAdapter protocol, source/resource types, and exception hierarchy.

This module defines the contract every storage-format adapter must satisfy
(csv, parquet, duckdb, zipcsv, remote-fsspec, ...). Concrete adapters live
in sibling modules and are expected to be registered via
``datagrove.io.register_adapter`` at import time of their host module.

Design notes for adapter implementers:
    - ``probe`` must be cheap (header sniff / magic-byte check / extension
      heuristic). It is called by the dispatcher only as a last resort,
      after explicit ``format=``, URL scheme, and filename extension
      dispatch have failed.
    - ``read`` must return a *lazy* table expression created via the engine
      (e.g., ``engine.read_csv(path)``); it must not materialize.
    - ``scan`` is the discovery surface for multi-table containers
      (a directory of csvs, a duckdb file with multiple tables, a zip with
      multiple csvs). Single-table formats simply return a one-element list.
    - The engine reference is passed through so adapters can defer all
      actual I/O to the engine's native readers --this keeps adapters thin
      and engine-agnostic at the call site.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    # These live in sibling modules that may import from io/. Type-only
    # imports break the circular dependency.
    from datagrove.engines.base import Engine, TableExpr  # pragma: no cover
    from datagrove.spec.base import Schema  # pragma: no cover


# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

SourceRef = str | Path
"""A reference to a data source.

Either a local filesystem path (``str`` or ``Path``) or a URL string in
fsspec form (``s3://bucket/key``, ``gs://...``, ``https://...``,
``duckdb://path/to.duckdb``, etc.).
"""


# ---------------------------------------------------------------------------
# Resource listing model
# ---------------------------------------------------------------------------


class ResourceRef(BaseModel):
    """A single discoverable resource (table) at a source.

    Attributes:
        name: Logical resource name (e.g., ``"link"``, ``"node"``). For a
            single-file source this is typically the file stem.
        path: Concrete locator for the resource --a filesystem path, a URL,
            or a sub-locator within a container (e.g., ``"my.duckdb::link"``
            for a duckdb table). Always a string for serializability.
        format: Short identifier of the format adapter that produced this
            ref (e.g., ``"csv"``, ``"parquet"``, ``"duckdb"``).
    """

    name: str = Field(..., description="Logical resource name (table name).")
    path: str = Field(..., description="Concrete locator for the resource.")
    format: str = Field(..., description="Short adapter identifier.")

    model_config = {"frozen": True}


ResourceListing = list[ResourceRef]
"""An ordered list of resources discovered at a source.

Single-table formats (one csv, one parquet) yield a one-element listing;
multi-table containers (directory of csvs, duckdb file, zipped package) may
yield many.
"""


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class FormatAdapter(Protocol):
    """A read/write adapter for one storage format.

    Implementations declare their identity (``name``), the filename
    extensions they own (``extensions``, no leading dot), and any URL
    schemes they handle (``schemes``, no trailing colon-slash). The
    dispatcher uses these to route a :data:`SourceRef` to the right
    adapter; ``probe`` is the fallback when neither extension nor scheme
    yields a unique match.

    Attributes:
        name: Short identifier --e.g. ``"csv"``, ``"parquet"``,
            ``"duckdb"``, ``"zipcsv"``. Must be unique across the registry.
        extensions: Tuple of filename extensions (no dot) this adapter
            owns. Compound extensions are written longest-first joined by
            dots --e.g. ``("csv.zip",)`` for a csv-in-zip adapter.
        schemes: Tuple of URL schemes (no ``://``) this adapter handles.
            Usually empty; populated for adapters that own a scheme like
            ``duckdb://``.
    """

    name: str
    extensions: tuple[str, ...]
    schemes: tuple[str, ...]

    def probe(self, source: SourceRef) -> bool:
        """Return True if this adapter can read ``source``.

        Implementations must be cheap --a header sniff, a magic-byte read,
        or an extension/heuristic check. Called by the dispatcher only
        when explicit format, scheme, and extension lookup all miss.

        Args:
            source: The candidate source reference.

        Returns:
            True if the adapter is willing to attempt a read.
        """
        ...

    def read(
        self,
        source: SourceRef,
        engine: Engine,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> TableExpr:
        """Return an unmaterialized table expression for ``source``.

        Args:
            source: The source reference to read.
            engine: The engine to defer actual I/O to (e.g., ibis/duckdb).
            schema: Optional resolved Frictionless schema; when provided,
                adapters should pass column-type hints to the engine.
            **kwargs: Adapter-specific options (compression, delimiter,
                partition pruning predicate, etc.).

        Returns:
            A lazy table expression. Materialization happens only on the
            consumer side (``.to_pandas()``, ``.collect()``, ...).
        """
        ...

    def write(
        self,
        expr: TableExpr,
        dest: SourceRef,
        engine: Engine,
        **kwargs: Any,
    ) -> None:
        """Persist ``expr`` to ``dest`` via ``engine``.

        Args:
            expr: A table expression to materialize and write.
            dest: Target reference (path or URL).
            engine: The engine performing the write.
            **kwargs: Adapter-specific options (partitioning, compression,
                overwrite mode, ...).
        """
        ...

    def scan(self, source: SourceRef, engine: Engine) -> ResourceListing:
        """Enumerate the tables/resources discoverable at ``source``.

        Multi-table containers (directory of csvs, duckdb file with
        multiple tables, zip with multiple csvs) return many entries.
        Single-table formats return a one-element listing.

        Args:
            source: The source to enumerate.
            engine: The engine for any cheap metadata reads.

        Returns:
            An ordered :data:`ResourceListing`.
        """
        ...


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class FormatError(Exception):
    """Base class for all I/O format errors raised by ``datagrove.io``."""


class FormatNotDetected(FormatError):
    """No registered adapter could be matched to a source.

    Raised by :func:`datagrove.io.dispatch` after all resolution stages
    (explicit format, URL scheme, filename extension, ``probe`` chain)
    have failed.
    """


class AdapterNotAvailableError(FormatError):
    """A named adapter was requested but is not registered.

    Raised when a caller passes ``format="excel"`` (or similar) and no
    adapter with that ``name`` has been registered. Typically this means
    an optional dependency is not installed or the adapter module was not
    imported.
    """


__all__ = [
    "AdapterNotAvailableError",
    "FormatAdapter",
    "FormatError",
    "FormatNotDetected",
    "ResourceListing",
    "ResourceRef",
    "SourceRef",
]
