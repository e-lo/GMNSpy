"""Link-geometry assembly — resolve ``link.geometry`` / ``link.geometry_id`` / node endpoints.

GMNS allows three ways to carry a link's geometry, in priority order:

1. Inline ``link.geometry`` (WKT) — wins when present + non-empty.
2. ``link.geometry_id`` resolving to a row in the ``geometry`` table.
3. Fall back to a straight :code:`LINESTRING(x1 y1, x2 y2)` synthesised
   from the link's ``from_node_id`` / ``to_node_id`` node coordinates.

:func:`assemble_link_geometry` walks all three in order and stamps each
output row with a ``source`` column so callers can audit how the
geometry was produced.

This module materialises through pyarrow (via the underlying
:class:`~datagrove.dataset.Table`'s engine) rather than expressing the
resolution chain in ibis. Reason: the geometry table is typically tiny
relative to links, the join is one-shot, and the pyarrow code reads
top-to-bottom in 60 lines instead of a 4-arm ibis ``case`` builder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gmnspy.network import Network

__all__ = ["GeometrySource", "assemble_link_geometry"]


class GeometrySource:
    """Enum-ish constants for the ``source`` column produced by :func:`assemble_link_geometry`."""

    INLINE = "inline"
    GEOMETRY_TABLE = "geometry_table"
    NODE_ENDPOINTS = "node_endpoints"
    MISSING = "missing"


def assemble_link_geometry(net: Network) -> pa.Table:
    """Return ``(link_id, geometry_wkt, source)`` for every link in ``net``.

    Resolution order per link row:

    1. Inline ``link.geometry`` (non-null, non-empty WKT) — ``source = "inline"``.
    2. ``link.geometry_id`` resolving in ``net.geometry`` — ``source = "geometry_table"``.
    3. Straight ``LINESTRING(x1 y1, x2 y2)`` from ``from_node_id`` /
       ``to_node_id`` looked up in ``net.nodes`` — ``source = "node_endpoints"``.
    4. None of the above (geometry column absent + geometry_id absent +
       endpoint nodes missing coords) — ``geometry_wkt = None``,
       ``source = "missing"``.

    Args:
        net: A loaded :class:`gmnspy.Network`.

    Returns:
        A :class:`pyarrow.Table` with columns ``link_id`` (matching
        the link table's id type), ``geometry_wkt`` (string or null),
        and ``source`` (string from :class:`GeometrySource`).

    Examples:
        >>> from gmnspy import Network
        >>> from gmnspy.fixtures import leavenworth
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from gmnspy.semantics import assemble_link_geometry
        >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
        >>> tbl = assemble_link_geometry(net)
        >>> set(tbl.column_names) == {"link_id", "geometry_wkt", "source"}
        True
        >>> # Leavenworth carries geometry via geometry_id, so all rows
        >>> # should resolve through the geometry table.
        >>> set(tbl.column("source").to_pylist()) <= {"inline", "geometry_table", "node_endpoints", "missing"}
        True
    """
    links_arrow = _to_arrow(net.links)
    geom_lookup = _build_geometry_lookup(net)
    node_lookup = _build_node_xy_lookup(net)

    link_ids: list = []
    geom_wkts: list[str | None] = []
    sources: list[str] = []

    has_inline_geom = "geometry" in links_arrow.column_names
    has_geom_id = "geometry_id" in links_arrow.column_names

    inline_col = links_arrow.column("geometry").to_pylist() if has_inline_geom else None
    geom_id_col = links_arrow.column("geometry_id").to_pylist() if has_geom_id else None
    from_col = links_arrow.column("from_node_id").to_pylist()
    to_col = links_arrow.column("to_node_id").to_pylist()
    id_col = links_arrow.column("link_id").to_pylist()

    for i, link_id in enumerate(id_col):
        link_ids.append(link_id)

        # 1. Inline geometry wins.
        if inline_col is not None:
            wkt = inline_col[i]
            if wkt is not None and str(wkt).strip():
                geom_wkts.append(str(wkt))
                sources.append(GeometrySource.INLINE)
                continue

        # 2. geometry_id lookup.
        if geom_id_col is not None:
            gid = geom_id_col[i]
            if gid is not None and gid in geom_lookup:
                geom_wkts.append(geom_lookup[gid])
                sources.append(GeometrySource.GEOMETRY_TABLE)
                continue

        # 3. Synthesize from node endpoints.
        from_id, to_id = from_col[i], to_col[i]
        if from_id in node_lookup and to_id in node_lookup:
            x1, y1 = node_lookup[from_id]
            x2, y2 = node_lookup[to_id]
            if None not in (x1, y1, x2, y2):
                geom_wkts.append(f"LINESTRING ({x1} {y1}, {x2} {y2})")
                sources.append(GeometrySource.NODE_ENDPOINTS)
                continue

        # 4. Truly unresolvable — emit a null + flag for the audit.
        geom_wkts.append(None)
        sources.append(GeometrySource.MISSING)

    return pa.table(
        {
            "link_id": pa.array(link_ids, type=links_arrow.column("link_id").type),
            "geometry_wkt": pa.array(geom_wkts, type=pa.string()),
            "source": pa.array(sources, type=pa.string()),
        }
    )


def _build_geometry_lookup(net: Network) -> dict:
    """Build ``{geometry_id: wkt}`` from ``net.geometry`` or return ``{}``."""
    geom_table = net.geometry
    if geom_table is None:
        return {}
    arrow = _to_arrow(geom_table)
    ids = arrow.column("geometry_id").to_pylist()
    wkts = arrow.column("geometry").to_pylist()
    # Drop rows with missing keys; downstream code already handles missing lookups.
    return {gid: wkt for gid, wkt in zip(ids, wkts, strict=True) if gid is not None and wkt is not None}


def _build_node_xy_lookup(net: Network) -> dict:
    """Build ``{node_id: (x_coord, y_coord)}`` from ``net.nodes``."""
    arrow = _to_arrow(net.nodes)
    ids = arrow.column("node_id").to_pylist()
    xs = arrow.column("x_coord").to_pylist() if "x_coord" in arrow.column_names else [None] * len(ids)
    ys = arrow.column("y_coord").to_pylist() if "y_coord" in arrow.column_names else [None] * len(ids)
    return {nid: (x, y) for nid, x, y in zip(ids, xs, ys, strict=True) if nid is not None}


def _to_arrow(table) -> pa.Table:
    """Materialise a :class:`~datagrove.dataset.Table` to pyarrow.

    Two-hop ``to_pandas`` → ``pa.Table.from_pandas`` matches the rest
    of the gmnspy.indexes / semantics layer so we don't introduce a
    second materialisation contract.
    """
    return pa.Table.from_pandas(table.to_pandas(), preserve_index=False)
