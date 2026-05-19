"""Internal: normalise cross-engine ``TableExpr`` to an ibis Table.

The validators in this package use ibis predicates throughout
(``expr[col].is_null()``, ``expr.filter(...).count().execute()``,
``expr.left_join(...)``) so that violation counts get pushed down to
the duckdb backend instead of materialising entire tables into
pandas. At Bay-Area scale (millions of rows) this is the difference
between "count nulls in a column" being a millisecond SQL aggregate
and being a gigabyte pandas materialisation.

To keep one codepath across the three engines, every validator entry
point calls :func:`to_ibis` once at the top, then operates on the
resulting :class:`ibis.expr.types.Table` for the rest of the call.

- ``IbisEngine`` (default) — pass-through. The expression already IS
  an ibis Table; we don't round-trip.
- ``PolarsEngine`` — collect the LazyFrame to a polars DataFrame, hand
  it the pyarrow Table view, wrap with ``ibis.memtable``. The data
  was going to be materialised anyway (polars is the in-memory path).
- ``PandasEngine`` — convert the DataFrame to pyarrow then
  ``ibis.memtable``. Same reasoning — pandas is already eager.

The ibis duckdb backend then runs all rule predicates as SQL against
the registered memtable. For pandas/polars sources this is a single
pyarrow round-trip per validator orchestrator call (not per rule), so
the overhead is bounded.

Sample materialisation for Issue enumeration goes via ``.to_pyarrow()``
+ ``.to_pylist()`` — never pandas — so this module is pandas-free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import ibis

if TYPE_CHECKING:  # pragma: no cover - typing only
    import ibis.expr.types as ir


__all__ = ["to_ibis"]


def to_ibis(expr: Any) -> ir.Table:
    """Return ``expr`` as an ibis :class:`Table`, converting if necessary.

    Pass-through for ibis tables (the default IbisEngine path).
    Polars LazyFrames and pandas DataFrames go via pyarrow into
    ``ibis.memtable``.

    Args:
        expr: Engine-native table expression — ibis Table, polars
            LazyFrame, or pandas DataFrame.

    Returns:
        An ibis Table backed by either the source backend (ibis
        pass-through) or the default in-memory ibis backend (memtable
        wrap).
    """
    # Ibis Table — pass-through. Cheapest path on the default engine.
    if isinstance(expr, ibis.expr.types.Table):
        return expr

    # Polars LazyFrame — collect to a polars DataFrame, hand its
    # pyarrow view to ibis.memtable. Polars frames don't expose
    # ``to_pyarrow`` directly on LazyFrame; collect first.
    try:
        import polars as pl

        if isinstance(expr, pl.LazyFrame):
            return ibis.memtable(expr.collect().to_arrow())
        if isinstance(expr, pl.DataFrame):
            return ibis.memtable(expr.to_arrow())
    except ImportError:  # pragma: no cover - polars not installed
        pass

    # Pandas DataFrame — duck-typed (no ``import pandas`` here, so the
    # validation package stays pandas-free per architecture §8). We
    # pyarrow-round-trip rather than calling ``ibis.memtable(df)``
    # directly because ibis's pandas-path inference drops integer
    # nullability (Int64 → float64), which would silently change
    # ``schema.type`` outcomes.
    if _looks_like_pandas_frame(expr):
        import pyarrow as pa

        return ibis.memtable(pa.Table.from_pandas(expr, preserve_index=False))

    # Last resort — let ibis try whatever it can with ``memtable``.
    # Any non-tabular object hits a clear ibis error here, not a
    # confusing AttributeError downstream.
    return ibis.memtable(expr)


def _looks_like_pandas_frame(obj: Any) -> bool:
    """Duck-type pandas DataFrame without importing pandas.

    Returns True for objects whose class name is ``DataFrame`` and
    whose module starts with ``pandas`` — the structural signature of
    a pandas DataFrame. This keeps this module free of any ``import
    pandas`` (architecture §8 — datagrove core paths are pandas-free;
    pandas is allowed only at user-facing converters).
    """
    cls = type(obj)
    return cls.__name__ == "DataFrame" and cls.__module__.startswith("pandas")
