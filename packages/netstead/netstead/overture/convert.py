"""Pure Overture segments + connectors -> GMNS node/link records (no I/O).

The converter turns parsed Overture ``segment`` and ``connector`` records into
flat GMNS ``node`` and ``link`` records. Unlike the OSM converter — which must
*infer* which shape points are intersections — Overture states topology
explicitly: every segment carries an ordered ``connectors[]`` array of
``{connector_id, at}`` entries, and two segments connect **iff** they reference
the same connector id. Node identity is therefore authoritative, not heuristic.

Conversion rule (per the scope doc):
    * Each referenced **connector** becomes a GMNS **node**. Node ids are minted
      integers (deterministic, sorted by connector id); the original GERS-style
      connector id rides along in the ``overture_connector_id`` provenance column.
    * Each **segment** is split at its ordered connectors: every consecutive
      connector pair becomes an undirected sub-segment whose geometry is the
      slice of the segment LineString between the two ``at`` linear references.
    * Each undirected sub-segment expands to directed GMNS links — two for a
      two-way segment (``directed=True`` on every link), one for a one-way
      (direction from :func:`netstead.overture.attrs.overture_direction`).

Units: ``length`` is geodesic metres; ``free_speed`` is mph.

Input contract:
    * ``connectors``: ``{connector_id: (lon, lat)}`` (EPSG:4326).
    * ``segments``: sequence of dicts carrying at least ``id`` (str),
      ``connectors`` (``[{"connector_id", "at"}, ...]``), ``geometry`` (a WKT
      ``LINESTRING``), plus the raw Overture properties the mapping reads
      (``class``, ``names``, ``speed_limits``, ``routes``,
      ``access_restrictions``, ...).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

from . import attrs
from ._geo import line_length_m, parse_wkt_linestring, slice_line, wkt_linestring

__all__ = ["build_node_link_tables"]


def build_node_link_tables(
    segments: Sequence[Mapping[str, Any]],
    connectors: Mapping[str, tuple[float, float]],
    *,
    extra_tags: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert Overture segments + connectors into GMNS ``node``/``link`` records.

    Args:
        segments: Overture segment records (see the module contract).
        connectors: ``{connector_id: (lon, lat)}`` coordinate lookup (EPSG:4326).
        extra_tags: Optional dotted Overture property paths to carry onto each
            link as extra columns (named by the path's last segment).

    Returns:
        A ``(node_records, link_records)`` tuple. ``node_records`` carry
        ``node_id`` (minted int), ``x_coord`` (lon), ``y_coord`` (lat) and
        ``overture_connector_id`` (provenance). ``link_records`` carry
        ``link_id``, ``from_node_id``, ``to_node_id``, ``directed`` (always
        ``True``), ``length`` (metres), ``free_speed``, ``lanes``,
        ``facility_type``, ``name``, ``ref``, ``geometry`` (WKT), and the
        provenance fields ``overture_segment_id`` + ``overture_connector_ids``.

    Raises:
        ValueError: If a segment references a connector id absent from
            ``connectors`` (a dangling node — fail fast, mirroring the OSM
            converter's "every referenced node exists" guard).

    Examples:
        >>> conns = {"a": (0.0, 0.0), "b": (0.0, 2.0)}
        >>> segs = [{
        ...     "id": "s1",
        ...     "class": "residential",
        ...     "geometry": "LINESTRING (0 0, 0 2)",
        ...     "connectors": [{"connector_id": "a", "at": 0.0},
        ...                    {"connector_id": "b", "at": 1.0}],
        ... }]
        >>> node_recs, link_recs = build_node_link_tables(segs, conns)
        >>> sorted(n["overture_connector_id"] for n in node_recs)
        ['a', 'b']
        >>> len(link_recs)  # two-way -> two directed links
        2
    """
    _assert_connectors_present(segments, connectors)
    node_id_of = _mint_node_ids(segments, connectors)
    extra = list(extra_tags or [])

    link_records: list[dict[str, Any]] = []
    used: set[str] = set()
    link_id = 0

    for segment in segments:
        mapped = attrs.apply_mapping(segment, extra)
        direction = attrs.overture_direction(segment)
        coords = parse_wkt_linestring(str(segment["geometry"]))
        ordered = _ordered_connectors(segment)

        for (cid_a, at_a), (cid_b, at_b) in pairwise(ordered):
            if at_a >= at_b:
                # Coincident / out-of-order linear refs can't form a sub-segment;
                # skip rather than raise (keeps a single odd segment from
                # failing an entire build).
                continue
            sub_coords = slice_line(coords, at_a, at_b)
            # Snap the sliced endpoints onto the authoritative connector points
            # so each link's geometry endpoints equal its node coordinates.
            sub_coords[0] = connectors[cid_a]
            sub_coords[-1] = connectors[cid_b]

            for oriented_coords, (from_cid, to_cid) in _orient(sub_coords, (cid_a, cid_b), direction):
                link_id += 1
                record: dict[str, Any] = {
                    "link_id": link_id,
                    "from_node_id": node_id_of[from_cid],
                    "to_node_id": node_id_of[to_cid],
                    "directed": True,
                    "length": round(line_length_m(oriented_coords), 2),
                    "free_speed": mapped["free_speed"],
                    "lanes": mapped["lanes"],
                    "facility_type": mapped["facility_type"],
                    "name": mapped["name"],
                    "ref": mapped["ref"],
                    "geometry": wkt_linestring(oriented_coords),
                    "overture_segment_id": segment.get("id"),
                    "overture_connector_ids": f"{from_cid},{to_cid}",
                }
                for path in extra:
                    column = path.split(".")[-1]
                    record[column] = mapped[column]
                link_records.append(record)
                used.add(from_cid)
                used.add(to_cid)

    node_records = [
        {
            "node_id": node_id_of[cid],
            "x_coord": connectors[cid][0],
            "y_coord": connectors[cid][1],
            "overture_connector_id": cid,
        }
        for cid in sorted(used)
    ]
    return node_records, link_records


