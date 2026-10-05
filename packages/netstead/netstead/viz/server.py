"""FastAPI backend for the netstead.viz network viewer.

Serves the network as **binary typed-arrays** (`/api/network.bin`), a compact
index-aligned attribute payload for tooltips (`/api/network.attrs.json`), and
the NL selection (`/api/select`, reusing :mod:`netstead.select`). The frontend
(deck.gl + MapLibre) renders links + nodes from the binary and highlights a
selection by slicing the already-loaded buffer. Requires the ``[server]`` extra.

Deprecated: ``netstead viz`` now launches the workbench (:mod:`netstead.workbench`);
this single-network app remains only for existing callers and is removed in P1.
"""

from __future__ import annotations

import json as _json
from functools import lru_cache
from importlib import resources
from typing import Any

from fastapi import Body, FastAPI, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse

from netstead.select.emit import to_fragment
from netstead.select.intent import SelectionIntent
from netstead.select.parse import ClaudeParser, StubParser
from netstead.select.resolve import resolve_frames

from .buffers import network_attrs, pack_network
from .styling import basemap_style as _basemap_style
from .styling import json_scalar as _json_scalar
from .styling import property_payload as _property_payload
from .styling import styleable_columns as _styleable_columns
from .tables import FilterError, columns_of, page_table, primary_key, table_list_entry, table_schema
from .tables import parse_ids as _parse_ids

__all__ = ["build_app"]


def _page() -> str:
    return resources.files(__package__).joinpath("templates/index.html").read_text()


def _py(v: Any) -> Any:
    return getattr(v, "item", lambda: v)()


def build_app(
    links, nodes, *, provider: str = "stub", parser=None, basemap: str = "positron", tables: dict | None = None
) -> FastAPI:
    """Return the viewer FastAPI app over ``links``/``nodes`` frames.

    ``basemap`` selects the (keyless) basemap: ``"positron"`` (default) or ``"esri"``.
    ``tables`` optionally maps extra GMNS table names to frames for the data-table
    view; ``link``/``node`` default to ``links``/``nodes``.
    """
    app = FastAPI(title="netstead viz")
    _style = _basemap_style(basemap)
    _parser = parser or (ClaudeParser() if provider == "claude" else StubParser())
    node_xy = {r.node_id: (float(r.x_coord), float(r.y_coord)) for r in nodes.itertuples()}
    _tables: dict[str, Any] = {"link": links, "node": nodes, **(tables or {})}

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
        return JSONResponse({"link_id": _py(key), "attributes": {k: _json_scalar(v) for k, v in rec.items()}})

    @app.get("/api/tables")
    def tables_list() -> JSONResponse:
        return JSONResponse({"tables": [table_list_entry(n, df) for n, df in _tables.items()]})

    @app.get("/api/table/{name}/schema")
    def table_schema_ep(name: str) -> JSONResponse:
        if name not in _tables:
            return JSONResponse({"error": f"unknown table {name}"}, status_code=404)
        return JSONResponse(table_schema(name, _tables[name]))

    @app.get("/api/table/{name}/rows")
    def table_rows(
        name: str,
        offset: int = 0,
        limit: int = 100,
        sort: str | None = None,
        dir: str = "asc",
        filter: str | None = None,
        ids: str | None = None,
    ) -> JSONResponse:
        if name not in _tables:
            return JSONResponse({"error": f"unknown table {name}"}, status_code=404)
        df = _tables[name]
        try:
            spec = _json.loads(filter) if filter else None
        except _json.JSONDecodeError as exc:
            return JSONResponse({"error": f"bad filter json: {exc}"}, status_code=400)
        id_list = _parse_ids(ids)
        try:
            payload = page_table(
                df,
                offset=offset,
                limit=limit,
                sort=sort,
                direction=dir,
                filter_spec=spec,
                ids=id_list,
                pk=primary_key(name, columns_of(df)),
            )
        except FilterError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"name": name, **payload})

    @app.post("/api/fragment")
    def fragment(payload: dict = Body(...)) -> JSONResponse:  # noqa: B008  (FastAPI Body default)
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
        return JSONResponse(
            {
                "status": result.status,
                "count": len(result.link_ids),
                "link_ids": [_py(i) for i in result.link_ids],
                "fragment": frag,
                "diagnostics": list(result.diagnostics),
            }
        )

    @app.get("/api/select")
    def select(utterance: str = Query(..., min_length=1)) -> dict:
        try:
            intent = _parser.parse(utterance)
        except Exception as exc:  # parse failures are a normal "not_found"
            return {
                "status": "not_found",
                "utterance": utterance,
                "link_ids": [],
                "anchors": [],
                "fragment": None,
                "diagnostics": [f"could not parse: {exc}"],
            }
        result = resolve_frames(intent, links, nodes)
        anchors = []
        for role, m in (("from", result.from_match), ("to", result.to_match)):
            if m and m.node_id is not None and m.node_id in node_xy:
                lon, lat = node_xy[m.node_id]
                anchors.append(
                    {
                        "role": role,
                        "node_id": _py(m.node_id),
                        "lon": lon,
                        "lat": lat,
                        "kind": m.kind,
                        "detail": m.detail,
                    }
                )
        fragment = to_fragment(result) if result.status == "resolved" else None
        return {
            "status": result.status,
            "utterance": utterance,
            "link_ids": [_py(i) for i in result.link_ids],
            "anchors": anchors,
            "fragment": fragment,
            "diagnostics": list(result.diagnostics),
        }

    return app
