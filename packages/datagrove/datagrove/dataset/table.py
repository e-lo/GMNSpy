"""Lazy single-table wrapper — see :class:`Table`.

A :class:`Table` is the unit of "one logical resource" inside a
:class:`~datagrove.dataset.Package`. It composes:

* a logical ``name`` (matches the Frictionless ``Resource.name`` and
  drives FK lookups);
* an engine-native lazy ``expr`` (``ibis.expr.types.Table`` /
  ``polars.LazyFrame`` / ``pandas.DataFrame``);
* a back-pointer to the :class:`~datagrove.engines.base.Engine` that
  produced the expression (so materialisation always goes back through
  the same engine);
* an optional Frictionless :class:`~datagrove.spec.model.Schema` used
  by the validation layer;
* an optional source locator (``source`` + ``format``) for round-trip
  reads / writes;
* a mutable ``dirty`` flag the sync-state tracker (task 2.6) reads
  before any write.

Design rules:
    * **Lazy by default.** ``head``, ``select``, ``filter`` return a new
      :class:`Table` wrapping a transformed expression. Nothing touches
      the engine backend until the caller asks for materialisation via
      :meth:`Table.to_pandas`, :meth:`Table.to_polars`,
      :meth:`Table.collect`, or :meth:`Table.count`.
    * **Each transform returns a new Table** — the original is
      unchanged. This matches the underlying engine semantics
      (TableExpr is immutable per engine) and lets callers safely hold
      a reference across a chain of ops.
    * **Mutations mark dirty.** :meth:`Table.invalidate` flips the
      ``dirty`` flag; the sync-state tracker reads it. Full Edit/Diff
      semantics arrive in task 2.9.

The cross-engine round-trip story is identical to the rest of
datagrove: every engine implements ``to_pandas`` and ``to_polars`` as
convergence points. The :class:`Table` simply delegates.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd
    import polars as pl

    from datagrove.engines.base import Engine, TableExpr
    from datagrove.spec.model import Schema

__all__ = ["Table"]


@dataclass
class Table:
    """Lazy wrapper around one table in a data package.

    The wrapper is *mutable* (its ``expr`` may be replaced — for
    example by an editing op or a scoped view), but each underlying
    ``TableExpr`` is *immutable* per the engine's semantics. Lazy ops
    (:meth:`filter`, :meth:`select`, :meth:`head`) therefore return a
    new :class:`Table`, leaving the original unchanged.

    Mutation: this class intentionally does not expose an in-place
    ``update`` shim. For row-level edits with full diff / rollback /
    audit, use :class:`datagrove.editing.Edit` +
    :class:`datagrove.editing.Session`. For low-level mutations that
    bypass the editing framework, build a new expression directly and
    call :meth:`invalidate` on the table to flip its ``dirty`` flag so
    the sync-state tracker sees the change.

    Attributes:
        name: Logical resource name. Matches
            :attr:`datagrove.spec.model.Resource.name` and is used as
            the dict key inside a :class:`~datagrove.dataset.Package`.
        expr: Engine-native lazy expression. Concrete type depends on
            the engine (``ibis.expr.types.Table`` for ibis,
            ``polars.LazyFrame`` for polars, ``pandas.DataFrame`` for
            pandas — pandas is eager by design).
        engine: The engine that produced ``expr``. Materialisation
            always routes back through this same engine to preserve
            the cross-engine dtype contract.
        schema: Optional resolved Frictionless schema. Carried so the
            validation layer can run per-field checks without
            re-loading the spec.
        source: Optional source locator (path / URL / sub-locator
            like ``"net.duckdb::link"``). Set by
            :meth:`Package.from_source`; ``None`` for tables
            constructed inline.
        format: Optional short format identifier (``"csv"``,
            ``"parquet"``, ``"duckdb"``). Mirrors
            :attr:`datagrove.io.base.ResourceRef.format`.
        dirty: True when the table has been mutated (or its source
            hash differs from a sync-state stamp). Read by the
            sync-state tracker (task 2.6) before any write.
        metadata: Free-form bag of extras. Carried through writes via
            the package-level metadata sidecar in Phase 3.

    Examples:
        Construct directly from in-memory records via an engine::

            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> expr = e.from_records([{"a": 1}, {"a": 2}, {"a": 3}])
            >>> t = Table(name="t", expr=expr, engine=e)
            >>> t.count()
            3
            >>> t.dirty
            False
    """

    name: str
    expr: TableExpr
    engine: Engine
    schema: Schema | None = None
    source: str | None = None
    format: str | None = None
    dirty: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Lazy ops — return a new Table; original unchanged
    # ------------------------------------------------------------------

    def filter(self, predicate: Callable[[TableExpr], TableExpr]) -> Table:
        """Return a new :class:`Table` whose expression is ``predicate(expr)``.

        The predicate receives the engine-native expression and returns
        a new engine-native expression (typically a filtered one). The
        caller writes the predicate in the engine's own dialect — this
        method doesn't translate between engines.

        Args:
            predicate: Callable taking the current ``expr`` and
                returning a new expression of the same engine type.

        Returns:
            A new :class:`Table` wrapping the transformed expression;
            the original :class:`Table` is unchanged.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> expr = e.from_records([{"a": 1}, {"a": 2}, {"a": 3}])
            >>> t = Table(name="t", expr=expr, engine=e)
            >>> t2 = t.filter(lambda df: df[df["a"] > 1])
            >>> t2 is t
            False
            >>> t.count(), t2.count()
            (3, 2)
        """
        return self._derived(predicate(self.expr))

    def select(self, *columns: str) -> Table:
        """Return a new :class:`Table` projected to the named ``columns``.

        Args:
            *columns: Column names to keep. Must all exist on the
                current ``expr``.

        Returns:
            A new :class:`Table` carrying only the projected columns.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> expr = e.from_records([{"a": 1, "b": 2}])
            >>> Table(name="t", expr=expr, engine=e).select("a").columns()
            ['a']
        """
        cols = list(columns)
        return self._derived(_engine_select(self.engine, self.expr, cols))

    def head(self, n: int = 5) -> Table:
        """Return a new :class:`Table` containing only the first ``n`` rows.

        Lazy — the underlying engine builds a head expression, but no
        materialisation runs until the caller asks for it.

        Args:
            n: Row count to keep (default 5).

        Returns:
            A new :class:`Table` whose expression is the head.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> expr = e.from_records([{"a": i} for i in range(10)])
            >>> Table(name="t", expr=expr, engine=e).head(3).count()
            3
        """
        return self._derived(_engine_head(self.engine, self.expr, n))

    # ------------------------------------------------------------------
    # Materialisation
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the row count, pushing down to the engine where possible.

        Tries the engine-native count path before falling back to a
        full materialisation:

        * ibis ``Table`` exprs use
          ``expr.count().to_pyarrow().as_py()`` so the aggregate is
          pushed to duckdb (or whichever ibis backend) as a single SQL
          scalar.
        * polars ``LazyFrame`` exprs use
          ``expr.select(polars.len()).collect().item()`` so the count
          stays inside the lazy plan.
        * pandas ``DataFrame`` exprs use ``len(expr)`` directly —
          pandas is already eager so there's nothing to push.
        * Anything else falls back to ``len(engine.to_pandas(expr))``.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> Table(name="t", expr=e.from_records([{"a": 1}]), engine=e).count()
            1
        """
        return _engine_count(self.engine, self.expr)

    def to_pandas(self) -> pd.DataFrame:
        """Materialise as a ``pandas.DataFrame`` using the engine's converter.

        The returned frame uses the cross-engine **nullable numpy-backed
        dtype** family (``Int64`` / ``Float64`` / ``string`` /
        ``boolean``) regardless of which engine produced the expression
        — see :meth:`datagrove.engines.base.Engine.to_pandas` for the
        full contract.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> t = Table(name="t", expr=e.from_records([{"a": 1}]), engine=e)
            >>> t.to_pandas()["a"].tolist()
            [1]
        """
        return self.engine.to_pandas(self.expr)

    def to_polars(self) -> pl.DataFrame:
        """Materialise as a ``polars.DataFrame`` using the engine's converter.

        Raises :class:`~datagrove.engines.errors.EngineNotAvailableError`
        if polars is not installed and the engine cannot satisfy the
        conversion.

        Examples:
            >>> import pytest
            >>> _ = pytest.importorskip("polars")
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> t = Table(name="t", expr=e.from_records([{"a": 1}]), engine=e)
            >>> t.to_polars().shape[0]
            1
        """
        return self.engine.to_polars(self.expr)

    def collect(self) -> TableExpr:
        """Force eager materialisation; return the engine-native frame.

        For ibis this triggers backend execution and returns a pyarrow
        ``Table``; for polars this collects the ``LazyFrame`` to a
        ``DataFrame``; for pandas this is essentially an identity
        (pandas is already eager).

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> t = Table(name="t", expr=e.from_records([{"a": 1}]), engine=e)
            >>> out = t.collect()
            >>> out is not t
            True
        """
        return self.engine.materialize(self.expr)

    # ------------------------------------------------------------------
    # Mutation surface (marks dirty)
    # ------------------------------------------------------------------

    def invalidate(self) -> None:
        """Manually mark the table dirty.

        Use after a direct mutation that bypassed the editing
        framework (e.g. the caller poked the underlying engine frame
        outside this wrapper). The sync-state tracker reads
        :attr:`dirty` before the next write.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> t = Table(name="t", expr=e.from_records([{"a": 1}]), engine=e)
            >>> t.invalidate()
            >>> t.dirty
            True
        """
        self.dirty = True

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def columns(self) -> list[str]:
        """Return the column names of the underlying expression.

        Uses the engine's lazy schema introspection where possible —
        for ibis this is ``expr.schema().names``; for polars
        ``expr.collect_schema().names()``; for pandas
        ``list(expr.columns)``. No row materialisation runs.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> Table(name="t", expr=e.from_records([{"a": 1, "b": 2}]), engine=e).columns()
            ['a', 'b']
        """
        return _engine_columns(self.engine, self.expr)

    def __repr__(self) -> str:
        """One-line summary: name, format if known, row count if cheap, dirty flag."""
        bits: list[str] = [f"name={self.name!r}"]
        if self.format:
            bits.append(f"format={self.format!r}")
        if self.source:
            bits.append(f"source={self.source!r}")
        bits.append("dirty" if self.dirty else "clean")
        return f"Table({', '.join(bits)})"

    def _repr_html_(self) -> str:
        """Minimal Jupyter-friendly HTML rendering.

        A polished render is Phase 4 / notebook polish work; today we
        ship a ``<pre>``-wrapped :meth:`__repr__` so notebooks don't
        break. The contract this guarantees is "non-empty string that
        is safe to insert into a notebook cell".

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Table
            >>> e = PandasEngine()
            >>> Table(name="t", expr=e.from_records([{"a": 1}]), engine=e)._repr_html_().startswith("<pre>")
            True
        """
        return f"<pre>{_html_escape(repr(self))}</pre>"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _derived(self, new_expr: TableExpr) -> Table:
        """Build a child :class:`Table` carrying the same identity metadata.

        The child inherits ``name``, ``engine``, ``schema``, ``source``,
        ``format``, and a shallow copy of ``metadata``. It starts
        ``dirty=False`` — a transform doesn't imply a mutation. Callers
        flip ``dirty`` themselves (or use :meth:`invalidate`) when they
        intend the result to be sync-state-relevant.
        """
        return Table(
            name=self.name,
            expr=new_expr,
            engine=self.engine,
            schema=self.schema,
            source=self.source,
            format=self.format,
            dirty=False,
            metadata=dict(self.metadata),
        )


