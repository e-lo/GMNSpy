"""FastAPI backend for the gmnspy.viz network viewer.

Serves the network as **binary typed-arrays** (`/api/network.bin`), a compact
index-aligned attribute payload for tooltips (`/api/network.attrs.json`), and
the NL selection (`/api/select`, reusing :mod:`gmnspy.select`). The frontend
(deck.gl + MapLibre) renders links + nodes from the binary and highlights a
selection by slicing the already-loaded buffer. Requires the ``[server]`` extra.
"""
from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any

import pandas as pd
from fastapi import Body, FastAPI, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse

from gmnspy.select.intent import SelectionIntent
from gmnspy.select.parse import ClaudeParser, StubParser
from gmnspy.select.resolve import resolve_frames
from gmnspy.select.emit import to_fragment

from .buffers import network_attrs, pack_network

__all__ = ["build_app"]


def _page() -> str:
    return resources.files(__package__).joinpath("templates/index.html").read_text()


def _py(v: Any) -> Any:
    return getattr(v, "item", lambda: v)()


def _json_scalar(v: Any) -> Any:
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return getattr(v, "item", lambda: v)()


#: Columns never offered as a color-by property (geometry/opaque or identity).
_SKIP_STYLE_COLS = {"geometry", "osm_node_ids", "osm_way_id", "link_id",
                    "from_node_id", "to_node_id"}
_MAX_CATEGORIES = 25


def _styleable_columns(links) -> list[dict]:
    """List columns usable for color-by, classified continuous vs categorical."""
    out = []
    for c in links.columns:
        if c in _SKIP_STYLE_COLS:
            continue
        s = links[c]
        if pd.api.types.is_numeric_dtype(s):
            out.append({"name": c, "kind": "continuous"})
        elif s.nunique(dropna=True) <= _MAX_CATEGORIES:   # skip high-cardinality (e.g. name)
            out.append({"name": c, "kind": "categorical"})
    return out


def _property_payload(links, name: str) -> dict | None:
    if name not in links.columns:
        return None
    s = links[name]
    values = [_json_scalar(v) for v in s]
    if pd.api.types.is_numeric_dtype(s):
        nn = [v for v in values if v is not None]
        return {"name": name, "kind": "continuous", "values": values,
                "min": min(nn) if nn else 0, "max": max(nn) if nn else 1}
    cats = sorted({str(v) for v in values if v is not None})
    return {"name": name, "kind": "categorical", "values": [None if v is None else str(v) for v in values],
            "categories": cats}


_ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas"
#: Free, no-key vector Positron (OpenMapTiles/OSM data). Gives the muted
#: "network pops" look without any API key or secret to manage.
_POSITRON_URL = "https://tiles.openfreemap.org/styles/positron"


def _basemap_style(basemap: str = "positron"):
    """Return a MapLibre style for ``basemap``.

    * ``"positron"`` (default) — OpenFreeMap's no-key vector Positron (a style
      URL string). No API key, crisp at all zooms.
    * ``"esri"`` — Esri World Light Gray raster, capped at z16 so MapLibre
      overzooms rather than hitting the 'map data not yet available' tiles.

    No basemap option requires or embeds a secret.
    """
    if basemap == "esri":
        return {"version": 8, "sources": {
            "basemap": {"type": "raster", "tileSize": 256, "maxzoom": 16,
                        "attribution": "Esri, © OpenStreetMap contributors",
                        "tiles": [f"{_ESRI}/World_Light_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}"]},
            "labels": {"type": "raster", "tileSize": 256, "maxzoom": 16,
                       "tiles": [f"{_ESRI}/World_Light_Gray_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}"]}},
            "layers": [{"id": "basemap", "type": "raster", "source": "basemap"},
                       {"id": "labels", "type": "raster", "source": "labels"}]}
    return _POSITRON_URL


