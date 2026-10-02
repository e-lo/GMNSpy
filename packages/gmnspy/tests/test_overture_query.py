"""Tests for gmnspy.overture.query reading the committed local GeoParquet fixture.

These exercise the real DuckDB read path (bbox + class pushdown, WKB->WKT via the
spatial extension) against a tiny Overture-shaped fixture — no network / S3. The
fixture is built by ``tests/fixtures/overture/build_fixture.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from datagrove.engines.ibis_engine import IbisEngine
from gmnspy.overture import query
from gmnspy.overture.layout import is_local_snapshot

FIXTURE_ROOT = str(Path(__file__).resolve().parent / "fixtures" / "overture")
WORLD_BBOX = (-0.5, -0.5, 0.5, 0.5)


@pytest.fixture
def engine():
    eng = IbisEngine()
    yield eng
    eng.close()


class TestResolveArea:
    def test_bbox_passthrough(self):
        assert query.resolve_area((-71.1, 42.0, -71.0, 42.1)) == (-71.1, 42.0, -71.0, 42.1)

    def test_point_buffer(self):
        _w, _s, e, n = query.resolve_area((0.0, 0.0), buffer_m=111320.0)
        assert (round(e, 3), round(n, 3)) == (1.0, 1.0)

    def test_bad_area_raises(self):
        with pytest.raises(ValueError, match="place string"):
            query.resolve_area((1.0, 2.0, 3.0))


class TestDataRoot:
    def test_default_is_aws_release(self):
        assert query.overture_data_root("2024-11-13.0", None).endswith("release/2024-11-13.0")

    def test_override_wins(self):
        assert query.overture_data_root("ignored", "/snap/") == "/snap"


class TestReadSegments:
    def test_drive_excludes_footway_and_returns_wkt(self, engine):
        segs = query.read_segments(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine)
        classes = {s["class"] for s in segs}
        assert "footway" not in classes
        assert {"residential", "primary"} <= classes
        main = next(s for s in segs if s["id"] == "s_main")
        assert main["geometry"].startswith("LINESTRING")
        # nested properties survive the round-trip
        assert main["names"]["primary"] == "Main St"
        assert isinstance(main["connectors"], list)

    def test_walk_includes_footway(self, engine):
        segs = query.read_segments(WORLD_BBOX, network_type="walk", data_root=FIXTURE_ROOT, engine=engine)
        assert "footway" in {s["class"] for s in segs}

    def test_bbox_filters_out_of_range(self, engine):
        far = (10.0, 10.0, 11.0, 11.0)
        assert query.read_segments(far, network_type="all", data_root=FIXTURE_ROOT, engine=engine) == []


class TestReadConnectors:
    def test_returns_lon_lat_map(self, engine):
        conns = query.read_connectors(WORLD_BBOX, data_root=FIXTURE_ROOT, engine=engine)
        assert conns["ca"] == pytest.approx((0.0, 0.0))
        assert conns["cc"] == pytest.approx((0.0, 0.002))


class TestFetchNetworkElements:
    def test_returns_segments_and_connectors(self, engine):
        segs, conns = query.fetch_network_elements(
            WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine
        )
        assert len(segs) == 2  # residential + primary (footway excluded)
        # every connector referenced by a drive segment is resolvable
        referenced = {c["connector_id"] for s in segs for c in s["connectors"]}
        assert referenced <= set(conns)


class TestLocalSnapshotLayout:
    def test_fixture_is_a_local_snapshot(self):
        assert is_local_snapshot(FIXTURE_ROOT)

    def test_needs_both_files(self, tmp_path):
        (tmp_path / "segment.parquet").write_bytes(b"")
        assert not is_local_snapshot(tmp_path)
        assert not is_local_snapshot(tmp_path / "segment.parquet")


class TestCountSegments:
    def test_count_matches_read(self, engine):
        n = query.count_segments(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine)
        assert n > 0
        assert n == len(query.read_segments(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine))

    def test_empty_bbox_counts_zero(self, engine):
        assert query.count_segments((10.0, 10.0, 11.0, 11.0), data_root=FIXTURE_ROOT, engine=engine) == 0
