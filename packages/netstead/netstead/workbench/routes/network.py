"""Per-network data routes: ``/api/n/{net_id}/{component}/...``.

The ``component`` segment is ``roadway`` today; ``transit`` answers 501 until the
GTFS component lands (P6). Heavy payloads are cached on the handle per version.

Table rows can be read by ``GET`` (query string) or ``POST`` (JSON body). The POST form exists
because id lists (a box-selection, the related-records sources) outgrow a URL; it also carries
the related-records ``tint``/``filter``. ``/related`` and ``/locate`` are read-only views: like
every route here, nothing is recorded in the session history.
"""

from __future__ import annotations

import json as _json
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from netstead.viz.buffers import network_attrs, pack_network
from netstead.viz.styling import json_scalar, property_payload, styleable_columns
from netstead.viz.tables import FilterError, locate_row, page_table, parse_ids, table_list_entry, table_schema

from ..registry import NetworkHandle
from ..related import (
    MAX_MAP_IDS,
    MAX_SOURCE_IDS,
    Match,
    Relation,
    RelationGraph,
    count,
    ids_of,
    relate,
    relation_graph,
    restrict,
    row_vias,
)
from ..session import Session

__all__ = ["LocateQuery", "RelatedQuery", "RowsQuery", "network_router"]

ScalarId = int | str


class RelatedQuery(BaseModel):
    """What to find related records for: highlighted ids per table, and how many keys away."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    sources: dict[str, list[ScalarId]]
    hops: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def _bounded(self) -> RelatedQuery:
        if sum(len(ids) for ids in self.sources.values()) > MAX_SOURCE_IDS:
            raise ValueError(f"too many ids (over {MAX_SOURCE_IDS:,}); narrow the highlight")
        return self


class RowsQuery(BaseModel):
    """One page of a table: the GET parameters as JSON, plus an optional related ``tint``/``filter``."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1)
    sort: str | None = None
    dir: Literal["asc", "desc"] = "asc"
    filter: list[dict[str, Any]] | None = None
    ids: list[ScalarId] | None = Field(default=None, max_length=MAX_SOURCE_IDS)
    related: RelatedQuery | None = None
    related_mode: Literal["tint", "filter"] = "tint"


