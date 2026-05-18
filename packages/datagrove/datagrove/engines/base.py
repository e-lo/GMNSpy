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

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd
    import polars as pl

# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

#: A reference to an input/output location an engine can read or write.
#:
#: Today: a filesystem path, a URL string, or a ``dict`` handle for
#: structured sources (e.g. ``{"format": "duckdb", "path": "...",
#: "table": "link"}``). Engines are free to accept richer dispatch
#: payloads in their own ``scan`` / ``write`` overrides — the registry
#: never inspects this type, it just hands it through.
SourceRef = str | Path | dict

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
# Errors
# ---------------------------------------------------------------------------


class EngineNotAvailableError(RuntimeError):
    """Raised when a requested engine is not registered or its deps are missing.

    This is the single error type the registry raises for "I cannot give
    you that engine". Reasons include:

    - The engine's optional dependencies are not installed (e.g. user
      asked for ``"polars"`` without ``pip install datagrove[polars]``).
    - The name is not registered (typo, or a module that failed to
      import at registration time).
    - The registry is empty (no engines successfully registered at
      import — usually means the default ibis install is broken).
    """


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

    def scan(self, source: SourceRef, schema: Any | None = None) -> TableExpr:
        """Open ``source`` as a lazy table expression.

        Args:
            source: A path, URL, or handle dict pointing at a tabular
                file or table. Format dispatch is delegated to the
                ``datagrove.io`` ``FormatAdapter`` layer.
            schema: Optional Frictionless ``Schema`` to apply at scan
                time (column types, missing-value handling). If
                ``None``, the engine infers from file metadata.

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
        ``EngineNotAvailableError`` if pandas is not installed.
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
    "NativeFrame",
    "SourceRef",
    "TableExpr",
]
