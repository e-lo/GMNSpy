"""Pandas engine — stub for task 1.2.

The real implementation lands in **Phase 1 task 1.5**. This module
auto-registers the engine if ``pandas`` is importable; otherwise it
silently does nothing (the engine is gated behind the
``datagrove[pandas]`` extra).

Per the architecture rules pandas is **only** allowed as an explicit
edge converter — never inside datagrove core paths. This adapter
exists for users who want to opt in via ``engine="pandas"``.
"""

from __future__ import annotations

from typing import Any

from .base import SourceRef, TableExpr


class PandasEngine:
    """Pandas engine adapter. Stub — real impl in task 1.5."""

    name: str = "pandas"

    def scan(self, source: SourceRef, schema: Any | None = None) -> TableExpr:
        """Open ``source`` as a ``pandas.DataFrame`` (eager). Lands in task 1.5."""
        raise NotImplementedError("pandas engine — landed in task 1.5")

    def materialize(self, expr: TableExpr) -> Any:
        """Identity for pandas (already eager). Lands in task 1.5."""
        raise NotImplementedError("pandas engine — landed in task 1.5")

    def to_pandas(self, expr: TableExpr) -> Any:
        """Identity / shallow copy. Lands in task 1.5."""
        raise NotImplementedError("pandas engine — landed in task 1.5")

    def to_polars(self, expr: TableExpr) -> Any:
        """Convert to ``polars.DataFrame``. Lands in task 1.5."""
        raise NotImplementedError("pandas engine — landed in task 1.5")

    def write(self, expr: TableExpr, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Write the pandas frame via the FormatAdapter layer. Lands in task 1.5."""
        raise NotImplementedError("pandas engine — landed in task 1.5")


__all__ = ["PandasEngine"]