def build_app(links, nodes, *, provider: str = "stub", parser=None, basemap: str = "positron") -> FastAPI:
    """Return the viewer FastAPI app over ``links``/``nodes`` frames.

    ``basemap`` selects the (keyless) basemap: ``"positron"`` (default) or ``"esri"``.
    """
    app = FastAPI(title="gmnspy viz")
    _style = _basemap_style(basemap)
    _parser = parser or (ClaudeParser() if provider == "claude" else StubParser())
    node_xy = {r.node_id: (float(r.x_coord), float(r.y_coord)) for r in nodes.itertuples()}

    @lru_cache(maxsize=1)
    def _bin() -> bytes:
        return pack_network(links, nodes)

    @lru_cache(maxsize=1)
    def _attrs() -> dict:
        return network_attrs(links)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _page()

    @app.get("/api/config")
    def config() -> JSONResponse:
        return JSONResponse({"style": _style})

    @app.get("/api/network.bin")
    def network_bin() -> Response:
        return Response(_bin(), media_type="application/octet-stream")

    @app.get("/api/network.attrs.json")
    def network_attrs_json() -> JSONResponse:
        return JSONResponse(_attrs())

    @app.get("/api/properties")
    def properties() -> JSONResponse:
        return JSONResponse({"properties": _styleable_columns(links)})

    @app.get("/api/property/{name}")
    def property_values(name: str) -> JSONResponse:
        payload = _property_payload(links, name)
        if payload is None:
            return JSONResponse({"error": f"unknown property {name}"}, status_code=404)
        return JSONResponse(payload)

    @app.get("/api/link/{link_id}")
    def link_detail(link_id: str) -> JSONResponse:
        """Full attribute row for one link (the detailed-inspection table)."""
        try:
            key: Any = int(link_id)
        except ValueError:
            key = link_id
        row = links[links["link_id"] == key]
        if len(row) == 0:
            return JSONResponse({"error": f"link {link_id} not found"}, status_code=404)
        rec = row.iloc[0].to_dict()
        return JSONResponse({"link_id": _py(key),
                             "attributes": {k: _json_scalar(v) for k, v in rec.items()}})

    @app.post("/api/fragment")
    def fragment(payload: dict = Body(...)) -> JSONResponse:
        """Emit a validated selection fragment from interactively-picked link ids.

        Body: ``{"link_ids": [...], "form": "resolved"|"query"}``. Reuses the
        real resolve+emit path so a map-built selection round-trips to the same
        ProjectCard-shaped fragment an utterance would produce.
        """
        ids = payload.get("link_ids") or []
        if not ids:
            return JSONResponse({"error": "link_ids must be a non-empty list"}, status_code=400)
        form = payload.get("form", "resolved")
        result = resolve_frames(SelectionIntent(link_ids=list(ids)), links, nodes)
        frag = to_fragment(result, form=form) if result.status == "resolved" else None
        return JSONResponse({"status": result.status, "count": len(result.link_ids),
                             "link_ids": [_py(i) for i in result.link_ids], "fragment": frag,
                             "diagnostics": list(result.diagnostics)})

    @app.get("/api/select")
    def select(utterance: str = Query(..., min_length=1)) -> dict:
        try:
            intent = _parser.parse(utterance)
        except Exception as exc:  # parse failures are a normal "not_found"
            return {"status": "not_found", "utterance": utterance, "link_ids": [],
                    "anchors": [], "fragment": None, "diagnostics": [f"could not parse: {exc}"]}
        result = resolve_frames(intent, links, nodes)
        anchors = []
        for role, m in (("from", result.from_match), ("to", result.to_match)):
            if m and m.node_id is not None and m.node_id in node_xy:
                lon, lat = node_xy[m.node_id]
                anchors.append({"role": role, "node_id": _py(m.node_id), "lon": lon,
                                "lat": lat, "kind": m.kind, "detail": m.detail})
        fragment = to_fragment(result) if result.status == "resolved" else None
        return {"status": result.status, "utterance": utterance,
                "link_ids": [_py(i) for i in result.link_ids], "anchors": anchors,
                "fragment": fragment, "diagnostics": list(result.diagnostics)}

    return app
