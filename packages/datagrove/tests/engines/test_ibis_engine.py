"""Behavioural tests for the IbisEngine (task 1.3).

Covers: default backend construction, scan() across csv/parquet/duckdb,
schema-driven type coercion, format override, materialize stability,
to_pandas / to_polars converters, write() round-trips, error messages
that point at the deferred-adapter tasks, and registry/protocol wiring.
"""

from __future__ import annotations

import re
from pathlib import Path

import ibis
import pytest
from datagrove.engines import Engine, get_engine
from datagrove.engines.base import EngineNotAvailableError
from datagrove.engines.ibis_engine import IbisEngine
from datagrove.spec.loader import load_schema
from gmnspy.fixtures import leavenworth

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> IbisEngine:
    """Fresh engine with a private in-memory duckdb connection."""
    e = IbisEngine()
    yield e
    e.close()


@pytest.fixture
def link_csv() -> Path:
    return leavenworth.csv_dir() / "link.csv"


@pytest.fixture
def link_parquet() -> Path:
    return leavenworth.parquet_dir() / "link.parquet"


@pytest.fixture
def duckdb_path() -> Path:
    return leavenworth.duckdb_path()


@pytest.fixture
def link_schema():
    """Frictionless schema for the GMNS link table.

    We load it from the vendored 0.97 spec so the test honours the same
    schema the production code does. ``shared_categories`` is mandatory
    because several link fields reference enum payloads via ``$ref``.
    """
    spec_root = Path(leavenworth.__file__).parent.parent.parent / "spec" / "0.97"
    import json

    shared = json.loads((spec_root / "shared_categories.json").read_text())
    return load_schema(spec_root / "link.schema.json", shared_categories=shared)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_creates_default_in_memory_connection():
    e = IbisEngine()
    try:
        assert e.con is not None
        assert e.name == "ibis"
    finally:
        e.close()


def test_accepts_existing_backend():
    """A caller can pass in their own backend; engine doesn't disconnect it."""
    con = ibis.duckdb.connect(":memory:")
    e = IbisEngine(con=con)
    try:
        assert e.con is con
    finally:
        e.close()
    # The engine should not have disconnected a backend it didn't own.
    # We can still list_tables() on it (empty, but the call succeeds).
    assert con.list_tables() == []
    con.disconnect()


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


def test_scan_csv_returns_ibis_table(engine: IbisEngine, link_csv: Path):
    t = engine.scan(link_csv)
    assert isinstance(t, ibis.expr.types.Table)
    assert t.count().to_pyarrow().as_py() == 214


def test_scan_parquet_returns_ibis_table(engine: IbisEngine, link_parquet: Path):
    t = engine.scan(link_parquet)
    assert isinstance(t, ibis.expr.types.Table)
    assert t.count().to_pyarrow().as_py() == 214


def test_scan_duckdb_with_explicit_table(engine: IbisEngine, duckdb_path: Path):
    t = engine.scan(duckdb_path, table="link")
    assert isinstance(t, ibis.expr.types.Table)
    assert t.count().to_pyarrow().as_py() == 214


def test_scan_duckdb_dict_handle(engine: IbisEngine, duckdb_path: Path):
    t = engine.scan({"path": str(duckdb_path), "table": "node"})
    assert isinstance(t, ibis.expr.types.Table)
    assert "node_id" in t.columns


def test_scan_duckdb_without_table_kwarg_raises(engine: IbisEngine, duckdb_path: Path):
    # Post-#134: the duckdb adapter owns this validation. The message
    # still mentions the 'table=' kwarg so the caller can fix the call;
    # the exception is still a ValueError subclass (InvalidEngineCallError).
    with pytest.raises(ValueError, match=re.escape("table=")):
        engine.scan(duckdb_path)


def test_scan_with_format_override_csv(engine: IbisEngine, link_csv: Path):
    """An explicit format= still works when the extension already matches."""
    t = engine.scan(link_csv, format="csv")
    assert t.count().to_pyarrow().as_py() == 214


