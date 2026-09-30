"""Parquet link/node frames -> packed binary typed-arrays for deck.gl.

No GeoJSON. Link geometry (WKT) is parsed **once here** into a flat coordinate
buffer in deck.gl `PathLayer` binary layout; a link with no parseable geometry
falls back to a straight from->to segment. The browser feeds these typed arrays
straight to the GPU.

Wire format (`pack_network`): ``[uint32 headerLen][header JSON][payload]`` where
the header gives per-array byte lengths and the payload concatenates, in order:
``linkPositions f32 (flat lon,lat)``, ``linkStartIndices u32 (nLinks+1)``,
``linkIds f64``, ``nodePositions f32``, ``nodeIds f64``.
"""
from __future__ import annotations

import json
import struct

import numpy as np
import pandas as pd

from gmnspy.select._geojson import _coords_for_link

__all__ = ["pack_network", "unpack_network", "network_attrs"]

#: Fallback lane count by facility_type when `lanes` is untagged, so freeways
#: still render thick. Ramps/links stay thin.
_LANES_DEFAULT = {"motorway": 4, "trunk": 3, "primary": 3, "secondary": 2, "tertiary": 2}


def _effective_lanes(links) -> np.ndarray:
    """Per-link lane count for width styling: `lanes` if tagged (>0), else a
    facility_type default (ramps=1). Clamped to 1..255 as uint8."""
    lanes = pd.to_numeric(links.get("lanes"), errors="coerce") if "lanes" in links.columns \
        else pd.Series([np.nan] * len(links))
    ft = links["facility_type"].astype(str) if "facility_type" in links.columns \
        else pd.Series([""] * len(links))
    default = ft.map(lambda f: 1 if f.endswith("_link") else _LANES_DEFAULT.get(f, 1))
    eff = lanes.fillna(0).astype(int)
    eff = eff.where(eff > 0, default)
    return eff.clip(1, 255).to_numpy(dtype="<u1")


def _node_coords(nodes):
    return (dict(zip(nodes["node_id"], nodes["x_coord"])),
            dict(zip(nodes["node_id"], nodes["y_coord"])))


def _link_paths(links, nx: dict, ny: dict):
    """Flat positions + startIndices + ids for every link (PathLayer binary)."""
    positions: list[float] = []
    start_indices: list[int] = [0]
    ids: list[float] = []
    for _, row in links.iterrows():
        coords = _coords_for_link(row, nx, ny)  # WKT parse, else straight fallback
        for x, y in coords:
            positions.append(float(x))
            positions.append(float(y))
        start_indices.append(len(positions) // 2)
        ids.append(float(row["link_id"]))
    return (np.asarray(positions, dtype="<f4"),
            np.asarray(start_indices, dtype="<u4"),
            np.asarray(ids, dtype="<f8"))


def _node_points(nodes):
    pos = np.empty(len(nodes) * 2, dtype="<f4")
    pos[0::2] = nodes["x_coord"].to_numpy(dtype="f4")
    pos[1::2] = nodes["y_coord"].to_numpy(dtype="f4")
    ids = nodes["node_id"].to_numpy(dtype="f8")
    return pos, ids


def pack_network(links, nodes) -> bytes:
    """Pack link paths + node points into the binary wire format."""
    nx, ny = _node_coords(nodes)
    lpos, lstart, lids = _link_paths(links, nx, ny)
    llanes = _effective_lanes(links)
    npos, nids = _node_points(nodes)

    header = {
        "links": {"count": int(len(links)),
                  "positionsBytes": int(lpos.nbytes),
                  "startIndicesBytes": int(lstart.nbytes),
                  "idsBytes": int(lids.nbytes),
                  "lanesBytes": int(llanes.nbytes)},
        "nodes": {"count": int(len(nodes)),
                  "positionsBytes": int(npos.nbytes),
                  "idsBytes": int(nids.nbytes)},
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload = b"".join([lpos.tobytes(), lstart.tobytes(), lids.tobytes(), llanes.tobytes(),
                        npos.tobytes(), nids.tobytes()])
    return struct.pack("<I", len(header_bytes)) + header_bytes + payload


def unpack_network(blob: bytes) -> dict:
    """Inverse of :func:`pack_network` (for tests / debugging)."""
    (header_len,) = struct.unpack_from("<I", blob, 0)
    start = 4 + header_len
    header = json.loads(blob[4:start].decode("utf-8"))
    off = start
    lk, nd = header["links"], header["nodes"]

    def take(n_bytes, dtype):
        nonlocal off
        arr = np.frombuffer(blob, dtype=dtype, count=n_bytes // np.dtype(dtype).itemsize, offset=off)
        off += n_bytes
        return arr

    lpos = take(lk["positionsBytes"], "<f4")
    lstart = take(lk["startIndicesBytes"], "<u4")
    lids = take(lk["idsBytes"], "<f8")
    llanes = take(lk["lanesBytes"], "<u1")
    npos = take(nd["positionsBytes"], "<f4")
    nids = take(nd["idsBytes"], "<f8")
    return {
        "links": {"count": lk["count"], "positions": lpos.tolist(),
                  "startIndices": lstart.tolist(), "ids": [int(i) for i in lids.tolist()],
                  "lanes": [int(x) for x in llanes.tolist()]},
        "nodes": {"count": nd["count"], "positions": npos.tolist(),
                  "ids": [int(i) for i in nids.tolist()]},
    }


def _col(links, name):
    if name not in links.columns:
        return [None] * len(links)
    return [None if pd_isna(v) else (v.item() if hasattr(v, "item") else v)
            for v in links[name]]


def pd_isna(v) -> bool:
    try:
        import pandas as pd
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return v is None


def network_attrs(links) -> dict:
    """Index-aligned attribute arrays for the hover tooltip (not per-feature objects)."""
    return {
        "link_id": [int(i) if hasattr(i, "item") else i for i in links["link_id"]],
        "name": _col(links, "name"),
        "ref": _col(links, "ref"),
        "facility_type": _col(links, "facility_type"),
    }
