"""Tests for the heuristic OperationCost estimator (task 3.1)."""

from __future__ import annotations

import pytest
from datagrove.operations import OperationCost
from datagrove.operations.cost_model import COEFFICIENTS


@pytest.mark.parametrize(
    ("op_name", "n_rows", "fmt", "coefficient_key"),
    [
        ("read", 1_000_000, "parquet", "read_parquet_per_million_rows"),
        ("read", 1_000_000, "csv", "read_csv_per_million_rows"),
        ("read", 1_000_000, "duckdb", "read_duckdb_per_million_rows"),
        ("validate_schema", 2_000_000, None, "validate_schema_per_million_rows"),
        ("validate_fk", 500_000, None, "validate_fk_per_million_rows"),
        ("scope_bbox", 4_000_000, None, "scope_bbox_per_million_rows"),
    ],
)
def test_est_seconds_scales_linearly_with_rows(op_name, n_rows, fmt, coefficient_key):
    cost = OperationCost(op_name=op_name, n_rows=n_rows, fmt=fmt)
    expected = COEFFICIENTS[coefficient_key] * (n_rows / 1_000_000)
    assert cost.est_seconds() == pytest.approx(expected)


def test_est_seconds_zero_rows_is_zero():
    cost = OperationCost(op_name="read", n_rows=0, fmt="parquet")
    assert cost.est_seconds() == 0.0


def test_unknown_op_returns_finite_default():
    cost = OperationCost(op_name="totally_made_up_op", n_rows=1_000_000)
    est = cost.est_seconds()
    assert est >= 0.0
    # Unknown ops should not silently mis-report as free.
    assert est > 0.0


def test_n_tables_multiplier():
    one = OperationCost(op_name="validate_fk", n_rows=1_000_000, n_tables=1).est_seconds()
    five = OperationCost(op_name="validate_fk", n_rows=1_000_000, n_tables=5).est_seconds()
    assert five > one


def test_frozen_dataclass_is_immutable():
    cost = OperationCost(op_name="read", n_rows=10, fmt="parquet")
    with pytest.raises((AttributeError, Exception)):
        cost.n_rows = 999  # type: ignore[misc]
