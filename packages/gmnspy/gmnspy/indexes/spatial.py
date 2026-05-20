"""STRtree-based spatial index over the GMNS link geometry column.

The index is built by materializing the link table to pyarrow, decoding
each row's ``geometry`` WKT into a shapely geometry, and feeding the
result into :class:`shapely.STRtree`. Queries hit the in-memory tree.

``distance_m`` arguments are in the **geometry column's CRS units** —
Leavenworth ships as WGS84 (degrees) so the buffer is a loose
approximation. Reprojection is the network-aware scope layer's job
(task 3.10); :mod:`gmnspy.indexes` ships the primitive only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shapely import STRtree, from_wkt
from shapely.geometry import Point

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.dataset import Table
    from shapely.geometry.base import BaseGeometry

__all__ = ["SpatialIndex"]


class SpatialIndex:
    """STRtree over the link geometry column, with WKT decode + bbox extract.

    Built lazily via :meth:`build`; cached to sidecar parquet keyed on
    the content hash of the source link table (see
    :func:`gmnspy.indexes.cache.cache_path`). Self-contained once built
    — no reference to the source :class:`~datagrove.dataset.Table`.

    Examples:
        >>> import pytest
        >>> _ = pytest.importorskip("shapely")
        >>> from gmnspy.indexes import SpatialIndex
        >>> SpatialIndex.__name__
        'SpatialIndex'
    """

    __slots__ = ("geometries", "link_ids", "tree")

    def __init__(self, link_ids: list[int], geometries: list[Any]) -> None:
        """Hold parallel link-id + geometry arrays and build an STRtree over them."""
        self.link_ids: list[int] = list(link_ids)
        self.geometries: list[Any] = list(geometries)
        self.tree = STRtree(self.geometries) if self.geometries else None

    def __len__(self) -> int:
        """Number of indexed geometries."""
        return len(self.link_ids)

    @classmethod
    def build(cls, links_table: Table) -> SpatialIndex:
        """Build a :class:`SpatialIndex` over a link table.

        The link table must carry ``link_id`` + ``geometry`` (WKT)
        columns. Caller is responsible for joining the GMNS ``geometry``
        table onto ``link`` first. Rows whose geometry is null or
        unparseable are silently dropped — run datagrove validation
        first for hard errors.
        """
        arrow = _to_arrow(links_table)
        link_id_col = arrow.column("link_id").to_pylist()
        geom_col = arrow.column("geometry").to_pylist()
        link_ids: list[int] = []
        geoms: list[Any] = []
        for lid, wkt in zip(link_id_col, geom_col, strict=True):
            if wkt is None:
                continue
            try:
                g = from_wkt(wkt)
            except Exception:  # pragma: no cover - shapely raises broadly
                continue
            if g is None or g.is_empty:
                continue
            link_ids.append(int(lid))
            geoms.append(g)
        return cls(link_ids, geoms)

    def query_bbox(self, minx: float, miny: float, maxx: float, maxy: float) -> list[int]:
        """Return link_ids whose geometries intersect the (minx, miny, maxx, maxy) bbox."""
        if self.tree is None:
            return []
        from shapely.geometry import box

        return self._query(box(minx, miny, maxx, maxy), distance_m=0.0)

    def query_point(self, x: float, y: float, *, distance_m: float = 0.0) -> list[int]:
        """Return link_ids within ``distance_m`` of ``(x, y)`` in the geometry CRS."""
        if self.tree is None:
            return []
        return self._query(Point(x, y), distance_m=distance_m)

    def query_geometry(self, geom: BaseGeometry, *, distance_m: float = 0.0) -> list[int]:
        """Return link_ids whose geometries intersect ``geom`` (optionally buffered)."""
        if self.tree is None:
            return []
        return self._query(geom, distance_m=distance_m)

    def _query(self, geom: BaseGeometry, *, distance_m: float) -> list[int]:
        probe = geom.buffer(distance_m) if distance_m > 0 else geom
        assert self.tree is not None
        positions = self.tree.query(probe, predicate="intersects")
        return [self.link_ids[int(i)] for i in positions]

    def __getstate__(self) -> dict[str, Any]:
        """Serialize geometries as WKB (portable across shapely minor versions)."""
        from shapely import to_wkb

        return {"link_ids": self.link_ids, "wkb": [to_wkb(g) for g in self.geometries]}

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Reconstruct from the WKB payload emitted by :meth:`__getstate__`."""
        from shapely import from_wkb

        self.link_ids = list(state["link_ids"])
        self.geometries = [from_wkb(b) for b in state["wkb"]]
        self.tree = STRtree(self.geometries) if self.geometries else None


def _to_arrow(table: Table) -> Any:
    """Materialize a :class:`~datagrove.dataset.Table` to pyarrow.

    Two-hop ``to_pandas`` → ``pa.Table.from_pandas`` is acceptable
    because building an index is the one-off expensive step; the hot
    path is the in-memory tree query.
    """
    import pyarrow as pa

    return pa.Table.from_pandas(table.to_pandas(), preserve_index=False)
