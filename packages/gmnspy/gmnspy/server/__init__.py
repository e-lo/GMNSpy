"""OPTIONAL EXTRA — self-hostable GMNS FastAPI server (task 4.10).

Install: ``pip install gmnspy[server]``. Run via ``gmnspy server run
--config path/to/config.yaml`` (CLI command added in this same PR).

The app is built by :func:`build_app` which composes on
:func:`datagrove.api.build_app` and layers the network-aware router
on top via the ``extra_router_factory`` hook. See
:mod:`gmnspy.server.app` for the endpoints.

Optional-import guard: the [server] extra installs ``fastapi`` +
``uvicorn`` + ``pydantic-settings``. If you ``import gmnspy.server``
without those installed, you'll see a clean ``ImportError`` from
:mod:`gmnspy.server.app` with the install hint.
"""

try:
    import fastapi  # noqa: F401
except ImportError as e:  # pragma: no cover - defensive
    raise ImportError("gmnspy.server requires the [server] extra: pip install 'gmnspy[server]'") from e

from .app import build_app

__all__ = ["build_app"]
