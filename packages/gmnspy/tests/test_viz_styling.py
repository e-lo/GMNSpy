"""Tests for gmnspy.viz.styling (shared by viz and the workbench)."""

import pandas as pd
from gmnspy.viz.styling import basemap_style, json_scalar, property_payload, styleable_columns
from gmnspy.viz.tables import parse_ids


def test_styleable_columns_classifies_and_skips_ids():
    links = pd.DataFrame({"link_id": [1, 2], "lanes": [1, 2], "facility_type": ["a", "b"], "geometry": ["x", "y"]})
    assert styleable_columns(links) == [
        {"name": "lanes", "kind": "continuous"},
        {"name": "facility_type", "kind": "categorical"},
    ]


def test_property_payload_continuous_and_unknown():
    links = pd.DataFrame({"lanes": [1, None, 3]})
    p = property_payload(links, "lanes")
    assert p["kind"] == "continuous" and p["values"][1] is None and (p["min"], p["max"]) == (1, 3)
    assert property_payload(links, "nope") is None


def test_json_scalar_handles_nan_and_numpy():
    assert json_scalar(float("nan")) is None
    assert json_scalar(pd.Series([7]).iloc[0]) == 7
    assert type(json_scalar(pd.Series([7]).iloc[0])) is int


def test_basemap_style_is_keyless():
    assert "openfreemap" in basemap_style("positron")
    assert "arcgisonline.com" in basemap_style("esri")["sources"]["basemap"]["tiles"][0]


def test_parse_ids():
    assert parse_ids("1, 2,x,") == [1, 2, "x"]
    assert parse_ids("") is None and parse_ids(None) is None
