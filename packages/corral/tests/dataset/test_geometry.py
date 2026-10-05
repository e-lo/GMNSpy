"""corral.dataset.geometry — WKT<->WKB re-encoding on a Table via duckdb spatial."""

from __future__ import annotations

import pytest
from corral.dataset.geometry import WKB, WKT, decode_wkt, encode_wkb
from corral.dataset.table import Table
from corral.engines.ibis_engine import IbisEngine

_WKT = "LINESTRING (1 2, 3 4.5, -78.8 35.9)"
_COORDS = [(1.0, 2.0), (3.0, 4.5), (-78.8, 35.9)]


def _links(engine: IbisEngine, geom=_WKT):
    expr = engine.from_records([{"link_id": 1, "geometry": geom}])
    return Table(name="link", expr=expr, engine=engine)


def _cell(table: Table):
    return table.expr.to_pyarrow().to_pylist()[0]["geometry"]


def _coords_of_wkb(wkb: bytes) -> list[tuple[float, float]]:
    shapely = pytest.importorskip("shapely")
    return [(round(x, 6), round(y, 6)) for x, y in shapely.from_wkb(bytes(wkb)).coords]


def test_encode_wkb_turns_wkt_string_into_wkb_bytes():
    cell = _cell(encode_wkb(_links(IbisEngine()), column="geometry"))
    assert isinstance(cell, (bytes, bytearray))
    assert _coords_of_wkb(cell) == _COORDS


def test_encode_wkb_is_idempotent_on_already_binary():
    eng = IbisEngine()
    once = encode_wkb(_links(eng), column="geometry")
    twice = encode_wkb(once, column="geometry")  # already WKB → no-op
    assert bytes(_cell(once)) == bytes(_cell(twice))


def test_encode_wkb_noop_when_column_absent():
    eng = IbisEngine()
    expr = eng.from_records([{"link_id": 1, "x": 5}])
    out = encode_wkb(Table(name="link", expr=expr, engine=eng), column="geometry")
    assert out.columns() == ["link_id", "x"]


def test_decode_wkt_roundtrips_wkb_back_to_text():
    shapely = pytest.importorskip("shapely")
    back = decode_wkt(encode_wkb(_links(IbisEngine())), column="geometry")
    cell = _cell(back)
    assert isinstance(cell, str)
    assert [(round(x, 6), round(y, 6)) for x, y in shapely.from_wkt(cell).coords] == _COORDS


def test_format_constants():
    assert WKT == "WKT"
    assert WKB == "WKB"
