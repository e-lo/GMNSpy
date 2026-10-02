"""GMNSpy Workbench: one live session served as a local web app (``gmnspy app``).

``Session`` is the action bus; ``build_app``/``serve`` need the ``[server]``
extra (FastAPI + uvicorn) and are imported lazily so ``Session`` works without it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .actions import (
    ClearSelection,
    CloseNetwork,
    Navigate,
    OpenNetwork,
    Select,
    SetActiveNetwork,
    SetSetting,
    Style,
)
from .session import ActionError, NotSupportedYet, Session

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = [
    "ActionError",
    "ClearSelection",
    "CloseNetwork",
    "Navigate",
    "NotSupportedYet",
    "OpenNetwork",
    "Select",
    "Session",
    "SetActiveNetwork",
    "SetSetting",
    "Style",
    "build_app",
    "serve",
]


def build_app(session: Session) -> FastAPI:
    """Return the workbench FastAPI app over ``session``."""
    from .server import build_app as _build_app

    return _build_app(session)


def serve(session: Session) -> None:
    """Serve ``session`` with uvicorn at ``settings.app.host:port`` (blocks)."""
    import uvicorn

    app_settings = session.settings.app
    uvicorn.run(build_app(session), host=app_settings.host, port=app_settings.port)
