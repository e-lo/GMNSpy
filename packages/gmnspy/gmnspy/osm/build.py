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

from gmnspy._network_build import network_from_records as _network_from_records
from gmnspy.network import Network
from gmnspy.spec import DEFAULT_SPEC

from . import convert, query

__all__ = ["build_network_from_osm", "network_from_records"]


def network_from_records(
    node_records: Sequence[dict[str, Any]],
    link_records: Sequence[dict[str, Any]],
    *,
    spec_version: str = DEFAULT_SPEC,
    engine: Any = None,
) -> Network:
    """Assemble a :class:`~gmnspy.network.Network` from OSM node/link records.

    Thin wrapper over :func:`gmnspy._network_build.network_from_records` that
    stamps the ``osm_export`` dataset name on the generated ``config`` table.
    The records are loaded onto the engine verbatim (extra provenance columns
    ``osm_way_id`` / ``osm_node_ids`` preserved); the per-table GMNS schema is
    attached so :meth:`Network.validate` can run.

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
    return _network_from_records(
        node_records,
        link_records,
        spec_version=spec_version,
        engine=engine,
        dataset_name="osm_export",
    )


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
