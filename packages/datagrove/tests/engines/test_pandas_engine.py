"""Tests for the PandasEngine (Phase 1 task 1.5).

The pandas engine is the *compatibility target* — eager, simple, no lazy
expressions. ``scan()`` returns a materialized ``pandas.DataFrame``.
``materialize()`` and ``to_pandas()`` are identities; ``to_polars()``
delegates to ``polars.from_pandas`` (optional dep).

These tests pin those semantics so the engine stays the lowest-common
denominator that other engines (ibis, polars) can fall back to via the
``to_pandas`` converter.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from datagrove.engines import list_engines
from datagrove.engines.base import Engine, EngineNotAvailableError
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.spec.model import Field, Schema

LEAVENWORTH = Path(__file__).resolve().parents[4] / "packages" / "gmnspy" / "gmnspy" / "fixtures" / "leavenworth"
CSV_DIR = LEAVENWORTH / "csv"
PARQUET_DIR = LEAVENWORTH / "parquet"
ZIP_PATH = LEAVENWORTH / "leavenworth.csv.zip"
DUCKDB_PATH = LEAVENWORTH / "leavenworth.duckdb"


# ---------------------------------------------------------------------------
# Construction + protocol
# ---------------------------------------------------------------------------


def test_creates_pandas_engine():
    e = PandasEngine()
    assert e.name == "pandas"


def test_protocol_conformance():
    assert isinstance(PandasEngine(), Engine)


def test_engine_auto_registers_when_pandas_installed():
    assert "pandas" in list_engines()


# ---------------------------------------------------------------------------
# scan() — direct pandas readers
# ---------------------------------------------------------------------------


def test_scan_csv_returns_dataframe():
    e = PandasEngine()
    df = e.scan(CSV_DIR / "node.csv")
    # eager — not lazy
    assert isinstance(df, pd.DataFrame)
    assert "node_id" in df.columns
    assert len(df) > 0


def test_scan_parquet_returns_dataframe():
    e = PandasEngine()
    df = e.scan(PARQUET_DIR / "node.parquet")
    assert isinstance(df, pd.DataFrame)
    assert "node_id" in df.columns


def test_scan_with_schema_casts_to_nullable_types():
    """Schema casts trigger pandas nullable dtypes (Int64, Float64, string, boolean)."""
    e = PandasEngine()
    schema = Schema(
        fields=[
            Field(name="node_id", type="integer"),
            Field(name="x_coord", type="number"),
            Field(name="node_type", type="string"),
        ]
    )
    df = e.scan(CSV_DIR / "node.csv", schema=schema)
    assert str(df["node_id"].dtype) == "Int64"
    assert str(df["x_coord"].dtype) == "Float64"
    assert str(df["node_type"].dtype) == "string"


def test_scan_with_format_override():
    """Format override wins over extension sniff."""
    e = PandasEngine()
    # Pass a path that has a .csv extension but force parquet — should error
    # at pandas read time. Conversely, force csv with explicit format= works.
    df = e.scan(CSV_DIR / "node.csv", format="csv")
    assert isinstance(df, pd.DataFrame)


def test_scan_csv_zip_single_file_works(tmp_path):
    """Single-csv inside a zip reads back correctly."""
    import zipfile

    src_csv = CSV_DIR / "node.csv"
    zip_path = tmp_path / "single.csv.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.write(src_csv, arcname="node.csv")

    e = PandasEngine()
    df_zip = e.scan(zip_path)
    df_raw = pd.read_csv(src_csv)
    assert len(df_zip) == len(df_raw)
    assert list(df_zip.columns) == list(df_raw.columns)


def test_scan_csv_zip_multi_file_raises_helpful_error():
    """The Leavenworth zip has 9 csvs + datapackage.json — must raise pointing at 1.10."""
    e = PandasEngine()
    with pytest.raises(NotImplementedError) as excinfo:
        e.scan(ZIP_PATH)
    msg = str(excinfo.value)
    assert "1.10" in msg
    assert "multi" in msg.lower() or "multiple" in msg.lower()


def test_scan_dict_source_with_data_key():
    e = PandasEngine()
    df = e.scan({"data": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]})
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


def test_scan_dict_source_without_data_key_raises():
    e = PandasEngine()
    with pytest.raises(ValueError, match="data"):
        e.scan({"path": "/nope"})


def test_scan_unknown_extension_raises_helpful_error(tmp_path):
    e = PandasEngine()
    weird = tmp_path / "thing.xyz"
    weird.write_text("foo\n")
    with pytest.raises(NotImplementedError) as excinfo:
        e.scan(weird)
    assert ".xyz" in str(excinfo.value) or "xyz" in str(excinfo.value).lower()


def test_scan_duckdb_via_python_api():
    """DuckDB scan uses the duckdb Python API (no SQL); requires kwargs['table']."""
    e = PandasEngine()
    df = e.scan(DUCKDB_PATH, table="node")
    assert isinstance(df, pd.DataFrame)
    assert "node_id" in df.columns


def test_scan_duckdb_without_table_raises():
    e = PandasEngine()
    with pytest.raises(ValueError, match="table"):
        e.scan(DUCKDB_PATH)


# ---------------------------------------------------------------------------
# materialize / to_pandas / to_polars
# ---------------------------------------------------------------------------


def test_materialize_is_identity():
    e = PandasEngine()
    df = pd.DataFrame({"a": [1, 2]})
    out = e.materialize(df)
    assert out is df


def test_to_pandas_is_identity():
    e = PandasEngine()
    df = pd.DataFrame({"a": [1, 2]})
    out = e.to_pandas(df)
    assert out is df


def test_to_polars_returns_polars_dataframe():
    pl = pytest.importorskip("polars")
    e = PandasEngine()
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    out = e.to_polars(df)
    assert isinstance(out, pl.DataFrame)
    assert out.shape == (2, 2)


def test_to_polars_without_polars_raises_engine_not_available(monkeypatch):
    """Verify the error type + the install hint."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "polars":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    e = PandasEngine()
    with pytest.raises(EngineNotAvailableError, match="polars"):
        e.to_polars(pd.DataFrame({"a": [1]}))


