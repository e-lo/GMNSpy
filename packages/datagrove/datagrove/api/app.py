"""FastAPI app factory + generic package endpoints (datagrove.api, task 4.10).

This is the framework half of architecture §6.8: a thin
:class:`fastapi.FastAPI` factory that wires the configured packages
behind bearer auth and exposes the four generic endpoints. Domain
packages (e.g. :mod:`gmnspy.server`) call this then attach their own
routers — same composition pattern as the CLI's
:func:`datagrove.cli.app.build_app`.

Endpoints (v1):

* ``GET /health`` — always 200; no auth required (load-balancer probe).
* ``GET /packages`` — list configured package ids + descriptions.
* ``GET /packages/{id}`` — package metadata (table list + row counts).
* ``GET /packages/{id}/spec`` — resolved Frictionless DataPackage JSON.
* ``POST /packages/{id}/validate`` — run full validation, return
  :class:`~datagrove.reports.ValidationReport` as JSON.

Defaults intentionally match the CLI's ``--json`` contract so an MCP
client / agent / curl invocation gets the same shape it would get
from the local commands.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, status

from datagrove.dataset import Package

from .auth import build_auth_dependency
from .config import ServerSettings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import APIRouter

__all__ = ["PackageRegistry", "build_app"]

logger = logging.getLogger(__name__)


class PackageRegistry:
    """Lazy registry mapping public id → :class:`Package`.

    Built once at app startup from :class:`ServerSettings.packages`;
    each :meth:`get` materialises the package on first access and
    caches it. Hot-reload + cache invalidation are out of scope for
    v1 — restart the server to pick up a config change.
    """

    def __init__(self, settings: ServerSettings) -> None:
        """Index settings by public id for O(1) lookup."""
        self._refs = {pkg.id: pkg for pkg in settings.packages}
        self._cache: dict[str, Package] = {}

    def list_ids(self) -> list[str]:
        """Return all configured public ids (insertion order)."""
        return list(self._refs)

    def describe(self, pkg_id: str) -> dict[str, Any]:
        """Return ``{id, source, description}`` without loading the package."""
        if pkg_id not in self._refs:
            raise KeyError(pkg_id)
        ref = self._refs[pkg_id]
        return {"id": ref.id, "source": ref.source, "description": ref.description}

    def get(self, pkg_id: str) -> Package:
        """Load + cache the :class:`Package` for ``pkg_id``."""
        if pkg_id in self._cache:
            return self._cache[pkg_id]
        if pkg_id not in self._refs:
            raise KeyError(pkg_id)
        pkg = Package.from_source(self._refs[pkg_id].source)
        self._cache[pkg_id] = pkg
        return pkg


def build_app(
    settings: ServerSettings | None = None,
    *,
    extra_router_factory: Callable[[PackageRegistry, Callable], APIRouter] | None = None,
) -> FastAPI:
    """Return a :class:`FastAPI` wired with the generic datagrove endpoints.

    Args:
        settings: :class:`ServerSettings` to mount. Defaults to
            :class:`ServerSettings` defaults (localhost, no packages).
        extra_router_factory: Optional callable used by domain packages
            (gmnspy) to attach extra routers. The callable receives
            the :class:`PackageRegistry` and the auth dependency, and
            returns a :class:`fastapi.APIRouter` the factory mounts on
            top of the generic routes. Keeps gmnspy's composition path
            clean — no need to mutate the app post-construction.

    Returns:
        A fully wired :class:`FastAPI` instance. The caller passes it
        to :func:`uvicorn.run` (or any ASGI server).
    """
    settings = settings or ServerSettings()
    settings.warn_on_unsafe_combinations()
    registry = PackageRegistry(settings)
    auth_dep = build_auth_dependency(settings.auth)

    app = FastAPI(
        title="datagrove API",
        description=(
            "Generic Frictionless data-package HTTP service. Every endpoint matches "
            "the CLI's --json contract for response shape."
        ),
        version="0.1.0",
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Liveness probe. No auth; safe to expose to load balancers."""
        return {"status": "ok"}

    @app.get("/packages", dependencies=[Depends(auth_dep)], tags=["packages"])
    def list_packages() -> list[dict[str, Any]]:
        """List all configured package ids (without materialising them)."""
        return [registry.describe(pid) for pid in registry.list_ids()]

    @app.get("/packages/{pkg_id}", dependencies=[Depends(auth_dep)], tags=["packages"])
    def get_package(pkg_id: str) -> dict[str, Any]:
        """Return metadata about ``pkg_id`` — table list + row counts."""
        pkg = _safe_get(registry, pkg_id)
        tables = []
        for name, table in pkg.tables.items():
            try:
                tables.append({"name": name, "rows": table.count(), "columns": table.columns()})
            except Exception as exc:  # pragma: no cover - per-table resilience
                logger.warning("get_package: skipping table %r — %s", name, exc)
        return {
            "id": pkg_id,
            "name": pkg.spec.name,
            "engine": type(pkg.engine).__name__,
            "table_count": len(pkg.tables),
            "tables": tables,
        }

    @app.get("/packages/{pkg_id}/spec", dependencies=[Depends(auth_dep)], tags=["packages"])
    def get_spec(pkg_id: str) -> dict[str, Any]:
        """Return the resolved Frictionless ``DataPackage`` as JSON."""
        pkg = _safe_get(registry, pkg_id)
        return pkg.spec.model_dump(mode="json")

    @app.post("/packages/{pkg_id}/validate", dependencies=[Depends(auth_dep)], tags=["packages"])
    def validate_package(pkg_id: str) -> dict[str, Any]:
        """Run full validation; return the :class:`ValidationReport` as JSON."""
        pkg = _safe_get(registry, pkg_id)
        report = pkg.validate()
        return _report_to_json(report)

    # Domain extensions (e.g. gmnspy.server) layer on via a router factory.
    if extra_router_factory is not None:
        router = extra_router_factory(registry, auth_dep)
        app.include_router(router)

    return app


def _safe_get(registry: PackageRegistry, pkg_id: str) -> Package:
    """Return ``registry.get(pkg_id)`` or raise 404."""
    try:
        return registry.get(pkg_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"package {pkg_id!r} not configured",
        ) from None


def _report_to_json(report: Any) -> dict[str, Any]:
    """Flatten a :class:`ValidationReport` to JSON-safe ``{issues: [...]}``."""
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
