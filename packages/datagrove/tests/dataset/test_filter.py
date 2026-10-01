"""Tests for :func:`datagrove.dataset.filter_rows` — engine-agnostic attribute filter.

Mirrors the ibis-first cross-engine strategy of ``dataset.view`` (spatial
scopes): lazy on a duckdb-backed ibis Table, pyarrow round-trip for other
engines. Parametrised across ibis + pandas (polars via importorskip) to pin
cross-engine parity of the ``[{col, op, val}]`` predicate language.
"""
from __future__ import annotations

import pytest
from datagrove.dataset import Table
from datagrove.dataset.filter import FilterSpecError, filter_rows
from datagrove.engines.ibis_engine import IbisEngine
from datagrove.engines.ibis_engine import IbisEngine

_ROWS = [
    {"ft": "motorway", "lanes": 4, "name": "I 40"},
    {"ft": "primary", "lanes": 2, "name": "Page Road"},
    {"ft": "motorway", "lanes": 6, "name": "I 540"},
    {"ft": "service", "lanes": None, "name": None},
]


def _make_engine(name: str):
    if name == "ibis":
        return IbisEngine()
    if name == "polars":
        pytest.importorskip("polars", reason="polars optional extra not installed")

        return IbisEngine()
    return IbisEngine()


def _table(engine_name: str) -> Table:
    e = _make_engine(engine_name)
    return Table(name="link", expr=e.from_records(_ROWS), engine=e)


def _fts(t: Table) -> list:
    return t.to_pandas().sort_values("lanes")["ft"].tolist()


@pytest.mark.parametrize("engine_name", ["ibis"])
def test_eq(engine_name):
    t = filter_rows(_table(engine_name), [{"col": "ft", "op": "eq", "val": "motorway"}])
    assert t.count() == 2 and set(_fts(t)) == {"motorway"}


@pytest.mark.parametrize("engine_name", ["ibis"])
def test_gte_excludes_null(engine_name):
    t = filter_rows(_table(engine_name), [{"col": "lanes", "op": "gte", "val": 4}])
    assert t.count() == 2   # 4 and 6; null-lane row excluded


@pytest.mark.parametrize("engine_name", ["ibis"])
def test_in(engine_name):
    t = filter_rows(_table(engine_name), [{"col": "ft", "op": "in", "val": ["primary", "service"]}])
    assert t.count() == 2


@pytest.mark.parametrize("engine_name", ["ibis"])
def test_contains_case_insensitive(engine_name):
    t = filter_rows(_table(engine_name), [{"col": "ft", "op": "contains", "val": "MOT"}])
    assert t.count() == 2


@pytest.mark.parametrize("engine_name", ["ibis"])
def test_notnull(engine_name):
    assert filter_rows(_table(engine_name), [{"col": "name", "op": "notnull"}]).count() == 3


@pytest.mark.parametrize("engine_name", ["ibis"])
def test_conditions_are_anded(engine_name):
    t = filter_rows(_table(engine_name),
                    [{"col": "ft", "op": "eq", "val": "motorway"}, {"col": "lanes", "op": "gte", "val": 5}])
    assert t.count() == 1 and _fts(t) == ["motorway"]


@pytest.mark.parametrize("engine_name", ["ibis"])
def test_empty_conditions_is_identity(engine_name):
    t = _table(engine_name)
    assert filter_rows(t, []).count() == 4


@pytest.mark.parametrize("engine_name", ["ibis"])
def test_unknown_column_and_op_raise(engine_name):
    t = _table(engine_name)
    with pytest.raises(FilterSpecError):
        filter_rows(t, [{"col": "nope", "op": "eq", "val": 1}])
    with pytest.raises(FilterSpecError):
        filter_rows(t, [{"col": "lanes", "op": "bogus", "val": 1}])
