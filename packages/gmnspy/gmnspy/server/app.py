"""GMNS-aware FastAPI app — composes on :mod:`datagrove.api` (task 4.10).

Adds GMNS-specific endpoints on top of the generic datagrove ones:

* ``GET /networks`` / ``GET /networks/{id}`` — aliases for
  ``/packages`` / ``/packages/{id}`` with the GMNS-flavoured metadata
  (``spec_version`` + named-table summary).
* ``POST /networks/{id}/quality`` — run the GMNS rule pack, return
  the :class:`ValidationReport` as JSON.

Reuses datagrove's auth + registry — no parallel infrastructure.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from datagrove.api import ServerSettings
from datagrove.api import build_app as build_generic_app
from datagrove.api.app import _safe_get
from fastapi import APIRouter, Depends

from gmnspy import Network
from gmnspy.quality import register_all

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from datagrove.api.app import PackageRegistry
    from fastapi import FastAPI


__all__ = ["build_app"]

logger = logging.getLogger(__name__)


def build_app(settings: ServerSettings | None = None) -> FastAPI:
    """Return a FastAPI app exposing GMNS networks + the generic datagrove endpoints.

    Wraps :func:`datagrove.api.build_app` and attaches the
    network-aware router via the ``extra_router_factory`` hook so
    the composition is declarative — no post-construction mutation.

    Args:
        settings: :class:`ServerSettings`. The ``packages`` list is
            treated as GMNS networks (each ``source`` is passed to
            :meth:`gmnspy.Network.from_source`).

    Returns:
        The :class:`FastAPI` app, ready for ``uvicorn.run(app, ...)``.
    """
    # Ensure the GMNS quality rule pack is registered for /networks/{id}/quality.
    register_all()
    return build_generic_app(settings, extra_router_factory=_build_network_router)


def _build_network_router(registry: PackageRegistry, auth_dep: Callable) -> APIRouter:
    """Return the GMNS-aware router (mounted at ``/networks``)."""
    from datagrove.quality import run_quality

    router = APIRouter(prefix="/networks", tags=["networks"])

    @router.get("", dependencies=[Depends(auth_dep)])
    def list_networks() -> list[dict[str, Any]]:
        """List all configured GMNS networks (alias for /packages)."""
        return [registry.describe(pid) for pid in registry.list_ids()]

    @router.get("/{net_id}", dependencies=[Depends(auth_dep)])
    def get_network(net_id: str) -> dict[str, Any]:
        """Return GMNS-aware metadata: spec version + named-table summary."""
        pkg = _safe_get(registry, net_id)
        # The registry returns a Package; if the source was loaded via
        # Network.from_source upstream of the registry it'd be a Network.
        # Today registry.get always returns Package. To get GMNS spec_version
        # we materialise a Network on the source path. Small extra cost but
        # the response is dominated by table counts anyway.
        spec_version = getattr(pkg, "spec_version", None)
        if spec_version is None:
            # Best-effort: re-resolve as a Network for the spec_version stamp.
            try:
                net = Network.from_source(registry._refs[net_id].source)
                spec_version = net.spec_version
            except Exception:  # pragma: no cover - resilient fallback
                spec_version = None
        return {
            "id": net_id,
            "name": pkg.spec.name,
            "spec_version": spec_version,
            "engine": type(pkg.engine).__name__,
            "links": _safe_count(pkg, "link"),
            "nodes": _safe_count(pkg, "node"),
            "table_count": len(pkg.tables),
            "tables": sorted(pkg.tables.keys()),
        }

    @router.post("/{net_id}/quality", dependencies=[Depends(auth_dep)])
    def run_quality_endpoint(net_id: str) -> dict[str, Any]:
        """Run the GMNS data-quality rule pack; return the report as JSON."""
        pkg = _safe_get(registry, net_id)
        report = run_quality(pkg)
        return _report_to_json(report)

    return router


def _safe_count(pkg: Any, table_name: str) -> int | None:
    """Return ``pkg.tables[table_name].count()`` or ``None``."""
    table = pkg.tables.get(table_name)
    if table is None:
        return None
    try:
        return table.count()
    except Exception:  # pragma: no cover - resilient
        return None


def _report_to_json(report: Any) -> dict[str, Any]:
    """Flatten a :class:`ValidationReport` to JSON-safe ``{issues: [...]}``.

    Duplicates the helper in :mod:`datagrove.api.app` because importing
    a private from datagrove.api would couple too tightly; the helper
    is 10 lines and the duplication is intentional.
    """
    issues = []
    for issue in report.issues:
        issues.append(
            {
                "severity": getattr(getattr(issue, "severity", None), "value", None),
                "category": getattr(getattr(issue, "category", None), "value", None),
                "code": getattr(issue, "code", None),
                "message": getattr(issue, "message", None),
                "table": getattr(issue, "table", None),
                "column": getattr(issue, "column", None),
                "row": getattr(issue, "row", None),
                "fix_hint": getattr(issue, "fix_hint", None),
                "extra": getattr(issue, "extra", {}),
            }
        )
    return {"issues": issues, "spec_version": getattr(report, "spec_version", None)}