def _assert_connectors_present(
    segments: Sequence[Mapping[str, Any]],
    connectors: Mapping[str, tuple[float, float]],
) -> None:
    """Fail fast if any segment references a connector id not in ``connectors``."""
    for segment in segments:
        for entry in _ordered_connectors(segment):
            cid = entry[0]
            if cid not in connectors:
                raise ValueError(
                    f"segment {segment.get('id')!r} references connector {cid!r} "
                    f"which is not in the connectors dict ({len(connectors)} connectors given); "
                    "the connector read must cover every connector the segments reference."
                )


def _mint_node_ids(
    segments: Sequence[Mapping[str, Any]],
    connectors: Mapping[str, tuple[float, float]],
) -> dict[str, int]:
    """Assign deterministic 1-based integer node ids to referenced connector ids."""
    referenced: set[str] = set()
    for segment in segments:
        for cid, _at in _ordered_connectors(segment):
            referenced.add(cid)
    return {cid: i for i, cid in enumerate(sorted(referenced), start=1)}


def _ordered_connectors(segment: Mapping[str, Any]) -> list[tuple[str, float]]:
    """Return a segment's connectors as ``(connector_id, at)`` sorted by ``at``.

    Overture lists connectors in order, but sorting by the linear reference is
    cheap insurance against an out-of-order producer.
    """
    raw = segment.get("connectors") or []
    pairs: list[tuple[str, float]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        cid = entry.get("connector_id")
        if cid is None:
            continue
        at = entry.get("at")
        pairs.append((str(cid), float(at) if at is not None else 0.0))
    pairs.sort(key=lambda p: p[1])
    return pairs


def _orient(
    sub_coords: list[tuple[float, float]],
    endpoints: tuple[str, str],
    direction: str,
):
    """Yield ``(coords, (from_cid, to_cid))`` per emitted directed link.

    ``both`` yields the forward orientation and its reverse; ``forward`` yields
    only the connector-order orientation; ``backward`` yields only the reverse.
    """
    cid_a, cid_b = endpoints
    forward = (list(sub_coords), (cid_a, cid_b))
    backward = (list(reversed(sub_coords)), (cid_b, cid_a))
    if direction == "forward":
        yield forward
    elif direction == "backward":
        yield backward
    else:  # "both"
        yield forward
        yield backward
