"""Ibis (duckdb-backed) engine — stub for task 1.2.

The real implementation is planned for **Phase 1 task 1.3** (see
``docs/architecture.md`` §10). This stub exists so the registry can
auto-register the default engine and so tests for the registry mechanics
can pass without depending on the real backend being wired.

This is also the **only** module in the codebase permitted to embed raw
SQL strings — the architecture lint rule allowlists it. All other
engines / IO adapters / dataset code must stay SQL-free.
"""

from __future__ import annotations

from typing import Any

from .base import SourceRef, TableExpr

_NOT_YET = "ibis engine: {method}() is not yet implemented (planned for task 1.3 — see docs/architecture.md §10)"


class IbisEngine:
    """Ibis engine adapter (duckdb backend). Stub — real impl in task 1.3."""

    name: str = "ibis"

    def scan(self, source: SourceRef, schema: Any | None = None) -> TableExpr:
        """Open ``source`` as an ``ibis.expr.types.Table``."""
        raise NotImplementedError(_NOT_YET.format(method="scan"))

    def materialize(self, expr: TableExpr) -> Any:
        """Execute the ibis expression on duckdb."""
        raise NotImplementedError(_NOT_YET.format(method="materialize"))

    def to_pandas(self, expr: TableExpr) -> Any:
        """Materialize via duckdb and return a ``pandas.DataFrame``."""
        raise NotImplementedError(_NOT_YET.format(method="to_pandas"))

    def to_polars(self, expr: TableExpr) -> Any:
        """Materialize via duckdb and return a ``polars.DataFrame``."""
        raise NotImplementedError(_NOT_YET.format(method="to_polars"))

    def write(self, expr: TableExpr, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Write the ibis expression to ``dest`` via the FormatAdapter layer."""
        raise NotImplementedError(_NOT_YET.format(method="write"))


__all__ = ["IbisEngine"]
