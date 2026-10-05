"""Visualization helpers for a :class:`GMNSGraph` (optional 'viz' extra).

Links are rendered from a WKT ``geometry`` column when present, otherwise as
straight segments between node coordinates. ``plot`` uses lonboard (deck.gl) when
available — which scales to large networks — and falls back to ``GeoDataFrame.explore``
(folium) for small debugging cases.
"""

from __future__ import annotations

import numpy as np


def to_geodataframe(graph, highlight=None):
    """Build a links GeoDataFrame, optionally flagging a highlighted set of link_ids.

    Args:
        graph: a :class:`GMNSGraph`.
        highlight: a ``ShortestPathResult`` or an iterable of link_ids to mark in a
            boolean ``highlight`` column (e.g. a shortest path or isochrone links).
    """
    import geopandas as gpd
    from shapely.geometry import LineString

    src = graph._source
    if src is None or not src.has_table("link"):
        raise ValueError("No source link table available to build geometry.")

    link = src.table("link", ["link_id", "from_node_id", "to_node_id", "geometry"]).to_pandas()

    if "geometry" in link.columns and link["geometry"].notna().any():
        geom = gpd.GeoSeries.from_wkt(link["geometry"].astype("string"))
    else:
        fidx = graph.node_index.get_indexer(link["from_node_id"].to_numpy())
        tidx = graph.node_index.get_indexer(link["to_node_id"].to_numpy())
        coords = graph.coords
        lines = []
        for fi, ti in zip(fidx, tidx, strict=False):
            if fi >= 0 and ti >= 0 and np.isfinite(coords[fi]).all() and np.isfinite(coords[ti]).all():
                lines.append(LineString([coords[fi], coords[ti]]))
            else:
                lines.append(None)
        geom = gpd.GeoSeries(lines)

    gdf = gpd.GeoDataFrame(link, geometry=geom, crs="EPSG:4326")

    if highlight is not None:
        ids = list(getattr(highlight, "links", highlight))
        gdf["highlight"] = gdf["link_id"].isin(ids)
    return gdf


def plot(graph, highlight=None):
    """Return an interactive map of the network (lonboard if available, else folium)."""
    gdf = to_geodataframe(graph, highlight=highlight)
    try:
        import lonboard

        return lonboard.viz(gdf)
    except ImportError:
        return gdf.explore()
