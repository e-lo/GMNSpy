"""Tiny, dependency-free ``LINESTRING`` coordinate extraction — WKT *and* WKB.

Lives at the package root (not under ``gmnspy.map``) so low-level consumers like
``gmnspy.viz`` and ``gmnspy.select`` can read link geometry without importing the
optional-extra ``gmnspy.map`` module — keeping the ``cli`` → ``map`` import
boundary (enforced by import-linter) intact. ``shapely`` is a heavy C-extension
dep to drag in just for coordinate extraction, so this stays hand-rolled over
``re`` + ``struct`` (both stdlib).

Geometry is stored as **WKB bytes** in memory / Parquet and as **WKT text** in
CSV, so callers that may see either should use :func:`linestring_points`.
"""

from __future__ import annotations

import re
import struct

#: Matches each ``x y`` coordinate pair inside a WKT geometry string.
_WKT_POINT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")

_WKB_LINESTRING = 2  # OGC base type for LINESTRING


def _parse_linestring_points(wkt: str) -> list[tuple[float, float]]:
    """Parse a ``LINESTRING (x y, x y, ...)`` WKT to a list of ``(lon, lat)``.

    Accepts a leading ``LINESTRING`` / ``LINESTRING M`` / ``LINESTRING Z`` token
    (case-insensitive) and any surrounding whitespace. Returns an empty list when
    the input is not a string or no coordinates parse.
    """
    if not isinstance(wkt, str):
        return []
    return [(float(x), float(y)) for x, y in _WKT_POINT_RE.findall(wkt)]


def _parse_wkb_linestring_points(wkb: object) -> list[tuple[float, float]]:
    """Parse a WKB ``LINESTRING`` to ``(x, y)`` pairs (Z/M dropped).

    Handles little- and big-endian, ISO WKB dimension codes (1000=Z, 2000=M,
    3000=ZM) and EWKB flags (0x8000_0000=Z, 0x4000_0000=M, 0x2000_0000=SRID).
    Returns an empty list for non-bytes input, truncated buffers, or a non-
    LINESTRING type (a defensive, never-raise reader).
    """
    if not isinstance(wkb, (bytes, bytearray, memoryview)):
        return []
    b = bytes(wkb)
    if len(b) < 9:  # order(1) + type(4) + count(4)
        return []
    try:
        bo = "<" if b[0] == 1 else ">"
        (gtype,) = struct.unpack_from(bo + "I", b, 1)
        off = 5
        has_z = bool(gtype & 0x80000000)
        has_m = bool(gtype & 0x40000000)
        has_srid = bool(gtype & 0x20000000)
        low = gtype & 0x1FFFFFFF  # strip EWKB flags → ISO code
        base = low % 1000
        thousands = low // 1000
        has_z = has_z or thousands in (1, 3)
        has_m = has_m or thousands in (2, 3)
        if base != _WKB_LINESTRING:
            return []
        if has_srid:
            off += 4
        (n,) = struct.unpack_from(bo + "I", b, off)
        off += 4
        dims = 2 + (1 if has_z else 0) + (1 if has_m else 0)
        stride = 8 * dims
        pts: list[tuple[float, float]] = []
        for _ in range(n):
            x, y = struct.unpack_from(bo + "dd", b, off)
            pts.append((x, y))
            off += stride
        return pts
    except struct.error:
        return []


def linestring_wkb(points: list[tuple[float, float]] | object) -> bytes:
    """Encode ``(x, y)`` pairs as a little-endian ISO WKB 2D ``LINESTRING``.

    The symmetric counterpart to :func:`_parse_wkb_linestring_points`: dep-free
    (stdlib ``struct``), little-endian, OGC base type ``2`` with no SRID/Z/M
    flags — the same shape duckdb's ``ST_AsWKB`` and shapely emit, so it round-
    trips through both. Used by :mod:`gmnspy.semantics` to synthesise a straight
    link geometry from node endpoints without pulling in shapely or duckdb.

    A degenerate input (not a sequence of ≥2 points) returns ``b""`` — a single
    point is not a line, matching how the decoder treats unparseable geometry as
    "no geometry" rather than raising.
    """
    try:
        pts = [(float(x), float(y)) for x, y in points]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return b""
    if len(pts) < 2:
        return b""
    out = b"\x01" + struct.pack("<I", _WKB_LINESTRING) + struct.pack("<I", len(pts))
    for x, y in pts:
        out += struct.pack("<dd", x, y)
    return out


def linestring_points(geom: object) -> list[tuple[float, float]]:
    """Return ``(x, y)`` pairs from a link geometry that may be WKT or WKB.

    Dispatches on type: ``str`` → WKT, ``bytes``/``bytearray``/``memoryview`` →
    WKB. Anything else (e.g. ``None``/NaN) → empty list. This is the one entry
    point callers should use when a geometry column could be either encoding.
    """
    if isinstance(geom, str):
        return _parse_linestring_points(geom)
    if isinstance(geom, (bytes, bytearray, memoryview)):
        return _parse_wkb_linestring_points(geom)
    return []
