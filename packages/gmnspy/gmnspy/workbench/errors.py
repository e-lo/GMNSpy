"""Typed, user-facing workbench errors (shared by the session, jobs, paths, and estimates).

Every subclass of :class:`ActionError` is recorded in the session history with
its class name as ``error_type``; ``payload`` (when set) becomes the entry's
``result`` so the UI can act on it (e.g. show the estimate an approval needs).
"""

from __future__ import annotations

from typing import Any

__all__ = ["ActionError", "JobCancelled", "NotSupportedYet", "PathNotAllowed"]


class ActionError(Exception):
    """An action could not be applied; the message is shown to the user."""

    payload: dict[str, Any] | None = None


class NotSupportedYet(ActionError):
    """The action is in the schema but its handler ships in a later phase."""


class PathNotAllowed(ActionError):
    """A local path resolved outside ``io.allowed_roots``."""


class JobCancelled(ActionError):
    """A background job stopped at a checkpoint because cancellation was requested."""
