"""Engine-agnostic attribute row filter.

Applies a compact ``[{"col", "op", "val"}, ...]`` predicate spec to a
:class:`~datagrove.dataset.Table`, AND-combined. The spec is **not SQL** — it
is validated (unknown column/op raise :class:`FilterSpecError`) and compiled to
an ibis boolean expression, following the same **ibis-first** cross-engine
strategy as the spatial scopes in :mod:`datagrove.dataset.view`:

* a duckdb-backed ibis ``Table`` keeps the filter lazy on that backend, so it
  is pushed down as a single SQL ``WHERE`` (a large table never materialises);
* other engines route through an ``ibis.memtable``, filter, and rebuild on the
  source engine via :meth:`Engine.from_arrow` (type-preserving round-trip).

This is the predicate layer behind the viewer's data-table filters, so a
million-row GMNS table filters in the engine rather than in Python.
"""

from __future__ import annotations

import functools
import operator
from typing import Any

import ibis

from datagrove.validation._ibis import to_ibis

from .table import Table

__all__ = ["FilterSpecError", "filter_rows"]


class FilterSpecError(ValueError):
    """An invalid filter spec (unknown column or operator)."""


def _ibis_backend_of(table: Table) -> Any | None:
    """Return the source ibis backend of ``table`` if its expr is ibis-native."""
    expr = table.expr
    if not isinstance(expr, ibis.expr.types.Table):
        return None
    try:
        return expr._find_backend()
    except Exception:  # pragma: no cover - defensive (fresh memtable, no backend)
        return None


def _condition(column: Any, op: str, val: Any):
    if op == "eq":
        return column == val
    if op == "ne":
        return column != val
    if op == "lt":
        return column < val
    if op == "lte":
        return column <= val
    if op == "gt":
        return column > val
    if op == "gte":
        return column >= val
    if op == "in":
        return column.isin(list(val) if isinstance(val, (list, tuple, set)) else [val])
    if op == "contains":
        return column.cast("string").lower().contains(str(val).lower())
    if op == "isnull":
        return column.isnull()
    if op == "notnull":
        return column.notnull()
    raise FilterSpecError(f"unknown operator {op!r}")


def _predicate(expr: Any, conditions: list[dict]):
    """Build an AND-combined ibis boolean expression over ``expr``."""
    cols = set(expr.columns)
    conds = []
    for cond in conditions:
        col = cond.get("col")
        if col not in cols:
            raise FilterSpecError(f"unknown column {col!r}")
        conds.append(_condition(expr[col], cond.get("op"), cond.get("val")))
    return functools.reduce(operator.and_, conds)


def filter_rows(table: Table, conditions: list[dict]) -> Table:
    """Return a new :class:`Table` filtered by ``conditions`` (AND-combined).

    Args:
        table: The table to filter.
        conditions: A list of ``{"col", "op", "val"}`` dicts. Ops:
            ``eq, ne, lt, lte, gt, gte, in, contains, isnull, notnull``.
            ``contains`` is case-insensitive substring. Empty list is a no-op.

    Raises:
        FilterSpecError: unknown column or operator.
    """
    if not conditions:
        return table
    if _ibis_backend_of(table) is not None:  # ibis/duckdb: stay lazy, push down
        return table._derived(table.expr.filter(_predicate(table.expr, conditions)))
    ibis_table = to_ibis(table.expr)  # pandas/polars: memtable round-trip
    filtered = ibis_table.filter(_predicate(ibis_table, conditions))
    return table._derived(table.engine.from_arrow(filtered.to_pyarrow()))
