"""Per-network data routes: ``/api/n/{net_id}/{component}/...``.

The ``component`` segment is ``roadway`` today; ``transit`` answers 501 until the
GTFS component lands (P6). Heavy payloads are cached on the handle per version.
"""

from __future__ import annotations

import json as _json
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from gmnspy.viz.buffers import network_attrs, pack_network
from gmnspy.viz.styling import json_scalar, property_payload, styleable_columns
from gmnspy.viz.tables import (
    FilterError,
    columns_of,
    page_table,
    parse_ids,
    primary_key,
    table_list_entry,
    table_schema,
)

from ..registry import NetworkHandle
from ..session import Session

__all__ = ["network_router"]


def _coerce_key(raw: str) -> Any:
    try:
        return int(raw)
    except ValueError:
        return raw


def network_router(session: Session) -> APIRouter:
    """Build the ``/api/n/{net_id}/{component}`` router bound to ``session``."""
    router = APIRouter(prefix="/api/n/{net_id}/{component}")

    def handle(net_id: str, component: str) -> NetworkHandle:
        if component == "transit":
            raise HTTPException(501, "the transit component is not supported yet (phase P6)")
        if component != "roadway":
            raise HTTPException(404, f"unknown component {component!r}")
        try:
            return session.registry.get(net_id)
        except KeyError as exc:
            raise HTTPException(404, exc.args[0]) from exc

    def table(h: NetworkHandle, name: str) -> Any:
        tables = h.tables()
        if name not in tables:
            raise HTTPException(404, f"unknown table {name!r}")
        return tables[name]

    @router.get("/network.bin")
    def network_bin(net_id: str, component: str) -> Response:
        h = handle(net_id, component)
        data = h.cached("network.bin", lambda: pack_network(h.links_df(), h.nodes_df()))
        return Response(data, media_type="application/octet-stream")

    @router.get("/network.attrs.json")
    def network_attrs_json(net_id: str, component: str) -> dict[str, Any]:
        h = handle(net_id, component)
        return h.cached("network.attrs", lambda: network_attrs(h.links_df()))

    @router.get("/properties")
    def properties(net_id: str, component: str) -> dict[str, Any]:
        return {"properties": styleable_columns(handle(net_id, component).links_df())}

    @router.get("/property/{name}")
    def property_values(net_id: str, component: str, name: str) -> dict[str, Any]:
        payload = property_payload(handle(net_id, component).links_df(), name)
        if payload is None:
            raise HTTPException(404, f"unknown property {name!r}")
        return payload

    @router.get("/feature/{table_name}/{pk_value}")
    def feature(net_id: str, component: str, table_name: str, pk_value: str) -> dict[str, Any]:
        src = table(handle(net_id, component), table_name)
        pk = primary_key(table_name, columns_of(src))
        if pk is None:
            raise HTTPException(404, f"table {table_name!r} has no primary key")
        key = _coerce_key(pk_value)
        page = page_table(src, limit=1, ids=[key], pk=pk)
        if not page["rows"]:
            raise HTTPException(404, f"{table_name} {pk_value} not found")
        return {
            "table": table_name,
            "pk": pk,
            "id": json_scalar(key),
            "attributes": dict(zip(page["columns"], page["rows"][0], strict=True)),
        }

    @router.get("/tables")
    def tables_list(net_id: str, component: str) -> dict[str, Any]:
        return {"tables": [table_list_entry(n, src) for n, src in handle(net_id, component).tables().items()]}

    @router.get("/table/{table_name}/schema")
    def table_schema_ep(net_id: str, component: str, table_name: str) -> dict[str, Any]:
        return table_schema(table_name, table(handle(net_id, component), table_name))

    @router.get("/table/{table_name}/rows")
    def table_rows(
        net_id: str,
        component: str,
        table_name: str,
        offset: int = 0,
        limit: int = 100,
        sort: str | None = None,
        dir: str = "asc",
        filter: str | None = None,
        ids: str | None = None,
    ) -> dict[str, Any]:
        src = table(handle(net_id, component), table_name)
        try:
            spec = _json.loads(filter) if filter else None
        except _json.JSONDecodeError as exc:
            raise HTTPException(400, f"bad filter json: {exc}") from exc
        try:
            payload = page_table(
                src,
                offset=offset,
                limit=limit,
                sort=sort,
                direction=dir,
                filter_spec=spec,
                ids=parse_ids(ids),
                pk=primary_key(table_name, columns_of(src)),
            )
        except FilterError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"name": table_name, **payload}

    return router