class LocateQuery(RowsQuery):
    """Where the row whose primary key is ``id`` sits, in a :class:`RowsQuery`'s order."""

    id: ScalarId


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

    def graph(h: NetworkHandle) -> RelationGraph:
        return h.cached("relations", lambda: relation_graph(h.roadway.spec, h.tables()))

    def related_of(g: RelationGraph, q: RelatedQuery) -> dict[str, Relation]:
        unknown = sorted(set(q.sources) - set(g.tables))
        if unknown:
            raise HTTPException(400, f"unknown table(s) {unknown}")
        return relate(g, q.sources, hops=q.hops)

    def prepared(h: NetworkHandle, name: str, q: RowsQuery) -> tuple[Any, str | None, Relation | None]:
        """The table (narrowed when ``related_mode`` is ``filter``), its key, and its relation (for the tint)."""
        g, src = graph(h), table(h, name)
        pk = g.pks.get(name)
        if q.ids is not None and not q.ids:  # an explicit empty id list is "no rows", not "all rows"
            src = restrict(src, [])
        if q.related is None:
            return src, pk, None
        relation = related_of(g, q.related).get(name)
        if q.related_mode == "filter":
            if relation is not None:
                src = restrict(src, relation.matches)
            elif name in q.related.sources and pk:  # the source table: its own highlighted rows
                src = restrict(src, [Match(pk, tuple(q.related.sources[name]), "")])
            else:
                src = restrict(src, [])
        return src, pk, relation

    def page(src: Any, pk: str | None, q: RowsQuery) -> dict[str, Any]:
        try:
            return page_table(
                src,
                offset=q.offset,
                limit=q.limit,
                sort=q.sort,
                direction=q.dir,
                filter_spec=q.filter,
                ids=q.ids or None,
                pk=pk,
            )
        except FilterError as exc:
            raise HTTPException(400, str(exc)) from exc

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
        h = handle(net_id, component)
        src, pk = table(h, table_name), graph(h).pks.get(table_name)
        if pk is None:
            raise HTTPException(404, f"table {table_name!r} has no primary key")
        key = _coerce_key(pk_value)
        rows = page_table(src, limit=1, ids=[key], pk=pk)
        if not rows["rows"]:
            raise HTTPException(404, f"{table_name} {pk_value} not found")
        return {
            "table": table_name,
            "pk": pk,
            "id": json_scalar(key),
            "attributes": dict(zip(rows["columns"], rows["rows"][0], strict=True)),
        }

    @router.get("/tables")
    def tables_list(net_id: str, component: str) -> dict[str, Any]:
        return {"tables": [table_list_entry(n, src) for n, src in handle(net_id, component).tables().items()]}

    @router.get("/table/{table_name}/schema")
    def table_schema_ep(net_id: str, component: str, table_name: str) -> dict[str, Any]:
        h = handle(net_id, component)
        g = graph(h)
        payload = table_schema(table_name, table(h, table_name))
        payload["primary_key"] = g.pks.get(table_name)
        payload["foreign_keys"] = [
            {
                "column": fk.column,
                "ref_table": fk.ref_table,
                "ref_column": fk.ref_column,
                "navigable": fk.ref_column == g.pks.get(fk.ref_table),
            }
            for fk in g.fks
            if fk.table == table_name
        ]
        return payload

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
        h = handle(net_id, component)
        try:
            spec = _json.loads(filter) if filter else None
        except _json.JSONDecodeError as exc:
            raise HTTPException(400, f"bad filter json: {exc}") from exc
        try:
            payload = page_table(
                table(h, table_name),
                offset=offset,
                limit=limit,
                sort=sort,
                direction=dir,
                filter_spec=spec,
                ids=parse_ids(ids),
                pk=graph(h).pks.get(table_name),
            )
        except FilterError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"name": table_name, **payload}

    @router.post("/table/{table_name}/rows")
    def table_rows_post(net_id: str, component: str, table_name: str, q: RowsQuery) -> dict[str, Any]:
        """One page; with ``related`` in ``tint`` mode, ``related[i]`` names why row ``i`` is related (or null)."""
        src, pk, relation = prepared(handle(net_id, component), table_name, q)
        payload = page(src, pk, q)
        if q.related is not None and q.related_mode == "tint":
            payload["related"] = row_vias(pd.DataFrame(payload["rows"], columns=payload["columns"]), relation)
        return {"name": table_name, **payload}

    @router.post("/table/{table_name}/locate")
    def locate(net_id: str, component: str, table_name: str, q: LocateQuery) -> dict[str, Any]:
        """``{"index": i}``: the row's position in ``q``'s order (``None``: lazy table, or not in the view)."""
        src, pk, _ = prepared(handle(net_id, component), table_name, q)
        if pk is None:
            return {"index": None}
        try:
            index = locate_row(src, q.id, pk=pk, sort=q.sort, direction=q.dir, filter_spec=q.filter, ids=q.ids)
        except FilterError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"index": index}

    @router.post("/related")
    def related(net_id: str, component: str, q: RelatedQuery) -> dict[str, Any]:
        """Per related table: hop, relation labels and row count; plus link/node ids to tint on the map."""
        g = graph(handle(net_id, component))
        relations = related_of(g, q)
        tables = [
            {"table": name, "hop": r.hop, "via": r.via, "partial": r.partial, "count": count(g.tables[name], r.matches)}
            for name, r in relations.items()
        ]
        drawn: dict[str, Any] = {}
        for name in ("link", "node"):
            relation, pk = relations.get(name), g.pks.get(name)
            if relation is not None and pk:
                ids, more = ids_of(g.tables[name], relation.matches, pk, limit=MAX_MAP_IDS)
                drawn[name] = {"ids": ids, "truncated": more}
        return {"hops": q.hops, "tables": tables, "map": drawn}

    return router
