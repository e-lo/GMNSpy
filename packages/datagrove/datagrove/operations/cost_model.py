"""Heuristic cost model for datagrove operations (architecture §6.5).

Provides :class:`OperationCost` plus a small table of per-op coefficients
calibrated on the Leavenworth + synthetic regional fixtures. The Phase 5
nightly bench job (issue #126) re-fits these per ibis/duckdb release.
``est_seconds()`` is an order-of-magnitude hint for gating prompts —
**not a performance guarantee**. One coefficient set covers the default
ibis+duckdb path for v1.0; per-engine models are out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass

# Coefficients are seconds-per-million-rows for each op kind. They are
# deliberately conservative on the high side so that gating prompts fire
# slightly early rather than slightly late — it's friendlier to ask once
# and skip than to silently run a 5-minute query.
COEFFICIENTS: dict[str, float] = {
    "read_parquet_per_million_rows": 0.5,
    "read_csv_per_million_rows": 2.0,
    "read_duckdb_per_million_rows": 0.3,
    "validate_schema_per_million_rows": 1.0,
    "validate_fk_per_million_rows": 1.5,
    "validate_structural_per_million_rows": 1.2,
    "scope_bbox_per_million_rows": 0.2,
    "scope_polygon_per_million_rows": 0.8,
    "write_parquet_per_million_rows": 0.6,
    "write_csv_per_million_rows": 2.5,
}

# Fallback used when we can't resolve op_name → coefficient. Picked to
# be larger than the cheapest read but smaller than FK validation so
# unknown ops are neither hidden nor over-flagged.
_DEFAULT_COEFFICIENT = 1.0


def _resolve_coefficient(op_name: str, fmt: str | None) -> float:
    """Return seconds-per-million-rows for ``(op_name, fmt)``.

    Resolution rules (most-specific first):

    * ``read`` + ``fmt`` → ``read_{fmt}_per_million_rows`` if present.
    * ``write`` + ``fmt`` → ``write_{fmt}_per_million_rows`` if present.
    * Bare ``op_name`` → ``{op_name}_per_million_rows`` if present.
    * Otherwise → :data:`_DEFAULT_COEFFICIENT`.
    """
    if op_name in ("read", "write") and fmt:
        key = f"{op_name}_{fmt}_per_million_rows"
        if key in COEFFICIENTS:
            return COEFFICIENTS[key]
    key = f"{op_name}_per_million_rows"
    if key in COEFFICIENTS:
        return COEFFICIENTS[key]
    return _DEFAULT_COEFFICIENT


@dataclass(frozen=True)
class OperationCost:
    """Heuristic estimate of an operation's wall time.

    Attributes:
        op_name: Logical operation kind, e.g. ``"read"``, ``"validate_fk"``,
            ``"scope_bbox"``. Used (with ``fmt``) to look up a coefficient
            in :data:`COEFFICIENTS`.
        n_rows: Approximate row count of the input. May be a planner
            estimate — exact counts are not required.
        n_tables: Number of tables involved. Multi-table ops (FK checks,
            joins) cost roughly linearly in table count for the v1.0 model.
        fmt: Source format if known (e.g. ``"parquet"``, ``"csv"``,
            ``"duckdb"``). Only consulted for ``read`` / ``write`` ops.

    Examples:
        Estimate a 5M-row parquet read::

            >>> from datagrove.operations import OperationCost
            >>> cost = OperationCost(op_name="read", n_rows=5_000_000, fmt="parquet")
            >>> round(cost.est_seconds(), 2)
            2.5
    """

    op_name: str
    n_rows: int
    n_tables: int = 1
    fmt: str | None = None

    def est_seconds(self) -> float:
        """Return the estimated wall time in seconds.

        The estimate is ``coefficient * (n_rows / 1_000_000) * n_tables``
        where ``coefficient`` comes from :data:`COEFFICIENTS` (see
        :func:`_resolve_coefficient` for resolution rules). This is a
        documented heuristic, not a guarantee — see the module docstring.
        """
        coefficient = _resolve_coefficient(self.op_name, self.fmt)
        rows_in_millions = self.n_rows / 1_000_000
        return float(coefficient * rows_in_millions * self.n_tables)
