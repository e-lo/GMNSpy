"""Issue → ``(lon, lat)`` resolver for the network-on-map HTML viewer.

A :class:`GeoResolver` precomputes a links DataFrame and a node-id
coordinate lookup once per render, then resolves each
:class:`~datagrove.reports.Issue` to its best-guess geographic location.
Findings without a resolvable location are returned as ``None`` and end
up in the viewer's "Unlocated findings" sidebar.

Resolution priority (first match wins):

1. ``issue.extra["lon"]/["lat"]`` (or ``["x"]/["y"]``).
2. ``issue.table == "link"`` + ``issue.row`` → midpoint of the link's
   WKT geometry (parsed inline; no shapely dep) or, when the link
   table has no ``geometry`` column, the midpoint of its from/to
   node coords.
3. ``issue.table == "node"`` + ``issue.row`` → that node's
   ``(x_coord, y_coord)``.
4. FK issues (``category=foreign_key``) follow the source-table row
   through priority 2/3 — i.e. an FK violation on a link row resolves
   to the link's midpoint, exactly like a schema violation on that
   same row.
5. Otherwise → ``None`` (unlocated).
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd
    from datagrove.reports import Issue

    from gmnspy.network import Network

__all__ = ["GeoResolver"]


_WKT_POINT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")


def _parse_linestring_points(wkt: str) -> list[tuple[float, float]]:
    """Parse a ``LINESTRING (x y, x y, ...)`` WKT to a list of ``(lon, lat)``.

    Handhewn — the format is tiny and shapely is a heavy C-extension dep
    to drag in just for a midpoint. Accepts a leading ``LINESTRING`` /
    ``LINESTRING M`` / ``LINESTRING Z`` token (case-insensitive) and any
    surrounding whitespace. Returns an empty list when no coords parse.
    """
    if not isinstance(wkt, str):
        return []
    return [(float(x), float(y)) for x, y in _WKT_POINT_RE.findall(wkt)]


def _polyline_midpoint(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Return the half-length point along ``points`` (planar, fine for short links).

    For a network display, planar-Euclidean midpoint is visually
    indistinguishable from a geodesic one over typical GMNS link
    lengths (a few hundred metres). When the polyline is degenerate
    (zero length or fewer than 2 points), returns the first vertex
    if present, else ``None``.
    """
    if not points:
        return None
    if len(points) == 1:
        return points[0]
    # Segment lengths and cumulative distances along the polyline.
    cumulative = [0.0]
    total = 0.0
    for (x1, y1), (x2, y2) in pairwise(points):
        seg = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        total += seg
        cumulative.append(total)
    if total == 0.0:
        return points[0]
    half = total / 2
    # Find the segment containing the half-length mark and interpolate.
    for i in range(1, len(cumulative)):
        if cumulative[i] >= half:
            seg_start = cumulative[i - 1]
            seg_len = cumulative[i] - seg_start
            t = 0.0 if seg_len == 0 else (half - seg_start) / seg_len
            (x1, y1), (x2, y2) = points[i - 1], points[i]
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return points[-1]  # pragma: no cover — defensive, shouldn't be reachable


