"""GMNS-aware FastAPI app — composes on :mod:`datagrove.api` (task 4.10).

Adds GMNS-specific endpoints on top of the generic datagrove ones:

* ``GET /networks`` / ``GET /networks/{id}`` — aliases for
  ``/packages`` / ``/packages/{id}`` with the GMNS-flavoured metadata
  (``spec_version`` + named-table summary).
* ``POST /networks/{id}/quality`` — run the GMNS rule pack, return
  the :class:`ValidationReport` as JSON via
  :meth:`~datagrove.reports.ValidationReport.to_dict` (canonical
  wire shape; matches the CLI ``--json`` + MCP shapes).

Reuses datagrove's auth + registry — no parallel infrastructure. The
registry's ``package_loader`` is set to :meth:`Network.from_source`
so the cache holds :class:`Network` instances directly (and the GMNS
metadata endpoint doesn't need to double-load).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from datagrove.api import AuthDep, PackageRegistry, ServerSettings
from datagrove.api import build_app as build_generic_app
from fastapi import APIRouter, Depends

from gmnspy import Network
from gmnspy.quality import register_all

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI


__all__ = ["build_app"]

logger = logging.getLogger(__name__)


def build_app(settings: ServerSettings | None = None) -> FastAPI:
    """Return a FastAPI app exposing GMNS networks + the generic datagrove endpoints.

    Wraps :func:`datagrove.api.build_app` with the GMNS-aware
    ``package_loader`` (so the registry caches :class:`Network`
    instances) and attaches the network-aware router via the
    ``extra_router_factory`` hook.

    Args:
        settings: :class:`ServerSettings`. The ``packages`` list is
            treated as GMNS networks (each ``source`` is passed to
            :meth:`Network.from_source`).

    Returns:
        The :class:`FastAPI` app, ready for ``uvicorn.run(app, ...)``.
    """
    # Ensure the GMNS quality rule pack is registered for /networks/{id}/quality.
    register_all()
    return build_generic_app(
        settings,
        package_loader=Network.from_source,
        extra_router_factory=_build_network_router,
    )


def _build_network_router(registry: PackageRegistry, auth_dep: AuthDep) -> APIRouter:
    """Return the GMNS-aware router (mounted at ``/networks``)."""
    from datagrove.quality import run_quality

    router = APIRouter(prefix="/networks", tags=["networks"])

    @router.get("", dependencies=[Depends(auth_dep)])
    def list_networks() -> list[dict[str, Any]]:
        """List all configured GMNS networks (alias for /packages)."""
        return [registry.describe(pid) for pid in registry.list_ids()]

    @router.get("/{net_id}", dependencies=[Depends(auth_dep)])
    def get_network(net_id: str) -> dict[str, Any]:
        """Return GMNS-aware metadata: spec version + named-table summary.

        The registry is configured with ``Network.from_source`` as its
        loader (see :func:`build_app`), so the cached package IS a
        :class:`Network` and ``spec_version`` is available directly —
        no double-load, no fallback ``getattr``.
        """
        net = registry.require(net_id)
        # The registry holds Network instances thanks to package_loader=Network.from_source
        # in build_app; .spec_version is part of the Network surface. Type-check via duck:
        spec_version = getattr(net, "spec_version", None)
        return {
            "id": net_id,
            "name": net.spec.name,
            "spec_version": spec_version,
            "engine": type(net.engine).__name__,
            "links": net.safe_count("link"),
            "nodes": net.safe_count("node"),
            "table_count": len(net.tables),
            "tables": sorted(net.tables.keys()),
        }

    @router.post("/{net_id}/quality", dependencies=[Depends(auth_dep)])
    def run_quality_endpoint(net_id: str) -> dict[str, Any]:
        """Run the GMNS data-quality rule pack; return ``report.to_dict()``."""
        net = registry.require(net_id)
        report = run_quality(net)
        return report.to_dict()

    return router
