"""Orchestration: fetch OSM -> convert -> assemble a GMNS :class:`~gmnspy.network.Network`.

:func:`build_network_from_osm` is the public entry point for the whole pipeline
(area resolution + Overpass fetch + node/link conversion + Network assembly).
:func:`network_from_records` is the records -> Network half on its own, exposed
so callers (and the benchmark harness) can build a Network from already-fetched
records without re-hitting the network.

The assembled Network carries the GMNS ``node`` and ``link`` tables on the
chosen engine (datagrove default ibis, or an explicit ``engine=``). Provenance
columns (``osm_way_id``, ``osm_node_ids``) ride along as extra columns; the
per-table GMNS schema is attached for validation.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from datagrove.dataset import Table
from datagrove.engines import get_engine

from gmnspy.network import Network
from gmnspy.spec import DEFAULT_SPEC, load_gmns_spec

from . import convert, query

__all__ = ["build_network_from_osm", "network_from_records"]

# Units the converter emits, declared on the generated GMNS `config` table so
# the network is self-describing (GMNS is unit-agnostic — units live in config).
# free_speed is mph (faithful to US OSM maxspeed tags); length is geodesic
# metres. Change here (and in gmnspy.osm.convert) to switch unit systems.
_UNITS = {
    "short_length": "meter",
    "long_length": "meter",
    "speed": "mph",
    "crs": "EPSG:4326",
    "geometry_field_format": "WKT",
}


def _resource_schema(spec: Any, name: str) -> Any:
    """Return the resolved schema for resource ``name`` from a loaded spec."""
    for resource in spec.resources:
        if resource.name == name:
            return resource.table_schema
    return None


def _records_to_expr(eng: Any, records: Sequence[dict[str, Any]], schema: Any) -> Any:
    """Build a table expression from records, preserving columns when empty.

    An empty record list yields a column-less frame, which the ibis/duckdb
    engine rejects ("must have at least one column"). When empty, build a
    zero-row frame whose columns come from the schema so the table stays valid
    and typed.
    """
    records = list(records)
    if records:
        return eng.from_records(records, schema=schema)
    columns: dict[str, list[Any]] = {field.name: [] for field in schema.fields} if schema and schema.fields else {}
    return eng.from_records(columns, schema=schema)


def _config_records(spec_version: str) -> list[dict[str, Any]]:
    """Build the single-row GMNS ``config`` table declaring units + CRS."""
    try:
        version_number = float(spec_version)
    except (TypeError, ValueError):
        version_number = None
    return [{"dataset_name": "osm_export", "id_type": "integer", "version_number": version_number, **_UNITS}]


def network_from_records(
    node_records: Sequence[dict[str, Any]],
    link_records: Sequence[dict[str, Any]],
    *,
    spec_version: str = DEFAULT_SPEC,
    engine: Any = None,
) -> Network:
    """Assemble a :class:`~gmnspy.network.Network` from node/link records.

    The records are loaded onto the engine verbatim (extra provenance columns
    preserved); the per-table GMNS schema is attached to each table so
    :meth:`Network.validate` can run.

    Args:
        node_records: GMNS ``node`` rows (e.g. from
            :func:`gmnspy.osm.convert.build_node_link_tables`).
        link_records: GMNS ``link`` rows.
        spec_version: GMNS spec version to validate against
            (default :data:`gmnspy.spec.DEFAULT_SPEC`).
        engine: Engine to materialise through. Defaults to the datagrove
            default (ibis).

    Returns:
        A :class:`~gmnspy.network.Network` with ``node`` and ``link`` tables
        and ``spec_version`` stamped.
    """
    eng = engine or get_engine()
    gmns_spec = load_gmns_spec(spec_version)
    node_schema = _resource_schema(gmns_spec, "node")
    link_schema = _resource_schema(gmns_spec, "link")
    config_schema = _resource_schema(gmns_spec, "config")

    # Pass the schema to from_records so GMNS columns get their declared
    # (nullable) types even when an optional column is entirely null — an
    # all-None column otherwise infers as `null` dtype and fails schema
    # validation. cast_schema leaves non-schema columns (osm_way_id,
    # osm_node_ids) untouched, so provenance is preserved.
    tables = {
        "node": Table(
            name="node",
            expr=_records_to_expr(eng, node_records, node_schema),
            engine=eng,
            schema=node_schema,
        ),
        "link": Table(
            name="link",
            expr=_records_to_expr(eng, link_records, link_schema),
            engine=eng,
            schema=link_schema,
        ),
        "config": Table(
            name="config",
            expr=eng.from_records(_config_records(spec_version), schema=config_schema),
            engine=eng,
            schema=config_schema,
        ),
    }
    return Network(spec=gmns_spec, tables=tables, engine=eng, source=None, spec_version=spec_version)


def build_network_from_osm(
    area: str | Sequence[float],
    *,
    buffer_m: float = 0.0,
    network_type: str = "drive",
    extra_tags: list[str] | None = None,
    spec_version: str = DEFAULT_SPEC,
    engine: Any = None,
    endpoint: str = query.OVERPASS_URL,
    session: Any = None,
    user_agent: str = query.USER_AGENT,
    timeout: int = 180,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> Network:
    """Build a GMNS network from OpenStreetMap for ``area``.

    Args:
        area: A place string, a ``(lat, lon)`` point, or a
            ``(west, south, east, north)`` bbox.
        buffer_m: Buffer in metres applied when ``area`` is a point.
        network_type: One of ``drive``/``walk``/``bike``/``all``.
        extra_tags: OSM tag keys to carry onto each link as extra columns.
        spec_version: GMNS spec version (default :data:`gmnspy.spec.DEFAULT_SPEC`).
        engine: Engine to materialise through (default: datagrove ibis).
        endpoint: Overpass API endpoint URL.
        session: HTTP session (injectable for tests). Defaults to ``requests``.
        user_agent: ``User-Agent`` header value.
        timeout: Per-request timeout, seconds.
        retries: Retries on transient status codes.
        sleep: Sleep function used between retries.

    Returns:
        A populated :class:`~gmnspy.network.Network`.
    """
    nodes, ways = query.fetch_network_elements(
        area,
        buffer_m=buffer_m,
        network_type=network_type,
        endpoint=endpoint,
        session=session,
        user_agent=user_agent,
        timeout=timeout,
        retries=retries,
        sleep=sleep,
    )
    node_records, link_records = convert.build_node_link_tables(nodes, ways, extra_tags=extra_tags)
    if not link_records:
        raise ValueError(
            f"no OSM ways matched for network_type={network_type!r} in the requested area; "
            "try a larger area or a different --network-type."
        )
    return network_from_records(node_records, link_records, spec_version=spec_version, engine=engine)