def test_scan_with_format_override_parquet(engine: IbisEngine, link_parquet: Path):
    t = engine.scan(link_parquet, format="parquet")
    assert t.count().to_pyarrow().as_py() == 214


def test_scan_with_schema_casts_types(engine: IbisEngine, link_csv: Path, link_schema):
    t = engine.scan(link_csv, schema=link_schema)
    s = t.schema()
    # GMNS link.from_node_id / to_node_id are Frictionless "integer".
    assert "int" in str(s["from_node_id"]).lower()
    assert "int" in str(s["to_node_id"]).lower()
    # length is "number" → float
    assert "float" in str(s["length"]).lower()
    # directed is "boolean"
    assert str(s["directed"]).lower() == "boolean"


def test_unsupported_format_raises_helpful_error(engine: IbisEngine):
    """Post-#134: dispatch via the FormatAdapter registry raises FormatNotDetected.

    Before the inversion the engine's own ``_resolve_kind`` raised
    ``NotImplementedError`` for unknown extensions. After the
    inversion the engine delegates to ``datagrove.io.dispatch``, which
    raises :class:`~datagrove.io.FormatNotDetected` (the registry's
    own structured exception) with the list of registered adapters
    so the caller can see what *is* available.
    """
    from datagrove.io import FormatNotDetected

    with pytest.raises(FormatNotDetected) as exc:
        engine.scan("foo.xlsx")
    msg = str(exc.value)
    # Lists what the registry knows about so the caller can correct
    # the call.
    assert "Registered adapters" in msg or "registered" in msg.lower()


def test_explicit_unsupported_format_raises(engine: IbisEngine):
    """Post-#134: an unknown explicit format= raises AdapterNotAvailableError."""
    from datagrove.io import AdapterNotAvailableError

    with pytest.raises(AdapterNotAvailableError) as exc:
        engine.scan("anything", format="excel")
    assert "excel" in str(exc.value)


# ---------------------------------------------------------------------------
# from_records / from_arrow — all-null column regression
# ---------------------------------------------------------------------------


def test_from_records_with_all_null_column_does_not_raise(engine: IbisEngine):
    """Regression: duckdb rejects ``CREATE TABLE`` with NULL-typed columns.

    Repro of the issue surfacing via ``gmnspy.scope.from_node(...).apply()``
    on the bundled Leavenworth fixture where ``link.name`` is entirely
    null. pyarrow infers ``pa.null()`` for such columns; duckdb raises
    ``IbisTypeError: DuckDB does not support creating tables with NULL
    typed columns``. ``IbisEngine.from_records`` now coerces all-null
    columns to ``string`` before the duckdb write — see
    ``_coerce_all_null_columns_to_string``.
    """
    expr = engine.from_records(
        [
            {"id": 1, "name": None},
            {"id": 2, "name": None},
        ]
    )
    df = engine.to_pandas(expr)
    assert len(df) == 2
    assert set(df.columns) == {"id", "name"}
    # The ``name`` column is castable to string after coercion — every
    # value still reads back as None / NA, just with a usable dtype.
    assert df["name"].isna().all()


def test_from_arrow_with_all_null_column_does_not_raise(engine: IbisEngine):
    """``from_arrow`` shares the same coercion — verify in parity with from_records."""
    import pyarrow as pa

    arrow = pa.Table.from_pylist([{"id": 1, "name": None}, {"id": 2, "name": None}])
    # Sanity-check the precondition the coercion fixes.
    assert pa.types.is_null(arrow.schema.field("name").type)
    expr = engine.from_arrow(arrow)
    df = engine.to_pandas(expr)
    assert len(df) == 2
    assert df["name"].isna().all()


# ---------------------------------------------------------------------------
# materialize / converters
# ---------------------------------------------------------------------------


def test_to_pandas_returns_pandas_dataframe(engine: IbisEngine, link_csv: Path):
    import pandas as pd

    df = engine.to_pandas(engine.scan(link_csv))
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 214


