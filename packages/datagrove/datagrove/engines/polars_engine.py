"""Polars engine — stub for task 1.2.

The real implementation is planned for **Phase 1 task 1.4** (see
``docs/architecture.md`` §10). This module auto-registers the engine if
``polars`` is importable; otherwise it silently does nothing (the engine
is gated behind the ``datagrove[polars]`` extra).
"""

from __future__ import annotations

from typing import Any

from .base import SourceRef, TableExpr

_NOT_YET = "polars engine: {method}() is not yet implemented (planned for task 1.4 — see docs/architecture.md §10)"


class PolarsEngine:
    """Polars engine adapter. Stub — real impl in task 1.4."""

    name: str = "polars"

    def scan(self, source: SourceRef, schema: Any | None = None) -> TableExpr:
        """Open ``source`` as a ``polars.LazyFrame``."""
        raise NotImplementedError(_NOT_YET.format(method="scan"))

    def materialize(self, expr: TableExpr) -> Any:
        """Collect the ``LazyFrame`` to a ``polars.DataFrame``."""
        raise NotImplementedError(_NOT_YET.format(method="materialize"))

    def to_pandas(self, expr: TableExpr) -> Any:
        """Collect and convert to ``pandas.DataFrame``."""
        raise NotImplementedError(_NOT_YET.format(method="to_pandas"))

    def to_polars(self, expr: TableExpr) -> Any:
        """Collect to a ``polars.DataFrame``."""
        raise NotImplementedError(_NOT_YET.format(method="to_polars"))

    def write(self, expr: TableExpr, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Write the polars frame via the FormatAdapter layer."""
        raise NotImplementedError(_NOT_YET.format(method="write"))


__all__ = ["PolarsEngine"]
