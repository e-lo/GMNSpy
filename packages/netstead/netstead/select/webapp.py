"""Local web app: type an utterance, see the selection on the network.

MapLibre GL renders the whole network (GPU, clickable to inspect links) over
basemap tiles; the resolved selection is highlighted with its gore/merge anchor
nodes marked. Backend is a thin FastAPI app over the resolver — the network is
loaded once and served as GeoJSON (localhost; render, not transfer, is the cost
MapLibre removes). Requires the ``[server]`` + ``[nl]`` extras.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from ._geojson import links_to_geojson, node_lonlat
from .emit import to_fragment
from .errors import IntentError
from .parse import ClaudeParser, StubParser
from .resolve import resolve_frames
from .result import SelectionResult

__all__ = ["build_app"]


def _page() -> str:
    return resources.files(__package__).joinpath("templates/index.html").read_text()


def _anchor_payload(nodes, result: SelectionResult) -> list[dict]:
    out = []
    for role, match in (("from", result.from_match), ("to", result.to_match)):
        if match and match.node_id is not None:
            lon, lat = node_lonlat(nodes, match.node_id)
            out.append(
                {
                    "role": role,
                    "node_id": _py(match.node_id),
                    "lon": lon,
                    "lat": lat,
                    "kind": match.kind,
                    "detail": match.detail,
                }
            )
    return out


def _py(value: Any) -> Any:
    """Coerce numpy scalar ids to plain Python for JSON."""
    return getattr(value, "item", lambda: value)()


def build_app(links, nodes, *, provider: str = "stub", parser=None) -> FastAPI:
    """Return a FastAPI app serving the selection map over ``links``/``nodes``."""
    app = FastAPI(title="netstead select")
    _parser = parser or (ClaudeParser() if provider == "claude" else StubParser())

    @lru_cache(maxsize=1)
    def _network_fc() -> dict:
        return links_to_geojson(links, nodes=nodes)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _page()

    @app.get("/api/network.geojson")
    def network() -> JSONResponse:
        return JSONResponse(_network_fc())

    @app.get("/api/select")
    def select(utterance: str = Query(..., min_length=1)) -> dict:
        try:
            intent = _parser.parse(utterance)
        except IntentError as exc:
            return {
                "status": "not_found",
                "utterance": utterance,
                "fragment": None,
                "selected": {"type": "FeatureCollection", "features": []},
                "anchors": [],
                "diagnostics": [f"could not parse: {exc}"],
            }
        result = resolve_frames(intent, links, nodes)
        payload: dict[str, Any] = {
            "status": result.status,
            "utterance": utterance,
            "anchors": _anchor_payload(nodes, result),
            "diagnostics": list(result.diagnostics),
            "candidates": {
                "from": [_py(c) for c in (result.from_match.candidates if result.from_match else [])],
                "to": [_py(c) for c in (result.to_match.candidates if result.to_match else [])],
            },
        }
        if result.link_ids:
            payload["selected"] = links_to_geojson(links, link_ids=result.link_ids, nodes=nodes)
            payload["fragment"] = (
                to_fragment(result)
                if result.status == "resolved"
                else {"links": {"link_id": [_py(i) for i in result.link_ids]}, "_status": result.status}
            )
        else:
            payload["selected"] = {"type": "FeatureCollection", "features": []}
            payload["fragment"] = None
        return payload

    return app
