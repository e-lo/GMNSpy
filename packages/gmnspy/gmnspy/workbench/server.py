"""Assemble the workbench FastAPI app: static front end + API routers."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .routes.core import core_router
from .routes.network import network_router
from .session import Session

__all__ = ["STATIC_DIR", "build_app"]

STATIC_DIR = Path(__file__).parent / "static"

#: Hosts a loopback bind trusts. TrustedHostMiddleware compares against the
#: ``Host`` header with any ``:port`` suffix stripped, so "127.0.0.1:8850"
#: matches the bare "127.0.0.1" entry. "testserver" is what Starlette's
#: TestClient sends as its Host header.
_LOOPBACK_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]", "testserver"]

#: Bind hosts considered loopback-only (not reachable off the local machine).
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def build_app(session: Session) -> FastAPI:
    """Return the FastAPI app serving ``session``."""
    app = FastAPI(title="GMNSpy Workbench")
    if session.settings.app.host in _LOOPBACK_HOSTS:
        # Binding to loopback only stops *other machines* from connecting; a
        # malicious web page on the same machine can still reach us via DNS
        # rebinding (a hostname that resolves to 127.0.0.1). Reject requests
        # whose Host header isn't one we expect. A non-loopback bind means the
        # user deliberately exposed the server, so we don't gate on Host there
        # (auth for that case is a separate, P1 item).
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=_LOOPBACK_ALLOWED_HOSTS)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(core_router(session))
    app.include_router(network_router(session))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    return app
