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

from fastapi import FastAPI, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse

from gmnspy.select.parse import ClaudeParser, StubParser
from gmnspy.select.resolve import resolve_frames
from gmnspy.select.emit import to_fragment

from .buffers import network_attrs, pack_network

__all__ = ["build_app"]


def _page() -> str:
    return resources.files(__package__).joinpath("templates/index.html").read_text()


def _py(v: Any) -> Any:
    return getattr(v, "item", lambda: v)()


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
