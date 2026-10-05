"""Unit tests for netstead.viz.tables — paged/sorted/filtered GMNS table access."""

from importlib import resources

import pandas as pd
import pyarrow as pa
import pytest
from corral.engines.ibis_engine import IbisEngine
from netstead.viz.tables import MAX_LIMIT, FilterError, page_table, primary_key, table_schema


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "link_id": [1, 2, 3, 4],
            "lanes": [2, 4, 4, None],
            "facility_type": ["motorway", "primary", "motorway", "service"],
            "name": ["I 40", "Page Road", "I 40", None],
            "geometry": ["LINESTRING(0 0,1 1)"] * 4,
        }
    )


def test_primary_key_prefers_table_name():
    assert primary_key("link", ["link_id", "from_node_id"]) == "link_id"
    assert primary_key("segment", ["from_node_id", "x"]) == "from_node_id"  # first *_id fallback
    assert primary_key("zone", ["a", "b"]) is None


def test_schema_classifies_kinds(df):
    kinds = {c["name"]: c["kind"] for c in table_schema("link", df)["columns"]}
    assert kinds["lanes"] == "num" and kinds["facility_type"] == "str" and kinds["geometry"] == "geom"


def test_page_excludes_geometry_and_pages(df):
    p = page_table(df, offset=1, limit=2)
    assert "geometry" not in p["columns"]
    assert len(p["rows"]) == 2 and p["total"] == 4 and p["offset"] == 1


def test_sort_desc(df):
    p = page_table(df, sort="link_id", direction="desc")
    assert [r[p["columns"].index("link_id")] for r in p["rows"]] == [4, 3, 2, 1]


def test_filter_eq_and_gte(df):
    p = page_table(
        df,
        filter_spec=[{"col": "facility_type", "op": "eq", "val": "motorway"}, {"col": "lanes", "op": "gte", "val": 3}],
    )
    assert p["total"] == 1 and p["rows"][0][p["columns"].index("link_id")] == 3


def test_filter_contains_and_isnull(df):
    assert page_table(df, filter_spec=[{"col": "name", "op": "contains", "val": "page"}])["total"] == 1
    assert page_table(df, filter_spec=[{"col": "name", "op": "notnull"}])["total"] == 3


def test_filter_in(df):
    p = page_table(df, filter_spec=[{"col": "link_id", "op": "in", "val": [1, 3]}])
    assert p["total"] == 2


def test_ids_crossfilter(df):
    assert page_table(df, ids=[2, 4], pk="link_id")["total"] == 2


def test_unknown_column_and_op_raise(df):
    with pytest.raises(FilterError):
        page_table(df, filter_spec=[{"col": "nope", "op": "eq", "val": 1}])
    with pytest.raises(FilterError):
        page_table(df, filter_spec=[{"col": "lanes", "op": "bogus", "val": 1}])
    with pytest.raises(FilterError):
        page_table(df, sort="nope")


def test_limit_clamped(df):
    assert page_table(df, limit=99999)["limit"] == MAX_LIMIT


def test_null_scalars_serialize(df):
    p = page_table(df, sort="link_id")
    assert p["rows"][3][p["columns"].index("lanes")] is None  # NaN -> None, JSON-safe


# --- lazy corral Table path (G1): engine push-down, pandas-parity ---


def _ibis_link_table():
    """A lazy corral Table over the fixture links, on the ibis/duckdb engine."""
    from corral.dataset import Table

    base = resources.files("netstead.fixtures.rdu_i40").joinpath("parquet")
    df = pd.read_parquet(base.joinpath("link.parquet"))
    e = IbisEngine()
    return Table(name="link", expr=e.from_arrow(pa.Table.from_pandas(df, preserve_index=False)), engine=e), df


def test_page_table_lazy_matches_pandas():
    t, df = _ibis_link_table()
    spec = [{"col": "facility_type", "op": "eq", "val": "motorway"}]
    lazy = page_table(t, limit=5, sort="lanes", direction="desc", filter_spec=spec)
    eager = page_table(df, limit=5, sort="lanes", direction="desc", filter_spec=spec)
    assert lazy["total"] == eager["total"] > 0
    assert "geometry" not in lazy["columns"]  # WKT dropped before materialising
    li = lazy["columns"].index("lanes")
    lv = [r[li] for r in lazy["rows"] if r[li] is not None]
    assert lv == sorted(lv, reverse=True)


def test_page_table_lazy_ids_crossfilter():
    t, df = _ibis_link_table()
    ids = [int(i) for i in df["link_id"].iloc[:3]]
    assert page_table(t, ids=ids, pk="link_id", limit=500)["total"] == 3


def test_page_table_lazy_bad_filter_raises():
    t, _ = _ibis_link_table()
    with pytest.raises(FilterError):
        page_table(t, filter_spec=[{"col": "nonsuch", "op": "eq", "val": 1}])


def test_table_schema_on_lazy_table():
    t, _ = _ibis_link_table()
    sch = table_schema("link", t)
    kinds = {c["name"]: c["kind"] for c in sch["columns"]}
    assert kinds["lanes"] == "num" and kinds["facility_type"] == "str"
    assert sch["primary_key"] == "link_id" and sch["rows"] > 50
