"""Geographic scoping stubs — filled in by task 2.8 (issue #67).

This module is the planned home for the three spatial-scope
constructors that produce a scoped :class:`~datagrove.dataset.Package`
from a geographic predicate. The constructors are stubs today
(raise :class:`NotImplementedError`) so callers, docs, and the AI
agents implementing task 2.8 have a single clean target.

The planned constructors all return a new
:class:`~datagrove.dataset.Package` whose link / node / geometry
tables are filtered to the geometric region. Predicate pushdown into
the engine (so partitioned parquet bbox queries become true partition
prunes) is part of the 2.8 deliverable.

Cross-references:
    * Architecture: ``docs/architecture.md`` §6.2 (memory-efficient
      scoping). Spatial scopes are documented as living here in the
      generic ``datagrove.dataset.view`` module; network-aware scopes
      live in ``gmnspy.scope`` (task 3.x).
    * Issue: https://github.com/e-lo/GMNSpy/issues/67

Examples:
    Each helper raises :class:`NotImplementedError` until task 2.8 lands::

        >>> from datagrove.dataset.view import from_bbox
        >>> from_bbox(None, (0, 0, 1, 1))
        Traceback (most recent call last):
          ...
        NotImplementedError: ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.dataset import Package

__all__ = ["from_bbox", "from_geometry_buffer", "from_polygon"]


def from_bbox(
    package: Package,
    bbox: tuple[float, float, float, float],
    *,
    columns: dict[str, tuple[str, str]] | None = None,
) -> Package:
    """Return a copy of ``package`` scoped to the axis-aligned bounding box.

    Args:
        package: The source :class:`Package` to scope.
        bbox: ``(min_x, min_y, max_x, max_y)`` in the package's CRS.
        columns: Optional per-table override of which column pair to
            interpret as ``(x, y)``. Defaults to the package's GMNS-style
            convention (``x_coord`` / ``y_coord`` on the node table,
            propagated to other tables via FK).

    Raises:
        NotImplementedError: Always — landing in task 2.8 (issue #67).
    """
    raise NotImplementedError(
        "datagrove.dataset.view.from_bbox is a Phase 2 task 2.8 stub. "
        "Track progress at https://github.com/e-lo/GMNSpy/issues/67."
    )


def from_polygon(
    package: Package,
    polygon: Any,
    *,
    columns: dict[str, tuple[str, str]] | None = None,
) -> Package:
    """Return a copy of ``package`` scoped to a (possibly multi-)polygon.

    Args:
        package: The source :class:`Package` to scope.
        polygon: A shapely / GeoJSON polygon (the exact accepted type
            is finalised by task 2.8; both will be supported).
        columns: Optional per-table override of which column pair to
            interpret as ``(x, y)``. Defaults match
            :func:`from_bbox`.

    Raises:
        NotImplementedError: Always — landing in task 2.8 (issue #67).
    """
    raise NotImplementedError(
        "datagrove.dataset.view.from_polygon is a Phase 2 task 2.8 stub. "
        "Track progress at https://github.com/e-lo/GMNSpy/issues/67."
    )


def from_geometry_buffer(
    package: Package,
    geometry: Any,
    *,
    buffer_m: float,
    columns: dict[str, tuple[str, str]] | None = None,
) -> Package:
    """Return a copy of ``package`` within ``buffer_m`` of a geometry.

    Args:
        package: The source :class:`Package` to scope.
        geometry: A shapely point / line / polygon (the exact accepted
            type is finalised by task 2.8).
        buffer_m: Buffer distance in metres. The CRS conversion is
            handled internally; the caller doesn't need to project.
        columns: Optional per-table override of which column pair to
            interpret as ``(x, y)``. Defaults match :func:`from_bbox`.

    Raises:
        NotImplementedError: Always — landing in task 2.8 (issue #67).
    """
    raise NotImplementedError(
        "datagrove.dataset.view.from_geometry_buffer is a Phase 2 task 2.8 stub. "
        "Track progress at https://github.com/e-lo/GMNSpy/issues/67."
    )
