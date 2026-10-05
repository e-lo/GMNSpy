"""CSV-in-zip GMNS packages: open the bundled zip, write + reopen, and ``netstead build --format zip``."""

from __future__ import annotations

import json
import zipfile

import pytest
from corral.engines.ibis_engine import IbisEngine
from netstead import Network
from netstead.cli.app import app
from netstead.fixtures import leavenworth
from typer.testing import CliRunner


def _link_geometry(net: Network) -> list:
    """First few link shapes (Leavenworth keeps them in the ``geometry`` table)."""
    df = net.geometry.to_pandas().sort_values("geometry_id")
    return list(df["geometry"].head(10))


def test_open_bundled_zip_matches_csv_dir() -> None:
    zipped = Network.from_source(leavenworth.zip_path(), engine=IbisEngine())
    on_disk = Network.from_source(leavenworth.csv_dir(), engine=IbisEngine())
    assert set(zipped.keys()) == set(on_disk.keys())
    assert zipped.links.count() == on_disk.links.count()
    assert zipped.nodes.count() == on_disk.nodes.count()


def test_fixture_load_zip() -> None:
    assert leavenworth.load("zip").links.count() == leavenworth.load("csv").links.count()


def test_write_zip_roundtrip_from_parquet(tmp_path) -> None:
    src = Network.from_source(leavenworth.parquet_dir(), engine=IbisEngine())
    dest = tmp_path / "x.zip"
    src.write(dest, format="zip")

    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        assert "datapackage.json" in names
        assert {f"{t}.csv" for t in src} <= names
        # CSV containers carry WKT text (geometry ADR), not WKB bytes.
        first_row = zf.read("geometry.csv").decode().splitlines()[1]
        assert "LINESTRING" in first_row
        json.loads(zf.read("datapackage.json"))

    back = Network.from_source(dest, engine=IbisEngine())
    assert set(back.keys()) == set(src.keys())
    for name in src:
        assert back[name].count() == src[name].count(), name
    # In memory both sides are canonical WKB.
    original, reopened = _link_geometry(src), _link_geometry(back)
    assert all(isinstance(g, bytes) for g in reopened)
    assert reopened == original
    # The source network's in-memory geometry stays WKB after writing.
    assert all(isinstance(g, bytes) for g in _link_geometry(src))


def test_cli_build_format_zip(tmp_path, monkeypatch) -> None:
    pytest.importorskip("netstead.osm")

    def _fake_build(*_args, **_kwargs):
        return Network.from_source(leavenworth.csv_dir(), engine=IbisEngine(), tables=["link", "node"])

    monkeypatch.setattr("netstead.osm.build_network_from_osm", _fake_build)
    dest = tmp_path / "leavenworth.zip"
    result = CliRunner().invoke(app, ["build", str(dest), "--bbox", "-120.7,47.5,-120.6,47.6", "--format", "zip"])
    assert result.exit_code == 0, result.output
    back = Network.from_source(dest, engine=IbisEngine())
    assert back.links.count() == leavenworth.load("csv").links.count()
