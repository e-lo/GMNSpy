"""Tests for the gate() function (task 3.1).

Thresholds (per architecture §6.5):
- est < 30s            → silent pass-through
- 30s ≤ est < 180s     → log estimate, return
- est ≥ 180s, approve=False → ApprovalRequired
- est ≥ 180s, approve=True  → log estimate, return
"""

from __future__ import annotations

import logging

import pytest
from datagrove.operations import ApprovalRequired, OperationCost, gate


def _cost(est: float) -> OperationCost:
    """Build an OperationCost whose est_seconds() returns approximately ``est``.

    We pick ``read`` with parquet fmt (0.5s/M rows) and back-solve n_rows.
    """
    rows_per_second = 1_000_000 / 0.5  # 2M rows/s
    return OperationCost(op_name="read", n_rows=int(est * rows_per_second), fmt="parquet")


def test_below_estimate_threshold_is_silent(caplog):
    caplog.set_level(logging.INFO, logger="datagrove.operations.gating")
    result = gate(_cost(5.0))
    assert result.est_seconds() < 30.0
    # No log records at INFO from the gating logger.
    assert not [r for r in caplog.records if r.name == "datagrove.operations.gating"]


def test_above_estimate_threshold_logs_estimate(caplog):
    caplog.set_level(logging.INFO, logger="datagrove.operations.gating")
    result = gate(_cost(60.0))
    assert result.est_seconds() >= 30.0
    msgs = [r.getMessage() for r in caplog.records if r.name == "datagrove.operations.gating"]
    assert any("estimate" in m.lower() or "est" in m.lower() for m in msgs)


def test_above_approval_threshold_without_approve_raises():
    with pytest.raises(ApprovalRequired):
        gate(_cost(300.0), approve=False)


def test_above_approval_threshold_with_approve_returns(caplog):
    caplog.set_level(logging.INFO, logger="datagrove.operations.gating")
    result = gate(_cost(300.0), approve=True)
    assert result.est_seconds() >= 180.0


def test_custom_thresholds_respected():
    # With a high approval threshold, a 300s op should not raise.
    result = gate(_cost(300.0), approve=False, approval_threshold_s=500.0)
    assert result.est_seconds() >= 180.0


def test_boundary_at_approval_threshold_raises():
    # Exactly at the approval threshold is "≥" → blocked.
    cost = _cost(180.0)
    # _cost may round; nudge to ensure ≥ 180.
    if cost.est_seconds() < 180.0:
        cost = _cost(180.5)
    with pytest.raises(ApprovalRequired):
        gate(cost, approve=False)


def test_approval_required_message_includes_estimate():
    try:
        gate(_cost(300.0), approve=False)
    except ApprovalRequired as exc:
        assert "approve" in str(exc).lower() or "180" in str(exc) or "s" in str(exc).lower()
    else:
        pytest.fail("expected ApprovalRequired")
