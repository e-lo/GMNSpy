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


def build_app(links, nodes, *, provider: str = "stub", parser=None) -> FastAPI:
    """Return the viewer FastAPI app over ``links``/``nodes`` frames."""
    app = FastAPI(title="gmnspy viz")
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
