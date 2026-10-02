"""Assemble the workbench FastAPI app: static front end + API routers."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .routes.core import core_router
from .routes.network import network_router
from .session import Session

__all__ = ["STATIC_DIR", "build_app"]

STATIC_DIR = Path(__file__).parent / "static"

#: Hosts a loopback bind trusts, as lowercased ``_host_name()`` output.
#: "testserver" is what Starlette's TestClient sends as its Host header.
_LOOPBACK_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}

#: Bind hosts considered loopback-only (not reachable off the local machine).
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _host_name(header: str) -> str:
    """Return the hostname portion of a ``Host`` header, with any ``:port`` stripped.

    Bracket-aware: an IPv6 literal like ``[::1]:8850`` contains colons of its
    own, so a plain ``split(":")[0]`` would truncate it to ``"["``. For a
    bracketed host we keep everything through the closing ``]``; otherwise we
    strip at most one trailing ``:port`` from the right.
    """
    if header.startswith("["):
        end = header.find("]")
        name = header if end == -1 else header[: end + 1]
    else:
        name = header.rsplit(":", 1)[0] if ":" in header else header
    return name.lower()


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
        @app.middleware("http")
        async def _check_host(request: Request, call_next):
            if _host_name(request.headers.get("host", "")) not in _LOOPBACK_ALLOWED_HOSTS:
                return PlainTextResponse("Invalid host header", status_code=400)
            return await call_next(request)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(core_router(session))
    app.include_router(network_router(session))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    return app
