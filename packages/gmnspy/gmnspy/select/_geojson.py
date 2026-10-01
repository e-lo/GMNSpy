"""Turn GMNS link/node frames into GeoJSON for the selection map.

Uses each link's WKT ``geometry`` when present; falls back to a straight
segment between its from/to node coordinates. Reuses the hand-rolled WKT
parser from :mod:`gmnspy._wkt` (no shapely dependency).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from gmnspy._wkt import linestring_points  # WKT/WKB LINESTRING coords

__all__ = ["links_to_geojson", "node_lonlat"]


def _json_scalar(value: Any) -> Any:
    """Coerce a pandas/numpy cell to a JSON-safe primitive (NA/NaN -> None)."""
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return getattr(value, "item", lambda: value)()  # numpy scalar -> python


def node_lonlat(nodes, node_id) -> tuple[float, float]:
    """Return ``(lon, lat)`` for ``node_id`` from a nodes frame."""
    row = nodes.loc[nodes["node_id"] == node_id].iloc[0]
    return float(row["x_coord"]), float(row["y_coord"])


def _coords_for_link(row, nx: dict, ny: dict) -> list[list[float]]:
    geom = row.get("geometry")
    pts = linestring_points(geom)
    if len(pts) >= 2:
        return [[x, y] for x, y in pts]
    u, v = row["from_node_id"], row["to_node_id"]  # fallback: straight segment
    if u in nx and v in nx:
        return [[float(nx[u]), float(ny[u])], [float(nx[v]), float(ny[v])]]
    return []


def links_to_geojson(links, link_ids: Iterable | None = None, nodes=None) -> dict:
    """Build a GeoJSON FeatureCollection of LineStrings for ``links``.

    Args:
        links: links frame (needs ``link_id``, ``from_node_id``, ``to_node_id``,
            optional ``geometry`` WKT, ``facility_type``, ``name``, ``ref``).
        link_ids: optional ordered subset; preserves the given order.
        nodes: optional nodes frame enabling the straight-segment fallback
            when a link has no parseable geometry.
    """
    nx = ny = {}
    if nodes is not None:
        nx = dict(zip(nodes["node_id"], nodes["x_coord"], strict=False))
        ny = dict(zip(nodes["node_id"], nodes["y_coord"], strict=False))

    if link_ids is not None:
        by_id = {r["link_id"]: r for _, r in links.iterrows()}
        rows = [by_id[i] for i in link_ids if i in by_id]
    else:
        rows = [r for _, r in links.iterrows()]

    features = []
    for row in rows:
        coords = _coords_for_link(row, nx, ny)
        if len(coords) < 2:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "link_id": _json_scalar(row["link_id"]),
                    "facility_type": _json_scalar(row.get("facility_type")),
                    "name": _json_scalar(row.get("name")),
                    "ref": _json_scalar(row.get("ref")),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