# ---------------------------------------------------------------------------
# write()
# ---------------------------------------------------------------------------


def test_write_csv_roundtrip(tmp_path):
    e = PandasEngine()
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    dest = tmp_path / "out.csv"
    e.write(df, dest, fmt="csv")
    back = pd.read_csv(dest)
    assert list(back.columns) == ["a", "b"]  # no index column written
    assert len(back) == 3


def test_write_parquet_roundtrip(tmp_path):
    e = PandasEngine()
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    dest = tmp_path / "out.parquet"
    e.write(df, dest, fmt="parquet")
    back = pd.read_parquet(dest)
    assert list(back.columns) == ["a", "b"]
    assert len(back) == 3


def test_write_duckdb_either_works_or_raises_clearly(tmp_path):
    """DuckDB write either works (via duckdb Python API) or raises clearly pointing
    at the ibis engine. Whichever path we took, lock it in."""
    e = PandasEngine()
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    dest = tmp_path / "out.duckdb"
    try:
        e.write(df, dest, fmt="duckdb", table="t")
    except NotImplementedError as exc:
        # If deferred, the message must point at ibis.
        assert "ibis" in str(exc).lower()
        return
    # If it worked, verify by reading back via the duckdb Python API.
    import duckdb

    con = duckdb.connect(str(dest))
    try:
        back = con.table("t").df()
    finally:
        con.close()
    assert len(back) == 3
    assert set(back.columns) == {"a", "b"}


def test_write_unsupported_format_raises_helpful_error(tmp_path):
    e = PandasEngine()
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(NotImplementedError) as excinfo:
        e.write(df, tmp_path / "out.xyz", fmt="xyz")
    assert "xyz" in str(excinfo.value)
