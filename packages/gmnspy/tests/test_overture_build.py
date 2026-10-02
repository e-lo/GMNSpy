"""End-to-end tests for gmnspy.overture.build against the local GeoParquet fixture.

No network / S3 — the pinned-release reads are redirected to the committed
fixture via ``data_root=``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from datagrove.engines.ibis_engine import IbisEngine
from gmnspy.overture import build

FIXTURE_ROOT = str(Path(__file__).resolve().parent / "fixtures" / "overture")
WORLD_BBOX = (-0.5, -0.5, 0.5, 0.5)


@pytest.fixture
def engine():
    eng = IbisEngine()
    yield eng
    eng.close()


def _links_df(net):
    return net.links.to_pandas()


class TestBuildDriveNetwork:
    def test_nodes_links_and_provenance(self, engine):
        net = build.build_network_from_overture(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine)
        links = _links_df(net)
        nodes = net.nodes.to_pandas()
        # residential (split at interior connector -> 2 sub-segs, two-way -> 4)
        # + primary one-way (1) = 5 links; footway excluded.
        assert len(links) == 5
        assert set(nodes["overture_connector_id"]) == {"ca", "cb", "cc", "cd"}
        assert "overture_segment_id" in links.columns

    def test_oneway_primary_has_single_direction(self, engine):
        net = build.build_network_from_overture(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine)
        links = _links_df(net)
        hwy = links[links["overture_segment_id"] == "s_hwy"]
        assert len(hwy) == 1
        assert hwy.iloc[0]["ref"] == "US 1"
        assert hwy.iloc[0]["free_speed"] == pytest.approx(62.1)  # 100 km/h -> mph

    def test_name_carried(self, engine):
        net = build.build_network_from_overture(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine)
        links = _links_df(net)
        assert "Main St" in set(links["name"])


class TestConfigAndValidation:
    def test_config_declares_crs_and_units(self, engine):
        net = build.build_network_from_overture(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine)
        cfg = net.config.to_pandas().iloc[0]
        assert cfg["dataset_name"] == "overture_export"
        assert cfg["crs"] == "EPSG:4326"
        assert cfg["geometry_field_format"] == "WKT"
        assert cfg["speed"] == "mph"

    def test_network_validates_without_errors(self, engine):
        net = build.build_network_from_overture(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine)
        errors = [i for i in net.validate().issues if i.severity.value == "error"]
        assert errors == [], errors


class TestEdgeCases:
    def test_extra_tags_carried_onto_links(self, engine):
        net = build.build_network_from_overture(
            WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine, extra_tags=["subtype"]
        )
        assert "subtype" in net.links.to_pandas().columns

    def test_empty_area_raises(self, engine):
        with pytest.raises(ValueError, match="no Overture segments matched"):
            build.build_network_from_overture(
                (10.0, 10.0, 11.0, 11.0), network_type="drive", data_root=FIXTURE_ROOT, engine=engine
            )
