"""Assemble the workbench FastAPI app: static front end + API routers."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .routes.core import core_router
from .routes.io import io_router
from .routes.llm import llm_router
from .routes.network import network_router
from .session import Session

__all__ = ["STATIC_DIR", "build_app", "is_loopback_host"]

STATIC_DIR = Path(__file__).parent / "static"

#: Hosts a loopback bind trusts, as lowercased ``_host_name()`` output.
#: "testserver" is what Starlette's TestClient sends as its Host header.
_LOOPBACK_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}

#: Bind hosts considered loopback-only (not reachable off the local machine).
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

#: HTTP methods that can't mutate state, so cross-origin requests for them are harmless
#: (the Host-header guard above already blocks DNS-rebinding reads from another machine).
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def is_loopback_host(host: str) -> bool:
    """Whether ``host`` (a bind address, no port) is loopback-only."""
    return host in _LOOPBACK_HOSTS


def _origin_hostname(origin: str) -> str:
    """Lowercased, bracket-preserving hostname of an ``Origin`` header value.

    ``urlsplit(...).hostname`` already lowercases and strips brackets from an
    IPv6 literal; we re-add brackets so the result compares directly against
    ``_host_name()``'s bracketed IPv6 output.
    """
    hostname = urlsplit(origin).hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return hostname


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
    if is_loopback_host(session.settings.app.host):
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
            # Local CSRF guard: a cross-origin page can still POST here without
            # a CORS preflight (a "simple" request needs no custom header, and
            # recent fastapi's strict_content_type default only blocks a
            # *missing* Content-Type — a guarantee we can't rely on across
            # supported fastapi versions). For state-changing methods, reject
            # any request that names a foreign origin, by either signal a
            # browser can send on its own. Reads are left alone: they're
            # harmless, and the Host check above already covers DNS rebinding.
            if request.method not in _SAFE_METHODS:
                origin = request.headers.get("origin")
                if origin is not None and (origin == "null" or _origin_hostname(origin) not in _LOOPBACK_ALLOWED_HOSTS):
                    return PlainTextResponse("Cross-origin request rejected", status_code=403)
                if request.headers.get("sec-fetch-site") == "cross-site":
                    return PlainTextResponse("Cross-origin request rejected", status_code=403)
            return await call_next(request)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(core_router(session))
    app.include_router(io_router(session))
    app.include_router(network_router(session))
    # Key writes are refused on an exposed bind: there is no auth beyond the loopback guard (design T10).
    app.include_router(llm_router(session, allow_key_writes=is_loopback_host(session.settings.app.host)))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    return app
