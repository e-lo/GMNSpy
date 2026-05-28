"""The generated network ships a GMNS ``config`` table declaring its units.

GMNS is unit-agnostic — units are declared per-dataset in the optional ``config``
table — so the builder emits one to make the network self-describing.
"""

from __future__ import annotations

from datagrove.engines.pandas_engine import PandasEngine
from gmnspy.osm import build

_NODE_RECS = [
    {"node_id": 1, "x_coord": -71.0, "y_coord": 42.0},
    {"node_id": 2, "x_coord": -71.0, "y_coord": 42.001},
]
_LINK_RECS = [
    {
        "link_id": 1,
        "from_node_id": 1,
        "to_node_id": 2,
        "directed": True,
        "length": 111.2,
        "free_speed": 25.0,
        "lanes": 2,
        "facility_type": "residential",
        "name": "Main St",
        "geometry": "LINESTRING (-71.0 42.0, -71.0 42.001)",
        "osm_way_id": 100,
        "osm_node_ids": "1,2",
    },
]


def test_config_table_declares_units():
    net = build.network_from_records(_NODE_RECS, _LINK_RECS, engine=PandasEngine())
    assert net.config is not None
    cfg = net.config.to_pandas().iloc[0]
    assert cfg["speed"] == "mph"
    assert cfg["long_length"] == "meter"
    assert cfg["geometry_field_format"] == "WKT"
    assert cfg["crs"] == "EPSG:4326"


def test_config_does_not_break_validation():
    net = build.network_from_records(_NODE_RECS, _LINK_RECS, engine=PandasEngine())
    errors = [i for i in net.validate().issues if i.severity.value == "error"]
    assert errors == [], errors
