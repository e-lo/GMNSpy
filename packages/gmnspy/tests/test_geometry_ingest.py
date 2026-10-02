"""gmnspy._geometry — config-driven WKB canonicalisation on load + per-container write."""

from __future__ import annotations

import csv
from pathlib import Path

from datagrove.dataset.table import Table
from datagrove.engines.ibis_engine import IbisEngine
from gmnspy import Network
from gmnspy._geometry import DEFAULT_CRS, geometry_encoding
from gmnspy._wkt import linestring_points
from gmnspy.fixtures import leavenworth


def _engine():
    return IbisEngine()


class _Pkg:
    """Minimal stand-in exposing the ``.tables`` dict geometry_encoding reads."""

    def __init__(self, tables):
        self.tables = tables


def test_geometry_encoding_defaults_without_config():
    fmt, crs = geometry_encoding(_Pkg({}))
    assert fmt == "WKT"
    assert crs == DEFAULT_CRS


def test_geometry_encoding_reads_config_row():
    eng = _engine()
    config = Table(
        name="config",
        expr=eng.from_records([{"geometry_field_format": "WKB", "crs": "EPSG:2913"}]),
        engine=eng,
    )
    fmt, crs = geometry_encoding(_Pkg({"config": config}))
    assert fmt == "WKB"
    assert crs == "EPSG:2913"


def test_from_source_canonicalises_geometry_to_wkb():
    net = Network.from_source(leavenworth.csv_dir(), engine=_engine())
    # Leavenworth carries geometry in the `geometry` table (WKT in the CSV).
    geom = net.geometry.to_pandas()["geometry"].iloc[0]
    assert isinstance(geom, (bytes, bytearray))
    assert len(linestring_points(geom)) >= 2


def test_csv_write_emits_wkt_text(tmp_path: Path):
    net = Network.from_source(leavenworth.csv_dir(), engine=_engine())
    out = tmp_path / "out_csv"
    net.write(out, format="csv", overwrite=True)
    # The on-disk geometry.csv must carry WKT text, not WKB bytes.
    with (out / "geometry.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "geometry.csv should have rows"
    assert any("LINESTRING" in (r.get("geometry") or "") for r in rows)
    # And the in-memory network is still canonical WKB (write used a proxy).
    assert isinstance(net.geometry.to_pandas()["geometry"].iloc[0], (bytes, bytearray))


def test_csv_roundtrip_is_coordinate_lossless(tmp_path: Path):
    net = Network.from_source(leavenworth.csv_dir(), engine=_engine())
    before = linestring_points(net.geometry.to_pandas()["geometry"].iloc[0])
    out = tmp_path / "rt_csv"
    net.write(out, format="csv", overwrite=True)
    reloaded = Network.from_source(out, engine=_engine())
    after = linestring_points(reloaded.geometry.to_pandas()["geometry"].iloc[0])
    assert after == before


def test_parquet_write_keeps_wkb(tmp_path: Path):
    net = Network.from_source(leavenworth.csv_dir(), engine=_engine())
    out = tmp_path / "rt_parquet"
    net.write(out, format="parquet", overwrite=True)
    reloaded = Network.from_source(out, engine=_engine())
    cell = reloaded.geometry.to_pandas()["geometry"].iloc[0]
    assert isinstance(cell, (bytes, bytearray))
    assert linestring_points(cell) == linestring_points(net.geometry.to_pandas()["geometry"].iloc[0])
