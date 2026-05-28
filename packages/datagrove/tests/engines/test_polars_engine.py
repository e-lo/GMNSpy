"""Tests for PolarsEngine — Phase 1 task 1.4 (issue #51).

Engine contract:
    - ``scan`` returns a ``polars.LazyFrame`` (unmaterialized).
    - ``materialize``/``to_polars`` collect the LazyFrame.
    - ``to_pandas`` round-trips via Arrow.
    - ``write`` persists csv/parquet; duckdb writes are deferred to
      ``IbisEngine`` (raised with a helpful pointer) so this module
      stays SQL-free.

The Leavenworth fixture (csv + parquet) is the test data; we never
embed test data inline so the fixture's evolution is the single source
of truth for representative GMNS shapes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("polars", reason="polars optional extra not installed")

import polars as pl
from datagrove.engines import Engine, list_engines
from datagrove.engines.polars_engine import PolarsEngine
from datagrove.spec.model import Field, Schema

# ---------------------------------------------------------------------------
# Fixture paths — small Leavenworth GMNS network shipped in gmnspy
# ---------------------------------------------------------------------------

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "gmnspy" / "gmnspy" / "fixtures" / "leavenworth"
LINK_CSV = FIXTURE_ROOT / "csv" / "link.csv"
LINK_PARQUET = FIXTURE_ROOT / "parquet" / "link.parquet"


# ---------------------------------------------------------------------------
# Engine instantiation + protocol conformance
# ---------------------------------------------------------------------------


def test_creates_polars_engine():
    engine = PolarsEngine()
    assert engine.name == "polars"


def test_from_records_handles_null_prefix_then_value():
    """from_records must not infer a Null column from an all-null prefix.

    Regression: a column null for the first >100 rows then carrying a value
    (common for optional fields) used to infer as Null and raise ComputeError
    on append. from_records now scans all rows for inference.
    """
    records = [{"a": i, "b": None} for i in range(120)] + [{"a": 120, "b": 30.0}]
    lf = PolarsEngine().from_records(records)
    df = lf.collect()
    assert df.height == 121
    assert df["b"].sum() == 30.0


def test_protocol_conformance():
    assert isinstance(PolarsEngine(), Engine)


def test_engine_auto_registers_when_polars_installed():
    # The engines/__init__.py auto-registration block imports polars and
    # registers PolarsEngine() iff polars is importable. Since this test
    # file is gated on `pytest.importorskip("polars")`, polars IS
    # installed here, so the engine MUST be in the registry.
    assert "polars" in list_engines()


# ---------------------------------------------------------------------------
# scan() — returns LazyFrame (the key Lens-A contract)
# ---------------------------------------------------------------------------


def test_scan_csv_returns_lazyframe():
    engine = PolarsEngine()
    result = engine.scan(LINK_CSV)
    # LazyFrame, NOT DataFrame — lazy by default is the engine's contract.
    assert isinstance(result, pl.LazyFrame), f"expected pl.LazyFrame (lazy by default), got {type(result).__name__}"


def test_scan_parquet_returns_lazyframe():
    engine = PolarsEngine()
    result = engine.scan(LINK_PARQUET)
    assert isinstance(result, pl.LazyFrame)


def test_scan_with_format_override():
    # Pass a csv path with format="csv" explicit — must still resolve to
    # the csv reader (and not, e.g., parquet because of some mis-sniff).
    engine = PolarsEngine()
    result = engine.scan(LINK_CSV, format="csv")
    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.height > 0


def test_scan_str_path_works():
    # SourceRef accepts str | Path; both arms must work.
    engine = PolarsEngine()
    result = engine.scan(str(LINK_CSV))
    assert isinstance(result, pl.LazyFrame)


def test_scan_with_schema_casts_types():
    # Cast a string-by-default column to an integer per the schema.
    # link_id is integer in GMNS; verify the cast lands.
    schema = Schema(
        fields=[
            Field(name="link_id", type="integer"),
            Field(name="from_node_id", type="integer"),
            Field(name="to_node_id", type="integer"),
        ]
    )
    engine = PolarsEngine()
    result = engine.scan(LINK_CSV, schema=schema)
    df = result.collect()
    # All three should be Int64 after the cast applies.
    assert df.schema["link_id"] == pl.Int64
    assert df.schema["from_node_id"] == pl.Int64
    assert df.schema["to_node_id"] == pl.Int64


# ---------------------------------------------------------------------------
# Materialization + cross-engine converters
# ---------------------------------------------------------------------------


def test_materialize_returns_dataframe():
    engine = PolarsEngine()
    lazy = engine.scan(LINK_CSV)
    df = engine.materialize(lazy)
    assert isinstance(df, pl.DataFrame)
    assert df.height > 0


def test_to_polars_collects_lazy_frame():
    engine = PolarsEngine()
    lazy = engine.scan(LINK_CSV)
    df = engine.to_polars(lazy)
    assert isinstance(df, pl.DataFrame)


def test_to_pandas_returns_pandas_dataframe():
    pd = pytest.importorskip("pandas")
    engine = PolarsEngine()
    lazy = engine.scan(LINK_CSV)
    pdf = engine.to_pandas(lazy)
    assert isinstance(pdf, pd.DataFrame)
    # Row count matches the polars side.
    assert len(pdf) == lazy.collect().height
    # Columns line up.
    assert list(pdf.columns) == lazy.collect().columns


# ---------------------------------------------------------------------------
# write() — csv / parquet roundtrips; duckdb is deferred
# ---------------------------------------------------------------------------


def test_write_csv_roundtrip(tmp_path):
    engine = PolarsEngine()
    lazy = engine.scan(LINK_CSV)
    out = tmp_path / "link_out.csv"
    engine.write(lazy, out, fmt="csv")
    assert out.exists()
    re_read = engine.scan(out).collect()
    original = lazy.collect()
    assert re_read.height == original.height
    assert re_read.columns == original.columns


def test_write_parquet_roundtrip(tmp_path):
    engine = PolarsEngine()
    lazy = engine.scan(LINK_PARQUET)
    out = tmp_path / "link_out.parquet"
    engine.write(lazy, out, fmt="parquet")
    assert out.exists()
    re_read = engine.scan(out).collect()
    original = lazy.collect()
    assert re_read.height == original.height
    assert re_read.columns == original.columns


def test_write_duckdb_raises_helpful_error(tmp_path):
    """Post-#134: polars defers duckdb writes to IbisEngine via the engine primitive.

    The engine's :meth:`PolarsEngine.write_duckdb_table` raises
    :class:`~datagrove.engines.errors.EngineNotAvailableError` (the
    structurally-cannot-do-it exception, not the not-yet-implemented
    one). The adapter forwards the failure unchanged.
    """
    from datagrove.engines.errors import EngineNotAvailableError

    engine = PolarsEngine()
    lazy = engine.scan(LINK_CSV)
    with pytest.raises(EngineNotAvailableError) as exc:
        engine.write(lazy, tmp_path / "out.duckdb", fmt="duckdb", table="link")
    msg = str(exc.value)
    # Must point users at IbisEngine for the duckdb write path.
    assert "IbisEngine" in msg or "ibis" in msg


def test_write_unsupported_format_raises_helpful_error(tmp_path):
    """Post-#134: unknown fmt raises AdapterNotAvailableError from the registry."""
    from datagrove.io import AdapterNotAvailableError

    engine = PolarsEngine()
    lazy = engine.scan(LINK_CSV)
    with pytest.raises(AdapterNotAvailableError) as exc:
        engine.write(lazy, tmp_path / "out.xlsx", fmt="xlsx")
    # Mentions the offending format so the caller knows what failed.
    assert "xlsx" in str(exc.value)


