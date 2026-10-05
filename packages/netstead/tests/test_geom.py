"""netstead._geom — shapely geometry from a WKT-or-WKB link-geometry cell."""

import pytest

pytest.importorskip("shapely")

import shapely
from netstead._geom import shapely_from_any

_WKT = "LINESTRING (1 2, 3 4.5, -78.8 35.9)"


def test_parses_wkt_string():
    g = shapely_from_any(_WKT)
    assert g is not None
    assert list(g.coords) == [(1.0, 2.0), (3.0, 4.5), (-78.8, 35.9)]


def test_parses_wkb_bytes():
    wkb = shapely.from_wkt(_WKT).wkb
    g = shapely_from_any(wkb)
    assert g is not None and g.equals(shapely.from_wkt(_WKT))


def test_accepts_bytearray_and_memoryview():
    wkb = shapely.from_wkt(_WKT).wkb
    assert shapely_from_any(bytearray(wkb)).equals(shapely.from_wkt(_WKT))
    assert shapely_from_any(memoryview(wkb)).equals(shapely.from_wkt(_WKT))


def test_none_and_empty_return_none():
    assert shapely_from_any(None) is None
    assert shapely_from_any("") is None
    assert shapely_from_any("   ") is None


def test_garbage_returns_none_not_raise():
    assert shapely_from_any(b"\x01\x02\x03") is None
    assert shapely_from_any("NOT WKT AT ALL") is None
    assert shapely_from_any(42) is None
