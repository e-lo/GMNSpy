"""Polars engine — stub for task 1.2.

The real implementation lands in **Phase 1 task 1.4**. This module
auto-registers the engine if ``polars`` is importable; otherwise it
silently does nothing (the engine is gated behind the
``datagrove[polars]`` extra).
"""

from __future__ import annotations

from typing import Any

from .base import SourceRef, TableExpr


class PolarsEngine:
    """Polars engine adapter. Stub — real impl in task 1.4."""

    name: str = "polars"

    def scan(self, source: SourceRef, schema: Any | None = None) -> TableExpr:
        """Open ``source`` as a ``polars.LazyFrame``. Lands in task 1.4."""
        raise NotImplementedError("polars engine — landed in task 1.4")

    def materialize(self, expr: TableExpr) -> Any:
        """Collect the ``LazyFrame`` to a ``polars.DataFrame``. Lands in task 1.4."""
        raise NotImplementedError("polars engine — landed in task 1.4")

    def to_pandas(self, expr: TableExpr) -> Any:
        """Collect and convert to ``pandas.DataFrame``. Lands in task 1.4."""
        raise NotImplementedError("polars engine — landed in task 1.4")

    def to_polars(self, expr: TableExpr) -> Any:
        """Collect to a ``polars.DataFrame``. Lands in task 1.4."""
        raise NotImplementedError("polars engine — landed in task 1.4")

    def write(self, expr: TableExpr, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Write the polars frame via the FormatAdapter layer. Lands in task 1.4."""
        raise NotImplementedError("polars engine — landed in task 1.4")


__all__ = ["PolarsEngine"]
