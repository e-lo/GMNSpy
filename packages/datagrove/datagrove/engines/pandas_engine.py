"""Pandas engine — stub for task 1.2.

The real implementation is planned for **Phase 1 task 1.5** (see
``docs/architecture.md`` §10). This module auto-registers the engine if
``pandas`` is importable; otherwise it silently does nothing (the engine
is gated behind the ``datagrove[pandas]`` extra).

Per the architecture rules pandas is **only** allowed as an explicit
edge converter — never inside datagrove core paths. This adapter
exists for users who want to opt in via ``engine="pandas"``.
"""

from __future__ import annotations

from typing import Any

from .base import SourceRef, TableExpr

_NOT_YET = "pandas engine: {method}() is not yet implemented (planned for task 1.5 — see docs/architecture.md §10)"


class PandasEngine:
    """Pandas engine adapter. Stub — real impl in task 1.5."""

    name: str = "pandas"

    def scan(self, source: SourceRef, schema: Any | None = None) -> TableExpr:
        """Open ``source`` as a ``pandas.DataFrame`` (eager)."""
        raise NotImplementedError(_NOT_YET.format(method="scan"))

    def materialize(self, expr: TableExpr) -> Any:
        """Identity for pandas (already eager)."""
        raise NotImplementedError(_NOT_YET.format(method="materialize"))

    def to_pandas(self, expr: TableExpr) -> Any:
        """Identity / shallow copy."""
        raise NotImplementedError(_NOT_YET.format(method="to_pandas"))

    def to_polars(self, expr: TableExpr) -> Any:
        """Convert to ``polars.DataFrame``."""
        raise NotImplementedError(_NOT_YET.format(method="to_polars"))

    def write(self, expr: TableExpr, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Write the pandas frame via the FormatAdapter layer."""
        raise NotImplementedError(_NOT_YET.format(method="write"))


__all__ = ["PandasEngine"]