# ---------------------------------------------------------------------------
# Engine-shape helpers — kept module-level so adding a fourth engine doesn't
# require changing :class:`Table`.
# ---------------------------------------------------------------------------


def _engine_columns(engine: Engine, expr: TableExpr) -> list[str]:
    """Best-effort lazy column list across the stock engines.

    Tries the cheapest known surface per engine — duck-typed to the
    engine's TableExpr — and falls back to a one-row materialisation if
    none of them are present. The fallback ensures :class:`Table` works
    with downstream engines that follow the protocol structurally but
    have a different schema-introspection API.
    """
    # ibis: expr.schema() returns an ibis.Schema whose .names is a list[str].
    schema_fn = getattr(expr, "schema", None)
    if callable(schema_fn):
        try:
            sch = schema_fn()
            names = getattr(sch, "names", None)
            if isinstance(names, list):
                return list(names)
        except Exception:
            pass
    # polars LazyFrame: collect_schema().names() (Polars >= 1.0)
    collect_schema = getattr(expr, "collect_schema", None)
    if callable(collect_schema):
        try:
            sch = collect_schema()
            names_fn = getattr(sch, "names", None)
            if callable(names_fn):
                return list(names_fn())
        except Exception:
            pass
    # pandas / polars DataFrame: .columns
    cols = getattr(expr, "columns", None)
    if cols is not None:
        return list(cols)
    # Fallback: cheap-ish materialisation.
    return list(engine.to_pandas(expr).columns)