# ---------------------------------------------------------------------------
# scan() error paths — clear hints to the relevant follow-up tasks
# ---------------------------------------------------------------------------


def test_scan_zip_raises_when_zip_invalid(tmp_path):
    """Post-#134: scan(.csv.zip) goes through ZipCsvAdapter.

    An invalid (or empty) zip surfaces zipfile's own error when the
    adapter tries to open it. A valid-but-table-less call raises the
    adapter's structured InvalidEngineCallError, asking for a table=.
    """
    import zipfile

    engine = PolarsEngine()
    fake_zip = tmp_path / "links.csv.zip"
    fake_zip.write_bytes(b"\x00")  # invalid zip body
    with pytest.raises((zipfile.BadZipFile, OSError)):
        engine.scan(fake_zip)


def test_scan_unsupported_format_raises_helpful_error(tmp_path):
    """Post-#134: unknown extension raises FormatNotDetected from dispatch."""
    from datagrove.io import FormatNotDetected

    engine = PolarsEngine()
    weird = tmp_path / "data.unknownfmt"
    weird.write_bytes(b"")
    with pytest.raises(FormatNotDetected) as exc:
        engine.scan(weird)
    msg = str(exc.value)
    assert "data.unknownfmt" in msg or "Registered adapters" in msg


# ---------------------------------------------------------------------------
# Defensive: lint_no_sql.py should also catch this, but a unit test gives
# us a fast local signal that doesn't require running the lint script.
# ---------------------------------------------------------------------------


def test_no_raw_sql_in_module():
    import re

    from datagrove.engines import polars_engine

    src = Path(polars_engine.__file__).read_text(encoding="utf-8")
    # Same conservative patterns as scripts/lint_no_sql.py, abridged.
    patterns = [
        r"\bSELECT\b[\s\S]{0,200}?\bFROM\b",
        r"\bINSERT\s+INTO\s+\w",
        r"\bCREATE\s+TABLE\b",
        r"\bDROP\s+TABLE\b",
    ]
    for pat in patterns:
        # Exclude this very test's matching by searching only the engine source.
        assert not re.search(pat, src), f"raw SQL detected in polars_engine.py: pattern {pat}"
