"""OPTIONAL EXTRA — self-hostable GMNS FastAPI server (task 4.10).

Install: ``pip install netstead[server]``. Run via ``netstead server run
--config path/to/config.yaml`` (CLI command added in this same PR).

The app is built by :func:`build_app` which composes on
:func:`corral.api.build_app` and layers the network-aware router
on top via the ``extra_router_factory`` hook. See
:mod:`netstead.server.app` for the endpoints.

Optional-import guard: the [server] extra installs ``fastapi`` +
``uvicorn`` + ``pydantic-settings``. If you ``import netstead.server``
without those installed, you'll see a clean ``ImportError`` from
:mod:`netstead.server.app` with the install hint.
"""

try:
    import fastapi  # noqa: F401
except ImportError as e:  # pragma: no cover - defensive
    raise ImportError("netstead.server requires the [server] extra: pip install 'netstead[server]'") from e

from .app import build_app

__all__ = ["build_app"]
