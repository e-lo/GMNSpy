"""Format-interop contract: pandas / polars / pyarrow are I/O formats; DuckDB computes.

This pins the behavior the engine consolidation (Option B) must preserve: a caller
hands data in as pandas / polars / Arrow, computation happens in DuckDB, and results
come back in the requested format with the cross-engine **nullable dtype** contract
(`Int64` / `Float64` / `string` / `boolean`). It replaces the cross-*compute*-engine
parity suite with an input/output-format guarantee on the one compute engine.
"""

from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pytest
from corral.dataset import Table
from corral.engines.ibis_engine import IbisEngine


def _table(expr, engine) -> Table:
    return Table(name="t", expr=expr, engine=engine)


def test_arrow_in_duckdb_compute_pandas_out_nullable_dtypes():
    e = IbisEngine()
    at = pa.table({"a": pa.array([1, 2, 3, None], type=pa.int64()), "b": ["x", "y", "z", None]})
    t = _table(e.from_arrow(at), e)
    # compute happens in duckdb (ibis predicate), not in pandas
    kept = t.filter(lambda x: x.filter(x.a >= 2)).to_pandas()
    assert kept["a"].tolist() == [2, 3]  # NULL row excluded by >= 2
    # output-converter contract: nullable int, not float64-with-NaN
    full = t.to_pandas()
    assert str(full["a"].dtype) == "Int64"
    assert str(full["b"].dtype) == "string"


def test_pandas_in_pandas_out():
    e = IbisEngine()
    df = pd.DataFrame({"a": [3, 1, 2], "ft": ["m", "p", "m"]})
    t = _table(e.from_arrow(pa.Table.from_pandas(df, preserve_index=False)), e)
    out = t.order_by("a").to_pandas()
    assert out["a"].tolist() == [1, 2, 3]


def test_polars_in_polars_out():
    pl = pytest.importorskip("polars")
    e = IbisEngine()
    pdf = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    t = _table(e.from_arrow(pdf.to_arrow()), e)
    out = t.to_polars()
    assert isinstance(out, pl.DataFrame)
    assert out["a"].to_list() == [1, 2, 3]


def test_arrow_out_round_trip():
    # Arrow is the interchange format in/out. (A first-class Table.to_arrow() is a
    # candidate addition during consolidation; today arrow-out goes via collect().)
    e = IbisEngine()
    at = pa.table({"a": [1, 2, 3]})
    out = _table(e.from_arrow(at), e).collect().to_pyarrow()
    assert out.column("a").to_pylist() == [1, 2, 3]


def test_compute_identical_regardless_of_input_format():
    e = IbisEngine()
    rows = {"a": [3, 1, 2], "ft": ["m", "p", "m"]}
    from_records = _table(e.from_records(rows), e)
    from_arrow = _table(e.from_arrow(pa.table(rows)), e)

    def q(t: Table):
        return t.filter(lambda x: x.filter(x.ft == "m")).order_by("a").to_pandas()["a"].tolist()

    assert q(from_records) == q(from_arrow) == [2, 3]
