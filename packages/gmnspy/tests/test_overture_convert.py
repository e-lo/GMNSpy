"""Tests for gmnspy.overture.convert — pure segments+connectors -> GMNS records.

Connectors are passed as ``{connector_id: (lon, lat)}``; segments carry their
ordered ``connectors`` array, a WKT ``geometry``, and the raw Overture
properties the mapping reads.
"""

from __future__ import annotations

import pytest
from gmnspy.overture import convert

_CONNECTORS = {
    "a": (0.0, 0.0),
    "b": (0.0, 1.0),
    "c": (0.0, 2.0),
    "d": (1.0, 2.0),
}


def _segment(**overrides):
    base = {
        "id": "seg1",
        "class": "residential",
        "names": {"primary": "A St"},
        "geometry": "LINESTRING (0 0, 0 2)",
        "connectors": [{"connector_id": "a", "at": 0.0}, {"connector_id": "c", "at": 1.0}],
    }
    base.update(overrides)
    return base


class TestConnectorSplitting:
    def test_interior_connector_splits_segment(self):
        seg = _segment(
            geometry="LINESTRING (0 0, 0 1, 0 2)",
            connectors=[
                {"connector_id": "a", "at": 0.0},
                {"connector_id": "b", "at": 0.5},
                {"connector_id": "c", "at": 1.0},
            ],
        )
        node_recs, link_recs = convert.build_node_link_tables([seg], _CONNECTORS)
        kept = {n["overture_connector_id"] for n in node_recs}
        assert kept == {"a", "b", "c"}
        # two sub-segments (a-b, b-c), each two-way -> 4 directed links
        assert len(link_recs) == 4

    def test_sub_segment_geometry_snaps_to_connector_points(self):
        seg = _segment(
            geometry="LINESTRING (0 0, 0 1, 0 2)",
            connectors=[
                {"connector_id": "a", "at": 0.0},
                {"connector_id": "b", "at": 0.5},
                {"connector_id": "c", "at": 1.0},
            ],
        )
        _, link_recs = convert.build_node_link_tables([seg], _CONNECTORS)
        ab = next(r for r in link_recs if r["overture_connector_ids"] == "a,b")
        assert ab["geometry"] == "LINESTRING (0.0 0.0, 0.0 1.0)"


class TestDirectedExpansion:
    def test_two_way_emits_two_links(self):
        # default segment references connectors a, c -> minted node ids 1, 2
        _, link_recs = convert.build_node_link_tables([_segment()], _CONNECTORS)
        assert len(link_recs) == 2
        pairs = {(r["from_node_id"], r["to_node_id"]) for r in link_recs}
        assert pairs == {(1, 2), (2, 1)}
        assert all(r["directed"] is True for r in link_recs)

    def test_oneway_forward_emits_single_link(self):
        seg = _segment(access_restrictions=[{"access_type": "denied", "when": {"heading": "backward"}}])
        _, link_recs = convert.build_node_link_tables([seg], _CONNECTORS)
        assert len(link_recs) == 1
        assert (link_recs[0]["from_node_id"], link_recs[0]["to_node_id"]) == (1, 2)
        assert link_recs[0]["overture_connector_ids"] == "a,c"

    def test_oneway_backward_emits_reversed_link(self):
        seg = _segment(access_restrictions=[{"access_type": "denied", "when": {"heading": "forward"}}])
        _, link_recs = convert.build_node_link_tables([seg], _CONNECTORS)
        assert len(link_recs) == 1
        assert (link_recs[0]["from_node_id"], link_recs[0]["to_node_id"]) == (2, 1)
        assert link_recs[0]["overture_connector_ids"] == "c,a"

    def test_unique_link_ids(self):
        seg = _segment(
            geometry="LINESTRING (0 0, 0 1, 0 2)",
            connectors=[
                {"connector_id": "a", "at": 0.0},
                {"connector_id": "b", "at": 0.5},
                {"connector_id": "c", "at": 1.0},
            ],
        )
        _, link_recs = convert.build_node_link_tables([seg], _CONNECTORS)
        ids = [r["link_id"] for r in link_recs]
        assert len(ids) == len(set(ids))


class TestProvenanceAndAttributes:
    def test_minted_node_ids_and_provenance(self):
        node_recs, link_recs = convert.build_node_link_tables([_segment()], _CONNECTORS)
        node_a = next(n for n in node_recs if n["overture_connector_id"] == "a")
        assert node_a["node_id"] == 1  # sorted connector ids -> 1-based ints
        assert node_a["x_coord"] == 0.0 and node_a["y_coord"] == 0.0
        assert link_recs[0]["overture_segment_id"] == "seg1"

    def test_attributes_mapped_onto_links(self):
        # 'class' is not a valid kwarg name, so override the base dict directly.
        seg = _segment(
            speed_limits=[{"max_speed": {"value": 30, "unit": "mph"}}],
            routes=[{"ref": "NC 1"}],
        )
        seg["class"] = "tertiary"
        _, link_recs = convert.build_node_link_tables([seg], _CONNECTORS)
        r = link_recs[0]
        assert r["facility_type"] == "tertiary"
        assert r["name"] == "A St"
        assert r["free_speed"] == 30.0
        assert r["ref"] == "NC 1"

    def test_extra_tags_carried(self):
        seg = _segment(subclass="driveway")
        _, link_recs = convert.build_node_link_tables([seg], _CONNECTORS, extra_tags=["subclass"])
        assert link_recs[0]["subclass"] == "driveway"


class TestLength:
    def test_length_is_geodesic_meters(self):
        _, link_recs = convert.build_node_link_tables([_segment()], _CONNECTORS)
        # 0,0 -> 0,2 (deg lat) ~= 222 km
        assert link_recs[0]["length"] == pytest.approx(222390, rel=0.01)


class TestMalformedInput:
    def test_missing_connector_raises(self):
        seg = _segment(connectors=[{"connector_id": "a", "at": 0.0}, {"connector_id": "zzz", "at": 1.0}])
        with pytest.raises(ValueError, match="connector 'zzz'"):
            convert.build_node_link_tables([seg], _CONNECTORS)

    def test_coincident_connectors_skipped(self):
        # two connectors at the same 'at' -> no sub-segment, no crash
        seg = _segment(connectors=[{"connector_id": "a", "at": 0.5}, {"connector_id": "c", "at": 0.5}])
        node_recs, link_recs = convert.build_node_link_tables([seg], _CONNECTORS)
        assert link_recs == []
        assert node_recs == []