class GeoResolver:
    """Cached resolver: turn issues into ``(lon, lat)`` against ``network``.

    Materialises the links and nodes tables once at construction time
    and reuses them for every :meth:`resolve` call.

    Attributes:
        network: The network the resolver is bound to.
    """

    def __init__(self, network: Network) -> None:
        """Materialise ``network``'s ``link`` / ``node`` / ``geometry`` tables and pre-compute lookups."""
        self.network = network
        self._links_df: pd.DataFrame | None = self._materialise("link")
        self._nodes_df: pd.DataFrame | None = self._materialise("node")
        self._node_coord_by_id: dict[object, tuple[float, float]] = {}
        if self._nodes_df is not None and {"node_id", "x_coord", "y_coord"} <= set(self._nodes_df.columns):
            for node_id, x, y in zip(
                self._nodes_df["node_id"],
                self._nodes_df["x_coord"],
                self._nodes_df["y_coord"],
                strict=False,
            ):
                self._node_coord_by_id[node_id] = (float(x), float(y))
        # GMNS allows link geometry to live either inline on ``link.geometry``
        # (OSM importer shape) or out-of-band in a separate ``geometry``
        # resource referenced by ``link.geometry_id`` (Leavenworth shape).
        # Build the FK lookup once.
        self._wkt_by_geometry_id: dict[object, str] = {}
        geom_df = self._materialise("geometry")
        if geom_df is not None and {"geometry_id", "geometry"} <= set(geom_df.columns):
            for gid, wkt in zip(geom_df["geometry_id"], geom_df["geometry"], strict=False):
                if isinstance(wkt, str):
                    self._wkt_by_geometry_id[gid] = wkt

    def _materialise(self, table_name: str) -> pd.DataFrame | None:
        table = self.network.tables.get(table_name)
        if table is None:
            return None
        return table.to_pandas()

    # -- Public surface ----------------------------------------------------

    def resolve(self, issue: Issue) -> tuple[float, float] | None:
        """Return ``(lon, lat)`` for ``issue``, or ``None`` when unlocated."""
        # 1. Explicit coords on the issue extra.
        if (coords := _explicit_coords(issue)) is not None:
            return coords

        # 2/3/4. Row-based lookups; both link and node are tried because FK
        # issues on a link row should still resolve via the link midpoint.
        if issue.row is None or issue.table is None:
            return None
        if issue.table == "link":
            return self._resolve_link_row(issue.row)
        if issue.table == "node":
            return self._resolve_node_row(issue.row)
        return None

    # -- Internals ---------------------------------------------------------

    def _resolve_link_row(self, row: int) -> tuple[float, float] | None:
        df = self._links_df
        if df is None or row < 0 or row >= len(df):
            return None
        record = df.iloc[row]
        # Geometry midpoint when the column exists and parses (OSM-import shape).
        wkt = self._link_wkt(record, set(df.columns))
        if wkt:
            mid = _polyline_midpoint(_parse_linestring_points(wkt))
            if mid is not None:
                return mid
        # Fall back to from/to node coord midpoint.
        from_coord = self._node_coord_by_id.get(record.get("from_node_id"))
        to_coord = self._node_coord_by_id.get(record.get("to_node_id"))
        if from_coord is not None and to_coord is not None:
            return ((from_coord[0] + to_coord[0]) / 2, (from_coord[1] + to_coord[1]) / 2)
        return from_coord or to_coord

    def _link_wkt(self, link_record, link_columns: set[str]) -> str | None:
        """Return the link's WKT — inline ``geometry`` column or via ``geometry_id`` FK.

        ``link_record`` must support ``.get(name)``. Both ``pandas.Series``
        and plain ``dict`` do, which lets the same helper serve both the
        per-row resolver path and the bulk-underlay path.
        """
        if "geometry" in link_columns:
            wkt = link_record.get("geometry")
            if isinstance(wkt, str) and wkt:
                return wkt
        if "geometry_id" in link_columns and self._wkt_by_geometry_id:
            gid = link_record.get("geometry_id")
            if gid is not None:
                return self._wkt_by_geometry_id.get(gid)
        return None

    def link_polylines(self, *, limit: int) -> list[list[list[float]]]:
        """Return up to ``limit`` link polylines as ``[[[lon, lat], ...], ...]`` for the underlay.

        Uses the same WKT resolution as :meth:`resolve` — inline
        ``geometry`` first, then ``geometry_id`` → ``geometry`` table —
        and falls back to a straight from/to-node segment when neither
        is available. Shared with the renderer so the underlay and
        per-issue resolution can't drift.
        """
        df = self._links_df
        if df is None or df.empty:
            return []
        cols = set(df.columns)
        out: list[list[list[float]]] = []
        for _, record in df.head(limit).iterrows():
            wkt = self._link_wkt(record, cols)
            if wkt:
                pts = _parse_linestring_points(wkt)
                if len(pts) >= 2:
                    out.append([[lon, lat] for lon, lat in pts])
                    continue
            a = self._node_coord_by_id.get(record.get("from_node_id"))
            b = self._node_coord_by_id.get(record.get("to_node_id"))
            if a and b:
                out.append([[a[0], a[1]], [b[0], b[1]]])
        return out

    def _resolve_node_row(self, row: int) -> tuple[float, float] | None:
        df = self._nodes_df
        if df is None or row < 0 or row >= len(df):
            return None
        record = df.iloc[row]
        try:
            return (float(record["x_coord"]), float(record["y_coord"]))
        except (KeyError, TypeError, ValueError):
            return None


def _explicit_coords(issue: Issue) -> tuple[float, float] | None:
    """Read ``lon``/``lat`` or ``x``/``y`` off ``issue.extra``."""
    extra = issue.extra or {}
    lon = extra.get("lon", extra.get("x"))
    lat = extra.get("lat", extra.get("y"))
    if lon is None or lat is None:
        return None
    try:
        return (float(lon), float(lat))
    except (TypeError, ValueError):
        return None
