"""Approval prompts + ``ApprovalRequired`` catcher (task 4.7, architecture §6.5).

The cost model in :mod:`datagrove.operations` raises
:class:`~datagrove.operations.ApprovalRequired` when an op exceeds the
approval threshold. CLI commands wrap their gated calls with
:func:`run_with_approval` (or use the lower-level
:func:`prompt_approval` directly) so the human is asked once, the
yes/no answer is recorded, and the wrapped call is retried with
``approve=True``.

Auto-approve channels (no prompt, immediate yes):

* CLI flag ``--yes`` / ``-y`` — passed by the caller into ``yes=True``.
* Env var ``DATAGROVE_AUTO_APPROVE=1`` — global escape hatch for
  automation. Falsy ("0", empty, unset) means "prompt".

Both channels are checked here so every CLI command honours them
identically; commands only have to pass through their ``--yes`` flag.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar

from datagrove.operations import ApprovalRequired

from .render import console

__all__ = ["AUTO_APPROVE_ENV_VAR", "is_auto_approve", "prompt_approval", "run_with_approval"]

logger = logging.getLogger(__name__)

AUTO_APPROVE_ENV_VAR = "DATAGROVE_AUTO_APPROVE"

T = TypeVar("T")


def is_auto_approve() -> bool:
    """Return ``True`` when ``DATAGROVE_AUTO_APPROVE`` env var is set truthy.

    Truthy values: ``"1"``, ``"true"``, ``"yes"``, ``"y"`` (case-insensitive).
    Anything else (including unset) is falsy.
    """
    raw = os.environ.get(AUTO_APPROVE_ENV_VAR, "")
    return raw.strip().lower() in {"1", "true", "yes", "y"}


def prompt_approval(exc: ApprovalRequired, *, yes: bool = False) -> bool:
    """Decide whether to approve the gated op.

    Decision order:

    1. ``yes=True`` (CLI ``--yes`` flag) → silent yes.
    2. ``DATAGROVE_AUTO_APPROVE=1`` env → silent yes.
    3. Interactive: ask ``y/N`` on the shared console (stderr).
       Default on Enter is **No** so a fat-fingered prompt doesn't
       commit a 5-minute op.

    Returns:
        ``True`` if approved, ``False`` if declined.
    """
    if yes:
        logger.info("auto-approving %s (--yes)", exc.cost.op_name)
        return True
    if is_auto_approve():
        logger.info("auto-approving %s (%s=1)", exc.cost.op_name, AUTO_APPROVE_ENV_VAR)
        return True

    # Interactive prompt on the shared console (stderr, so --json on
    # stdout still produces a parseable doc when the user types y).
    console.print(
        f"[yellow]Op {exc.cost.op_name!r} estimated at "
        f"{exc.cost.est_seconds():.1f}s exceeds {exc.threshold_s:.1f}s approval threshold.[/yellow]"
    )
    answer = input("Proceed? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def run_with_approval(
    func: Callable[..., T],
    *args: Any,
    yes: bool = False,
    **kwargs: Any,
) -> T:
    """Run ``func(*args, **kwargs)``; on :class:`ApprovalRequired`, prompt + retry.

    ``func`` must accept an ``approve`` keyword (the gating contract).
    The retry passes ``approve=True`` after a positive prompt; a
    declined prompt re-raises :class:`ApprovalRequired` so callers can
    convert to a non-zero exit code.

    Examples:
        >>> from datagrove.operations import OperationCost, gate
        >>> from datagrove.cli.prompts import run_with_approval
        >>> def heavy(*, approve=False):
        ...     gate(OperationCost(op_name='demo', row_count=1), approve=approve)
        ...     return 'ok'
        >>> run_with_approval(heavy, yes=True)
        'ok'
    """
    try:
        return func(*args, **kwargs)
    except ApprovalRequired as exc:
        if prompt_approval(exc, yes=yes):
            return func(*args, approve=True, **kwargs)
        raise
