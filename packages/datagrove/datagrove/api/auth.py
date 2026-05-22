"""Auth dependencies for FastAPI — bearer-token + none modes (datagrove.api, task 4.10).

One :func:`build_auth_dependency` factory returns a callable suitable
for ``fastapi.Depends``. The factory closes over the configured
:class:`~datagrove.api.config.AuthSettings` so endpoints stay agnostic
to which auth mode is active.

Token comparison uses :func:`hmac.compare_digest` to avoid timing
attacks even though our tokens are bearer-style (Phase 5 hardening
could move to OAuth2 / mTLS; the dependency contract stays the same).
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import Header, HTTPException, status

from .config import AuthSettings

__all__ = ["build_auth_dependency"]

logger = logging.getLogger(__name__)


def build_auth_dependency(auth: AuthSettings) -> Callable[[str | None], None]:
    """Return a FastAPI dependency callable that enforces ``auth`` on every request.

    The returned callable takes the request's ``Authorization`` header
    (FastAPI injects it via :class:`fastapi.Header`) and either returns
    ``None`` (pass) or raises :class:`fastapi.HTTPException(401)`.

    Args:
        auth: The active auth configuration. ``kind == "none"`` returns
            an unconditional-pass dependency; ``kind == "bearer"``
            returns one that compares the ``Authorization`` header
            against :attr:`AuthSettings.token` in constant time.

    Returns:
        A no-arg-friendly callable for ``fastapi.Depends(...)``.

    Examples:
        >>> from datagrove.api.config import AuthSettings
        >>> dep = build_auth_dependency(AuthSettings(kind="none"))
        >>> dep(None)  # passes
    """
    if auth.kind == "none":

        def _pass(authorization: Annotated[str | None, Header()] = None) -> None:
            """Open access — no auth check."""
            return None

        return _pass

    if auth.token is None:
        # Misconfiguration: bearer mode requires a token. Fail-fast at
        # build time rather than silently letting every request through.
        raise ValueError("AuthSettings(kind='bearer') requires `token` to be set.")

    expected = f"Bearer {auth.token}"

    def _check_bearer(authorization: Annotated[str | None, Header()] = None) -> None:
        """Reject requests missing or with a wrong Bearer token."""
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or invalid Bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return _check_bearer
