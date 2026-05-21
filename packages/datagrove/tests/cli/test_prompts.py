"""Tests for the CLI approval-prompt helpers (task 4.7 / issue #94)."""

from __future__ import annotations

import os

import pytest
from datagrove.cli.prompts import (
    AUTO_APPROVE_ENV_VAR,
    is_auto_approve,
    prompt_approval,
    run_with_approval,
)
from datagrove.operations import ApprovalRequired, OperationCost


def _make_approval_required() -> ApprovalRequired:
    """Build a realistic :class:`ApprovalRequired` to exercise prompt_approval / run_with_approval."""
    cost = OperationCost(op_name="big_op", n_rows=10_000_000)  # ~ over default 180s budget
    return ApprovalRequired(cost=cost, threshold_s=180.0)


# ---------------------------------------------------------------------------
# is_auto_approve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("YES", True), ("y", True)])
def test_is_auto_approve_truthy_values(monkeypatch, value, expected):
    """All four truthy spellings (case-insensitive) flip auto-approve on."""
    monkeypatch.setenv(AUTO_APPROVE_ENV_VAR, value)
    assert is_auto_approve() is expected


@pytest.mark.parametrize("value", ["0", "false", "no", "", "anything-else"])
def test_is_auto_approve_falsy_values(monkeypatch, value):
    """Non-truthy values (including unset) keep auto-approve off."""
    monkeypatch.setenv(AUTO_APPROVE_ENV_VAR, value)
    assert is_auto_approve() is False


def test_is_auto_approve_unset(monkeypatch):
    """Unset env var → False."""
    monkeypatch.delenv(AUTO_APPROVE_ENV_VAR, raising=False)
    assert is_auto_approve() is False


# ---------------------------------------------------------------------------
# prompt_approval
# ---------------------------------------------------------------------------


def test_prompt_approval_yes_flag_short_circuits():
    """yes=True skips both env + interactive checks."""
    assert prompt_approval(_make_approval_required(), yes=True) is True


def test_prompt_approval_env_short_circuits(monkeypatch):
    """DATAGROVE_AUTO_APPROVE=1 skips the interactive prompt."""
    monkeypatch.setenv(AUTO_APPROVE_ENV_VAR, "1")
    assert prompt_approval(_make_approval_required()) is True


def test_prompt_approval_interactive_no(monkeypatch):
    """Default Enter (empty input) → False (don't run a 5-minute op by accident)."""
    monkeypatch.delenv(AUTO_APPROVE_ENV_VAR, raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert prompt_approval(_make_approval_required()) is False


def test_prompt_approval_interactive_yes(monkeypatch):
    """Typing 'y' returns True."""
    monkeypatch.delenv(AUTO_APPROVE_ENV_VAR, raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert prompt_approval(_make_approval_required()) is True


# ---------------------------------------------------------------------------
# run_with_approval
# ---------------------------------------------------------------------------


def test_run_with_approval_passes_through_when_no_block():
    """A function that never raises just runs normally."""
    calls = {"n": 0}

    def cheap(*, approve: bool = False) -> str:
        calls["n"] += 1
        return "done"

    assert run_with_approval(cheap) == "done"
    assert calls["n"] == 1


def test_run_with_approval_retries_with_approve_true_after_yes(monkeypatch):
    """First call raises ApprovalRequired, prompt says yes, retry succeeds with approve=True."""
    state = {"first_call": True, "saw_approve": None}

    def heavy(*, approve: bool = False) -> str:
        if state["first_call"]:
            state["first_call"] = False
            raise _make_approval_required()
        state["saw_approve"] = approve
        return "done"

    assert run_with_approval(heavy, yes=True) == "done"
    assert state["saw_approve"] is True


def test_run_with_approval_propagates_decline(monkeypatch):
    """If the prompt is declined, ApprovalRequired propagates so callers can exit non-zero."""
    monkeypatch.delenv(AUTO_APPROVE_ENV_VAR, raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "n")

    def heavy(*, approve: bool = False) -> str:
        raise _make_approval_required()

    with pytest.raises(ApprovalRequired):
        run_with_approval(heavy)


def test_run_with_approval_forwards_args_and_kwargs():
    """Positional + keyword arguments survive the wrapper unchanged."""

    def fn(a, b, *, c, approve: bool = False) -> tuple:
        return (a, b, c, approve)

    assert run_with_approval(fn, 1, 2, c=3, yes=False) == (1, 2, 3, False)


def test_auto_approve_env_var_name_is_namespaced():
    """The env var lives under DATAGROVE_ — not GMNSPY_ — per architecture §6.1.

    The namespace lives in datagrove because credential + approval
    handling are generic concerns; gmnspy inherits without re-defining.
    """
    assert AUTO_APPROVE_ENV_VAR == "DATAGROVE_AUTO_APPROVE"
    assert "GMNSPY" not in os.environ.get(AUTO_APPROVE_ENV_VAR, "_")
