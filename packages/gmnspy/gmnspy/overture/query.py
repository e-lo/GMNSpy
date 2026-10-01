"""Area resolution + Overture GeoParquet reading via DuckDB (the only I/O module).

This is the only module in :mod:`gmnspy.overture` that touches external data. It
turns a user-supplied area into an EPSG:4326 bbox, reads the Overture
**transportation** theme (``segment`` + ``connector`` types) straight from
GeoParquet with DuckDB, pushes the bbox + ``class`` predicates down into
``read_parquet`` (so only matching rows cross the wire), and returns the plain
``(segments, connectors)`` records :mod:`gmnspy.overture.convert` consumes.

Overture stores geometry as WKB in GeoParquet; following the official DuckDB
recipe, geometry is turned into WKT / coordinates with the duckdb **spatial**
extension via ibis builtin-UDF wrappers (no raw SQL — the whole pipeline stays
engine-consistent). Remote ``s3://`` reads additionally need the **httpfs**
extension.

Conventions:
    * **bbox** is ``(west, south, east, north)`` in EPSG:4326.
    * a **point** is ``(lat, lon)`` (osmnx / OSM-source convention).
    * a **place** is a free-text string resolved through the OSM source's
      Nominatim geocoder (lazy import; needs the ``[osm]`` extra).

Attribution: Overture data is **ODbL** and must be attributed as
"© OpenStreetMap contributors, © Overture Maps Foundation" in derived products
(https://docs.overturemaps.org/attribution/). This library reads Overture data;
it does not vendor or redistribute it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import ibis.expr.datatypes as dt
from datagrove.engines import get_engine
from ibis import udf

from . import attrs

__all__ = [
    "OVERTURE_RELEASE",
    "fetch_network_elements",
    "overture_data_root",
    "point_buffer_bbox",
    "read_connectors",
    "read_segments",
    "resolve_area",
]

# Pinned, known-good Overture release (date-versioned). Bump this one constant to
# move to a newer release; pinning keeps builds reproducible (a re-run of the same
# area returns the same network). Override per-call with ``overture_release=``.
OVERTURE_RELEASE = "2024-11-13.0"

# Default AWS public bucket base (anonymous read). Override via ``data_root=``
# for the Azure mirror or a local snapshot.
_AWS_BASE = "s3://overturemaps-us-west-2/release"

# Overture transportation subtype we build road networks from (Phase 1).
_ROAD_SUBTYPE = "road"

# Metres per degree of latitude (spherical approximation).
_M_PER_DEG_LAT = 111320.0

# Padding (degrees) applied to the connector read bbox so endpoint connectors
# that fall just outside the segment bbox are still fetched — avoids dangling
# ``to_node_id`` references. ~1 km; the converter fail-fasts on anything still
# missing.
_CONNECTOR_PAD_DEG = 0.01

# Overture segment property columns the converter / mapping may read. Only those
# actually present in the source are selected (so a trimmed fixture still works).
_SEGMENT_PROPERTY_COLUMNS = (
    "id",
    "subtype",
    "class",
    "subclass",
    "names",
    "routes",
    "speed_limits",
    "access_restrictions",
    "lanes",
    "road_flags",
    "connectors",
)


# ---------------------------------------------------------------------------
# DuckDB spatial extension — ibis builtin UDF wrappers (no pandas round-trip,
# no raw SQL; mirrors datagrove.dataset.view). Geometry is binary (WKB) across
# the ibis <-> duckdb boundary.
# ---------------------------------------------------------------------------


@udf.scalar.builtin(name="ST_GeomFromWKB")
def _st_geom_from_wkb(wkb: dt.binary) -> dt.binary:  # type: ignore[empty-body]
    """Parse WKB into a duckdb GEOMETRY."""


@udf.scalar.builtin(name="ST_AsText")
def _st_as_text(geom: dt.binary) -> str:  # type: ignore[empty-body]
    """Render a duckdb GEOMETRY as WKT."""


@udf.scalar.builtin(name="ST_X")
def _st_x(geom: dt.binary) -> float:  # type: ignore[empty-body]
    """Return the X (longitude) ordinate of a POINT GEOMETRY."""


@udf.scalar.builtin(name="ST_Y")
def _st_y(geom: dt.binary) -> float:  # type: ignore[empty-body]
    """Return the Y (latitude) ordinate of a POINT GEOMETRY."""


_SPATIAL_LOADED_ATTR = "_gmnspy_overture_spatial_loaded"
_HTTPFS_LOADED_ATTR = "_gmnspy_overture_httpfs_loaded"


def _ensure_extension(backend: Any, name: str, cached_attr: str) -> None:
    """Install + load a duckdb extension on ``backend`` once (cached, no SQL)."""
    if getattr(backend, cached_attr, False):
        return
    raw = getattr(backend, "con", None)
    if raw is None:  # pragma: no cover - protective
        raise RuntimeError(
            "gmnspy.overture.query requires an ibis duckdb backend; "
            f"got {type(backend).__name__} with no underlying duckdb connection."
        )
    raw.install_extension(name)
    backend.load_extension(name)
    setattr(backend, cached_attr, True)


# ---------------------------------------------------------------------------
# Area resolution
# ---------------------------------------------------------------------------


def point_buffer_bbox(lat: float, lon: float, buffer_m: float) -> tuple[float, float, float, float]:
    """Return a ``(west, south, east, north)`` bbox around a point.

    Args:
        lat: Latitude of the centre point.
        lon: Longitude of the centre point.
        buffer_m: Half-width of the box in metres (added on every side).

    Returns:
        The bounding box as ``(west, south, east, north)`` in degrees.

    Examples:
        >>> w, s, e, n = point_buffer_bbox(0.0, 0.0, 111320.0)
        >>> round(e, 3), round(n, 3)
        (1.0, 1.0)
    """
    dlat = buffer_m / _M_PER_DEG_LAT
    cos_lat = math.cos(math.radians(lat))
    dlon = buffer_m / (_M_PER_DEG_LAT * cos_lat) if cos_lat else dlat
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def resolve_area(area: str | Sequence[float], *, buffer_m: float = 0.0) -> tuple[float, float, float, float]:
    """Resolve a user-supplied area to a ``(west, south, east, north)`` bbox.

    A 4-sequence is taken as a bbox; a 2-sequence as a ``(lat, lon)`` point
    expanded by ``buffer_m``; a string is geocoded through the OSM source's
    Nominatim helper (lazy import — needs the ``[osm]`` extra). The bbox-only
    return keeps the Overture read bbox-driven (GeoParquet pushes a bbox
    predicate down; polygon clipping is not a Phase-1 feature).

    Args:
        area: A place string, a ``(lat, lon)`` point, or a
            ``(west, south, east, north)`` bbox.
        buffer_m: Buffer in metres applied when ``area`` is a point.

    Returns:
        The resolved ``(west, south, east, north)`` bbox.

    Raises:
        ValueError: If ``area`` is not a string, 2-tuple, or 4-tuple.

    Examples:
        >>> resolve_area((-71.1, 42.0, -71.0, 42.1))
        (-71.1, 42.0, -71.0, 42.1)
    """
    if isinstance(area, str):
        from gmnspy.osm import query as osm_query  # lazy: place geocoding needs [osm]

        return tuple(osm_query.geocode_area(area)["bbox"])  # type: ignore[return-value]
    if isinstance(area, Sequence) and not isinstance(area, str | bytes):
        values = [float(v) for v in area]
        if len(values) == 4:
            return (values[0], values[1], values[2], values[3])
        if len(values) == 2:
            return point_buffer_bbox(values[0], values[1], buffer_m)
    raise ValueError("area must be a place string, a (lat, lon) point, or a (west, south, east, north) bbox")


# ---------------------------------------------------------------------------
# Source URIs
# ---------------------------------------------------------------------------


def overture_data_root(overture_release: str, data_root: str | None) -> str:
    """Return the base URI for an Overture release (AWS bucket unless overridden).

    Args:
        overture_release: Date-versioned release string (e.g. ``"2024-11-13.0"``).
        data_root: Explicit base URI (Azure mirror / local snapshot dir). When
            given it is used verbatim and ``overture_release`` is ignored.

    Returns:
        The release base URI (no trailing slash).

    Examples:
        >>> overture_data_root("2024-11-13.0", None)
        's3://overturemaps-us-west-2/release/2024-11-13.0'
        >>> overture_data_root("ignored", "/snap")
        '/snap'
    """
    if data_root is not None:
        return data_root.rstrip("/")
    return f"{_AWS_BASE}/{overture_release}"


def _type_source(root: str, feature_type: str) -> str:
    """Return the read path for a transportation feature type under ``root``.

    Hive-partitioned remote layout (``theme=.../type=.../*``) for ``s3://`` roots;
    a flat ``<type>.parquet`` file for a local-snapshot / fixture root.
    """
    if root.startswith(("s3://", "az://", "abfss://", "http://", "https://")):
        return f"{root}/theme=transportation/type={feature_type}/*"
    return f"{root}/{feature_type}.parquet"


def _prepare_backend(engine: Any, source: str) -> Any:
    """Load the duckdb extensions the read needs and return the engine's backend."""
    backend = engine.con
    _ensure_extension(backend, "spatial", _SPATIAL_LOADED_ATTR)
    if source.startswith(("s3://", "az://", "abfss://", "http://", "https://")):
        _ensure_extension(backend, "httpfs", _HTTPFS_LOADED_ATTR)
    return backend


def _bbox_intersects(table: Any, bbox: tuple[float, float, float, float]) -> Any:
    """Build the ibis predicate: row ``bbox`` struct intersects ``bbox``."""
    west, south, east, north = bbox
    return (
        (table.bbox.xmin <= east) & (table.bbox.xmax >= west) & (table.bbox.ymin <= north) & (table.bbox.ymax >= south)
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def read_segments(
    bbox: tuple[float, float, float, float],
    *,
    network_type: str = "drive",
    overture_release: str = OVERTURE_RELEASE,
    data_root: str | None = None,
    engine: Any = None,
    extra_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Read in-bbox Overture road segments as plain records.

    The bbox + ``class`` predicates are pushed into ``read_parquet`` so unrelated
    rows / partitions are pruned. Geometry is returned as a WKT ``LINESTRING`` in
    the ``geometry`` key; nested properties (``names``, ``speed_limits``,
    ``connectors``, ...) come back as nested Python dicts / lists.

    Args:
        bbox: ``(west, south, east, north)`` in EPSG:4326.
        network_type: One of ``drive``/``walk``/``bike``/``all``; selects the
            allowed ``class`` list (``all`` applies no class filter).
        overture_release: Pinned release string (ignored when ``data_root`` set).
        data_root: Override base URI (Azure mirror / local snapshot dir).
        engine: Compute engine (default: datagrove ibis/duckdb).
        extra_tags: Extra dotted Overture property paths to carry; their
            top-level columns are added to the read projection.

    Returns:
        A list of segment records (``geometry`` as WKT + nested properties).
    """
    engine = engine or get_engine()
    root = overture_data_root(overture_release, data_root)
    source = _type_source(root, "segment")
    _prepare_backend(engine, source)

    table = engine.read_parquet(source, hive_partitioning=source.endswith("/*"))
    available = set(table.columns)
    predicate = _bbox_intersects(table, bbox)
    if "subtype" in available:
        predicate = predicate & (table.subtype == _ROAD_SUBTYPE)
    allowed = attrs.allowed_classes(network_type)
    if allowed and "class" in available:
        predicate = predicate & table["class"].isin(sorted(allowed))
    filtered = table.filter(predicate)

    wanted = [c for c in _SEGMENT_PROPERTY_COLUMNS if c in available]
    for path in extra_tags or []:
        top = path.split(".")[0]
        if top in available and top not in wanted:
            wanted.append(top)
    projected = filtered.select(*wanted, geometry=_st_as_text(_st_geom_from_wkb(filtered.geometry)))
    return projected.to_pyarrow().to_pylist()


def read_connectors(
    bbox: tuple[float, float, float, float],
    *,
    overture_release: str = OVERTURE_RELEASE,
    data_root: str | None = None,
    engine: Any = None,
    pad_deg: float = _CONNECTOR_PAD_DEG,
) -> dict[str, tuple[float, float]]:
    """Read Overture connectors near ``bbox`` as a ``{connector_id: (lon, lat)}`` map.

    The read bbox is padded by ``pad_deg`` so endpoint connectors just outside
    the segment bbox are still fetched (preventing dangling ``to_node_id``).

    Args:
        bbox: ``(west, south, east, north)`` in EPSG:4326.
        overture_release: Pinned release string (ignored when ``data_root`` set).
        data_root: Override base URI (Azure mirror / local snapshot dir).
        engine: Compute engine (default: datagrove ibis/duckdb).
        pad_deg: Degrees of padding added on every side of the read bbox.

    Returns:
        ``{connector_id: (lon, lat)}`` for connectors in the padded bbox.
    """
    engine = engine or get_engine()
    root = overture_data_root(overture_release, data_root)
    source = _type_source(root, "connector")
    _prepare_backend(engine, source)

    west, south, east, north = bbox
    padded = (west - pad_deg, south - pad_deg, east + pad_deg, north + pad_deg)
    table = engine.read_parquet(source, hive_partitioning=source.endswith("/*"))
    filtered = table.filter(_bbox_intersects(table, padded))
    projected = filtered.select(
        "id",
        x=_st_x(_st_geom_from_wkb(filtered.geometry)),
        y=_st_y(_st_geom_from_wkb(filtered.geometry)),
    )
    rows = projected.to_pyarrow().to_pylist()
    return {row["id"]: (row["x"], row["y"]) for row in rows}


def fetch_network_elements(
    area: str | Sequence[float],
    *,
    buffer_m: float = 0.0,
    network_type: str = "drive",
    overture_release: str = OVERTURE_RELEASE,
    data_root: str | None = None,
    engine: Any = None,
    extra_tags: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, tuple[float, float]]]:
    """Resolve ``area`` and read its Overture segments + connectors.

    Args:
        area: Place string, ``(lat, lon)`` point, or ``(west, south, east,
            north)`` bbox.
        buffer_m: Buffer in metres applied when ``area`` is a point.
        network_type: One of ``drive``/``walk``/``bike``/``all``.
        overture_release: Pinned release string (ignored when ``data_root`` set).
        data_root: Override base URI (Azure mirror / local snapshot dir).
        engine: Compute engine (default: datagrove ibis/duckdb).
        extra_tags: Extra dotted Overture property paths to carry onto links.

    Returns:
        ``(segments, connectors)`` ready for
        :func:`gmnspy.overture.convert.build_node_link_tables`.
    """
    engine = engine or get_engine()
    bbox = resolve_area(area, buffer_m=buffer_m)
    segments = read_segments(
        bbox,
        network_type=network_type,
        overture_release=overture_release,
        data_root=data_root,
        engine=engine,
        extra_tags=extra_tags,
    )
    connectors = read_connectors(
        bbox,
        overture_release=overture_release,
        data_root=data_root,
        engine=engine,
    )
    return segments, connectors
