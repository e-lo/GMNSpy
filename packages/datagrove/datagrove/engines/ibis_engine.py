"""Ibis (duckdb-backed) engine — stub for task 1.2.

The real implementation lands in **Phase 1 task 1.3**. This stub exists
so the registry can auto-register the default engine and so tests for
the registry mechanics can pass without depending on the real backend
being wired.

This is also the **only** module in the codebase permitted to embed raw
SQL strings — the architecture lint rule allowlists it. All other
engines / IO adapters / dataset code must stay SQL-free.
"""

from __future__ import annotations

from typing import Any

from .base import SourceRef, TableExpr


class IbisEngine:
    """Ibis engine adapter (duckdb backend). Stub — real impl in task 1.3."""

    name: str = "ibis"

    def scan(self, source: SourceRef, schema: Any | None = None) -> TableExpr:
        """Open ``source`` as an ``ibis.expr.types.Table``. Lands in task 1.3."""
        raise NotImplementedError("ibis engine — landed in task 1.3")

    def materialize(self, expr: TableExpr) -> Any:
        """Execute the ibis expression on duckdb. Lands in task 1.3."""
        raise NotImplementedError("ibis engine — landed in task 1.3")

    def to_pandas(self, expr: TableExpr) -> Any:
        """Materialize via duckdb and return a ``pandas.DataFrame``. Lands in task 1.3."""
        raise NotImplementedError("ibis engine — landed in task 1.3")

    def to_polars(self, expr: TableExpr) -> Any:
        """Materialize via duckdb and return a ``polars.DataFrame``. Lands in task 1.3."""
        raise NotImplementedError("ibis engine — landed in task 1.3")

    def write(self, expr: TableExpr, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Write the ibis expression to ``dest`` via the FormatAdapter layer. Lands in task 1.3."""
        raise NotImplementedError("ibis engine — landed in task 1.3")


__all__ = ["IbisEngine"]