def test_to_polars_returns_polars_dataframe(engine: IbisEngine, link_csv: Path):
    pl = pytest.importorskip("polars")
    df = engine.to_polars(engine.scan(link_csv))
    assert isinstance(df, pl.DataFrame)
    assert len(df) == 214


def test_to_polars_without_polars_raises_engine_not_available(engine: IbisEngine, link_csv: Path, monkeypatch):
    """Parity with PandasEngine: missing polars must raise EngineNotAvailableError.

    Per ``Engine`` protocol §9 ("structured exceptions"), the right
    failure mode for "an optional engine extra isn't installed" is the
    structured ``EngineNotAvailableError`` — not bare ``ImportError``.
    """
    scan = engine.scan(link_csv)

    def _raise(*_a, **_kw):
        raise ImportError("simulated polars missing")

    monkeypatch.setattr(type(scan), "to_polars", _raise)
    with pytest.raises(EngineNotAvailableError, match="polars"):
        engine.to_polars(scan)


def test_materialize_makes_values_stable(engine: IbisEngine, link_csv: Path):
    """Materialize twice and confirm both materializations agree on rows."""
    scan = engine.scan(link_csv)
    mat1 = engine.materialize(scan)
    mat2 = engine.materialize(scan)
    df1 = engine.to_pandas(mat1).sort_values("link_id").reset_index(drop=True)
    df2 = engine.to_pandas(mat2).sort_values("link_id").reset_index(drop=True)
    assert df1.equals(df2)
    assert len(df1) == 214


def test_materialize_returns_ibis_table(engine: IbisEngine, link_csv: Path):
    mat = engine.materialize(engine.scan(link_csv))
    assert isinstance(mat, ibis.expr.types.Table)


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


def test_write_csv_roundtrip(engine: IbisEngine, link_csv: Path, tmp_path: Path):
    out = tmp_path / "link_out.csv"
    engine.write(engine.scan(link_csv), out, "csv")
    assert out.exists()
    again = engine.scan(out)
    assert again.count().to_pyarrow().as_py() == 214


def test_write_parquet_roundtrip(engine: IbisEngine, link_csv: Path, tmp_path: Path):
    out = tmp_path / "link_out.parquet"
    engine.write(engine.scan(link_csv), out, "parquet")
    assert out.exists()
    again = engine.scan(out)
    assert again.count().to_pyarrow().as_py() == 214


def test_write_duckdb_roundtrip(engine: IbisEngine, link_csv: Path, tmp_path: Path):
    out = tmp_path / "out.duckdb"
    engine.write(engine.scan(link_csv), out, "duckdb", table="link")
    assert out.exists()
    again = engine.scan(out, table="link")
    assert again.count().to_pyarrow().as_py() == 214


def test_write_unsupported_format_raises(engine: IbisEngine, link_csv: Path, tmp_path: Path):
    """Post-#134: unknown write fmt raises AdapterNotAvailableError from the registry."""
    from datagrove.io import AdapterNotAvailableError

    with pytest.raises(AdapterNotAvailableError) as exc:
        engine.write(engine.scan(link_csv), tmp_path / "x.xlsx", "xlsx")
    assert "xlsx" in str(exc.value)


# ---------------------------------------------------------------------------
# Registry / protocol
# ---------------------------------------------------------------------------


def test_engine_is_default_in_registry():
    # Compare by class name + module rather than isinstance: pytest's
    # `--import-mode=importlib` can load this module under two paths when
    # the engine source file is collected for doctests AND the test file
    # imports IbisEngine — producing two distinct class objects that both
    # satisfy the user's mental model of "is an ibis engine".
    e = get_engine()
    assert e.name == "ibis"
    assert type(e).__name__ == "IbisEngine"
    assert type(e).__module__ == "datagrove.engines.ibis_engine"


def test_protocol_conformance():
    e = IbisEngine()
    try:
        assert isinstance(e, Engine)
    finally:
        e.close()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_close_is_idempotent():
    e = IbisEngine()
    e.close()
    e.close()  # second call must not raise
