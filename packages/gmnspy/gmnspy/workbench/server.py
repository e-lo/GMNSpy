"""Assemble the workbench FastAPI app: static front end + API routers."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routes.core import core_router
from .session import Session

__all__ = ["STATIC_DIR", "build_app"]

STATIC_DIR = Path(__file__).parent / "static"


def build_app(session: Session) -> FastAPI:
    """Return the FastAPI app serving ``session``."""
    app = FastAPI(title="GMNSpy Workbench")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(core_router(session))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    return app
