"""Typed, user-facing workbench errors (shared by the session, jobs, paths, and estimates).

Every subclass of :class:`ActionError` is recorded in the session history with
its class name as ``error_type``; ``payload`` (when set) becomes the entry's
``result`` so the UI can act on it (e.g. show the estimate an approval needs).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .estimate import Estimate

__all__ = ["ActionError", "ApprovalRequired", "JobCancelled", "NotSupportedYet", "PathNotAllowed"]


class ActionError(Exception):
    """An action could not be applied; the message is shown to the user."""

    payload: dict[str, Any] | None = None


class NotSupportedYet(ActionError):
    """The action is in the schema but its handler ships in a later phase."""


class PathNotAllowed(ActionError):
    """A local path resolved outside ``io.allowed_roots``."""


class JobCancelled(ActionError):
    """A background job stopped at a checkpoint because cancellation was requested."""


class ApprovalRequired(ActionError):
    """A build's estimate is over ``app.approve_above_s`` (or unavailable) and ``approved`` was false."""

    def __init__(self, estimate: Estimate, threshold_s: float) -> None:
        """Keep the estimate (``.estimate``) and expose it as the history payload."""
        self.estimate = estimate
        self.threshold_s = threshold_s
        self.payload = {"estimate": estimate.to_dict(), "threshold_s": threshold_s}
        if estimate.seconds is None:
            detail = f"the size estimate is unavailable ({estimate.basis})"
        else:
            detail = f"estimated ~{estimate.seconds:.0f} s, over the {threshold_s:.0f} s approval threshold"
        super().__init__(f"approval required: {detail}; re-run with approved=True")
