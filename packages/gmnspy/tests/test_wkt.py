"""gmnspy._wkt — WKT + WKB LINESTRING coordinate extraction (dep-free)."""

import struct

import pytest
from gmnspy._wkt import (
    _parse_linestring_points,
    _parse_wkb_linestring_points,
    linestring_points,
    linestring_wkb,
)

_PTS = [(1.0, 2.0), (3.0, 4.5), (-78.8, 35.9)]


def _wkb(points, *, little=True, z=False, srid=None):
    """Hand-build an ISO/EWKB 2D (or Z) LINESTRING WKB for the test."""
    bo = "<" if little else ">"
    order = b"\x01" if little else b"\x00"
    gtype = 2
    if z:
        gtype = 1002
    if srid is not None:
        gtype |= 0x20000000
    out = order + struct.pack(bo + "I", gtype)
    if srid is not None:
        out += struct.pack(bo + "I", srid)
    out += struct.pack(bo + "I", len(points))
    for x, y in points:
        out += struct.pack(bo + "dd", x, y)
        if z:
            out += struct.pack(bo + "d", 0.0)
    return out


def test_wkt_parser_still_works():
    assert _parse_linestring_points("LINESTRING (1 2, 3 4.5, -78.8 35.9)") == _PTS


def test_wkb_little_endian():
    assert _parse_wkb_linestring_points(_wkb(_PTS)) == _PTS


def test_wkb_big_endian():
    assert _parse_wkb_linestring_points(_wkb(_PTS, little=False)) == _PTS


def test_wkb_with_z_is_dropped_to_xy():
    assert _parse_wkb_linestring_points(_wkb(_PTS, z=True)) == _PTS


def test_wkb_ewkb_with_srid():
    assert _parse_wkb_linestring_points(_wkb(_PTS, srid=4326)) == _PTS


def test_matches_shapely_wkb():
    shapely = pytest.importorskip("shapely")
    g = shapely.from_wkt("LINESTRING (1 2, 3 4.5, -78.8 35.9)")
    assert _parse_wkb_linestring_points(g.wkb) == _PTS


def test_dispatcher_handles_str_and_bytes():
    assert linestring_points("LINESTRING (1 2, 3 4.5, -78.8 35.9)") == _PTS
    assert linestring_points(_wkb(_PTS)) == _PTS
    assert linestring_points(None) == []
    assert linestring_points(bytearray(_wkb(_PTS))) == _PTS


def test_garbage_returns_empty():
    assert _parse_wkb_linestring_points(b"\x01\x02") == []
    assert _parse_wkb_linestring_points("not bytes") == []


def test_linestring_wkb_roundtrips_through_decoder():
    assert _parse_wkb_linestring_points(linestring_wkb(_PTS)) == _PTS


def test_linestring_wkb_is_little_endian_iso_2d():
    blob = linestring_wkb(_PTS)
    assert blob[0] == 1  # little-endian byte-order flag
    (gtype,) = struct.unpack_from("<I", blob, 1)
    assert gtype == 2  # ISO WKB 2D LINESTRING, no SRID/Z/M flags
    (n,) = struct.unpack_from("<I", blob, 5)
    assert n == len(_PTS)


def test_linestring_wkb_matches_shapely():
    shapely = pytest.importorskip("shapely")
    mine = linestring_wkb(_PTS)
    theirs = shapely.LineString(_PTS).wkb
    # Both decode to the same coordinates; shapely also emits little-endian 2D.
    assert shapely.from_wkb(mine).equals(shapely.LineString(_PTS))
    assert _parse_wkb_linestring_points(theirs) == _parse_wkb_linestring_points(mine)


def test_linestring_wkb_empty_for_degenerate():
    assert linestring_wkb([]) == b""
    assert linestring_wkb([(1.0, 2.0)]) == b""  # a single point is not a line