def _engine_select(engine: Engine, expr: TableExpr, columns: list[str]) -> TableExpr:
    """Engine-native ``select(columns)`` — preserves the expression's laziness.

    Each engine exposes a slightly different selection surface; we
    duck-type to the cheapest lazy one and fall through to pandas only
    when nothing else matches. The fallback path is eager but the test
    parametrisation excludes it for the engines we ship today.
    """
    # ibis: expr.select("a", "b")
    select_fn = getattr(expr, "select", None)
    if callable(select_fn):
        # ibis + polars LazyFrame + polars DataFrame all expose this surface.
        try:
            return select_fn(*columns)
        except TypeError:
            # polars wants a list, ibis takes varargs — try the list form.
            return select_fn(columns)
    # pandas DataFrame: column-list indexing.
    try:
        return expr[columns]  # type: ignore[index]
    except Exception:  # pragma: no cover - defensive fallback
        df = engine.to_pandas(expr)
        return df[columns]


def _engine_count(engine: Engine, expr: TableExpr) -> int:
    """Engine-native row count — avoids the full materialisation hop.

    Probes the cheapest known count surface per engine in order. The
    duck-typed checks intentionally don't require an ``isinstance``
    against ibis / polars / pandas at this layer so a fourth engine
    that follows the same structural surface keeps working without
    edits here.

    Order:
        1. ``expr.count()`` returning an ibis scalar — call
           ``.to_pyarrow().as_py()`` for the int.
        2. ``expr.select(pl.len()).collect().item()`` for polars
           ``LazyFrame``.
        3. ``len(expr)`` for pandas / polars eager ``DataFrame``.
        4. Last-resort fallback: ``len(engine.to_pandas(expr))``.
    """
    # ibis: `expr.count()` returns an ibis scalar expression whose
    # `to_pyarrow().as_py()` produces the int via the configured
    # backend. The whole computation pushes down as a SQL
    # `SELECT COUNT(*)`. Mirrors the convention in
    # :func:`datagrove.validation.schema_check._count`.
    count_fn = getattr(expr, "count", None)
    if callable(count_fn):
        try:
            result = count_fn()
        except TypeError:
            result = None
        if result is not None:
            to_pyarrow = getattr(result, "to_pyarrow", None)
            if callable(to_pyarrow):
                try:
                    return int(to_pyarrow().as_py())
                except Exception:  # pragma: no cover - defensive
                    pass
            # pandas Series exposes a `.count()` int directly — fall
            # through to len() below.
    # polars LazyFrame: select(pl.len()).collect().item() keeps the
    # count inside the lazy plan. We only import polars when the
    # expression actually has the `collect` + `select` shape so we
    # don't pay an import cost for the ibis / pandas paths.
    if hasattr(expr, "collect") and hasattr(expr, "select"):
        try:
            import polars as pl  # local import — polars is optional
        except ImportError:  # pragma: no cover - polars not installed
            pl = None  # type: ignore[assignment]
        if pl is not None:
            try:
                return int(expr.select(pl.len()).collect().item())  # type: ignore[arg-type]
            except Exception:  # pragma: no cover - defensive
                pass
    # pandas DataFrame / polars eager DataFrame: len() is cheap.
    try:
        return len(expr)  # type: ignore[arg-type]
    except TypeError:
        pass
    # Last resort — materialise via the engine. Keeps the public
    # contract intact for exotic engines.
    return len(engine.to_pandas(expr))


def _engine_head(engine: Engine, expr: TableExpr, n: int) -> TableExpr:
    """Engine-native ``head(n)`` — preserves the expression's laziness.

    Tries ``expr.head(n)`` (works for ibis, pandas, polars DataFrame),
    then ``expr.limit(n)`` (polars LazyFrame), then falls through to a
    pandas materialise-and-slice as the universal floor.
    """
    head_fn = getattr(expr, "head", None)
    if callable(head_fn):
        return head_fn(n)
    limit_fn = getattr(expr, "limit", None)
    if callable(limit_fn):
        return limit_fn(n)
    df = engine.to_pandas(expr)
    return df.head(n)


def _html_escape(value: str) -> str:
    """Tiny stdlib HTML escape — keeps :meth:`Table._repr_html_` dependency-free."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
