"""Engine protocol + supporting types for the datagrove engine layer.

An ``Engine`` is the *execution* abstraction over a Frictionless tabular
data package. It knows how to ``scan`` a source into a lazy table
expression, ``materialize`` that expression into the engine's natural
in-memory frame, convert to/from pandas and polars, and ``write`` an
expression back out to a destination.

Concrete engines (one per file in this package) implement this protocol:

- ``IbisEngine`` (default; backed by duckdb) — ``TableExpr`` is
  ``ibis.expr.types.Table``.
- ``PolarsEngine`` — ``TableExpr`` is ``polars.LazyFrame``.
- ``PandasEngine`` — ``TableExpr`` is ``pandas.DataFrame`` (eager;
  pandas has no lazy mode).

The protocol is **structural** (``typing.Protocol``,
``runtime_checkable``). The exact concrete types of ``TableExpr`` and
``NativeFrame`` differ per engine — that is intentional. Generic code
that hands an expression back to the same engine that produced it does
not need to care; cross-engine flow goes through the
``to_pandas`` / ``to_polars`` converters.

The protocol intentionally takes a ``SourceRef`` (a path / URL / dict
handle) on ``scan`` rather than a pre-opened reader. Format dispatch is
the job of the ``FormatAdapter`` layer (Phase 1 task 1.6, separate
module ``datagrove.io``); engines call into that layer when they need
to materialize bytes from a particular file shape (csv / parquet /
duckdb / zipcsv / remote). For task 1.2 this contract is just declared
— the wiring lands with the concrete engines (1.3 / 1.4 / 1.5) and
the format adapter (1.6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from datagrove.types import SourceRef

from .errors import (
    EngineNotAvailableError,
    InvalidEngineCallError,
    UnsupportedSourceError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd
    import polars as pl

# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

# ``SourceRef`` is re-exported from :mod:`datagrove.types` so that
# ``datagrove.io`` and ``datagrove.engines`` cannot drift apart on the
# accepted shape of a source reference. The canonical definition lives
# in ``datagrove.types``; the re-export here preserves the existing
# import path ``from datagrove.engines.base import SourceRef`` used by
# the concrete engine stubs and the registry.

#: An engine-native lazy/eager table expression returned by ``scan`` and
#: accepted by ``materialize`` / ``write`` / ``to_pandas`` / ``to_polars``.
#:
#: The concrete type depends on the engine (``ibis.expr.types.Table``,
#: ``polars.LazyFrame``, ``pandas.DataFrame``). The protocol is
#: structural; callers that mix engines should round-trip through
#: ``to_pandas()`` / ``to_polars()``.
TableExpr = Any

#: An engine-native fully-materialized frame returned by ``materialize``.
#: Concrete type depends on the engine (typically ``pyarrow.Table`` for
#: ibis, ``polars.DataFrame`` for polars, ``pandas.DataFrame`` for
#: pandas).
NativeFrame = Any


# ---------------------------------------------------------------------------
# Errors — re-exported from datagrove.engines.errors so the existing
# ``from datagrove.engines.base import EngineNotAvailableError`` import
# path keeps working (architecture §9 — structured exceptions live in
# errors.py, surfaced from the module that callers use).
# ---------------------------------------------------------------------------

# Re-exported via the imports at the top of the file; listed in __all__.


# ---------------------------------------------------------------------------
# Engine protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Engine(Protocol):
    """Execution engine for tabular operations on a Frictionless data package.

    Implementations are concrete classes (one per backend: ibis, polars,
    pandas) that satisfy this protocol structurally. The registry
    (``datagrove.engines``) holds singleton instances and resolves them
    by ``name``.

    Attributes:
        name: Short identifier used as the registry key
            (``"ibis"`` / ``"polars"`` / ``"pandas"``).
    """

    name: str

    def scan(
        self,
        source: SourceRef,
        format: str | None = None,
        schema: Any | None = None,
        **kwargs: Any,
    ) -> TableExpr:
        """Open ``source`` as a lazy table expression.

        Args:
            source: A path, URL, ``Path``, or handle dict pointing at a
                tabular file or table. Format dispatch is delegated to
                the ``datagrove.io`` ``FormatAdapter`` layer. The two
                handle-dict shapes every engine MUST accept are:

                - ``{"data": [...]}`` — inline data. Value is either a
                  list of row dicts (``[{"a": 1}, {"a": 2}]``) or a
                  columnar dict (``{"a": [1, 2]}``). Used for in-memory
                  test fixtures and small synthetic frames.
                - ``{"format": "duckdb", "path": "net.duckdb", "table":
                  "link"}`` — a duckdb table handle. ``"format"`` is
                  optional when ``"path"`` ends in ``.duckdb``.

                Any other dict shape MUST raise
                :class:`~datagrove.engines.errors.UnsupportedSourceError`
                with a message listing these supported shapes.
            format: Optional explicit format hint forwarded to
                ``datagrove.io.dispatch(source, format=format)``. When
                ``None`` the dispatcher uses URL-scheme / extension /
                ``probe`` resolution. Use this when the source is
                ambiguous (e.g. an extensionless file, an ``http://``
                URL that returns parquet bytes).
            schema: Optional Frictionless ``Schema`` to apply at scan
                time (column types, missing-value handling). If
                ``None``, the engine infers from file metadata.
            **kwargs: Adapter-specific options forwarded verbatim to the
                resolved ``FormatAdapter.read`` (delimiter, compression,
                partition pruning predicate, etc.). Engines must not
                strip or mutate this mapping.

        Returns:
            An engine-native lazy expression. Concrete type depends on
            the engine — see module docstring.
        """
        ...

    def materialize(self, expr: TableExpr) -> NativeFrame:
        """Execute ``expr`` and return the engine's native materialized frame.

        For ibis this triggers backend execution; for polars this
        ``.collect()``-s a ``LazyFrame``; for pandas this is an identity
        (pandas is already eager).
        """
        ...

    def to_pandas(self, expr: TableExpr) -> pd.DataFrame:
        """Materialize ``expr`` and return it as a ``pandas.DataFrame``.

        Cross-engine convergence point. Implementations may raise
        :class:`~datagrove.engines.errors.EngineNotAvailableError` if
        pandas is not installed.

        **Dtype convention (cross-engine contract).** The returned
        DataFrame uses pandas **numpy-backed nullable dtypes**:
        ``Int64`` (capital I), ``Float64``, ``string``, ``boolean``.
        We standardize on this family because:

        - Null semantics are preserved without silently upcasting
          integer columns with missing values to ``float64`` (the
          numpy default's footgun).
        - Numpy-backed (not ``pyarrow``-backed) dtypes keep
          compatibility with downstream libraries (sklearn, older
          matplotlib, geopandas pre-1.0) that don't understand
          ``pd.ArrowDtype`` columns.

        Implementations achieve this by post-processing with
        :meth:`pandas.DataFrame.convert_dtypes` (the universal path),
        regardless of which engine produced ``expr``. The Leavenworth
        fixture's ``link.from_node_id`` column round-trips as ``Int64``
        from all three stock engines under this convention — that is
        the regression locked in by the cross-engine parity test.
        """
        ...

    def to_polars(self, expr: TableExpr) -> pl.DataFrame:
        """Materialize ``expr`` and return it as a ``polars.DataFrame``.

        Cross-engine convergence point. Implementations may raise
        ``EngineNotAvailableError`` if polars is not installed.
        """
        ...

    def write(self, expr: TableExpr, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Write ``expr`` to ``dest`` in format ``fmt``.

        Args:
            expr: The expression to materialize and write.
            dest: A path, URL, or handle dict — same contract as
                ``scan``'s ``source``.
            fmt: Format name (``"parquet"``, ``"csv"``, ``"duckdb"``,
                etc.). Dispatched through the ``datagrove.io``
                ``FormatAdapter`` layer.
            **kwargs: Format-specific options (compression, partitioning,
                etc.). Adapter-defined.
        """
        ...


__all__ = [
    "Engine",
    "EngineNotAvailableError",
    "InvalidEngineCallError",
    "NativeFrame",
    "SourceRef",
    "TableExpr",
    "UnsupportedSourceError",
]
