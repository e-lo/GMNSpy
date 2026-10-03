"""Tests for the build Area union."""

import pytest
from gmnspy.osm.query import point_buffer_bbox
from gmnspy.workbench.area import Area, BboxArea, PlaceArea, PointArea
from pydantic import TypeAdapter, ValidationError

AREA = TypeAdapter(Area)


def test_discriminates_on_kind():
    assert isinstance(AREA.validate_python({"kind": "bbox", "bbox": [-79, 35, -78, 36]}), BboxArea)
    assert isinstance(AREA.validate_python({"kind": "point", "lat": 35.9, "lon": -78.9, "buffer_m": 500}), PointArea)
    with pytest.raises(ValidationError):
        AREA.validate_python({"kind": "county", "name": "Durham"})


def test_bbox_must_be_ordered_and_in_range():
    assert BboxArea(bbox=(-79, 35, -78, 36)).to_bbox() == (-79, 35, -78, 36)
    with pytest.raises(ValidationError, match="west<east"):
        BboxArea(bbox=(-78, 35, -79, 36))
    with pytest.raises(ValidationError):
        BboxArea(bbox=(-79, 35, -78, 91))


def test_point_bbox_matches_the_osm_builder():
    area = PointArea(lat=35.9, lon=-78.9, buffer_m=800)
    assert area.to_bbox() == pytest.approx(point_buffer_bbox(35.9, -78.9, 800))
    assert area.to_polygon() is None
    with pytest.raises(ValidationError):
        PointArea(lat=35.9, lon=-78.9, buffer_m=0)


@pytest.mark.parametrize(
    "point",
    [
        {"lat": 0.0, "lon": 179.999, "buffer_m": 5000},  # crosses the antimeridian
        {"lat": 89.999, "lon": 0.0, "buffer_m": 5000},  # crosses the pole
        {"lat": 0.0, "lon": 0.0, "buffer_m": float("inf")},
    ],
)
def test_point_whose_buffer_leaves_the_world_is_rejected(point):
    with pytest.raises(ValidationError, match="does not fit in one bbox"):
        PointArea(**point)
    with pytest.raises(ValidationError):  # the action API path validates the same way
        AREA.validate_python({"kind": "point", **point})


def test_place_keeps_polygon_for_overpass():
    ring = [(35.9, -79.0), (35.9, -78.8), (36.1, -78.8), (35.9, -79.0)]
    area = PlaceArea(name="Durham", bbox=(-79.01, 35.86, -78.75, 36.14), polygon=ring)
    assert area.to_bbox() == (-79.01, 35.86, -78.75, 36.14) and area.to_polygon() == ring
    with pytest.raises(ValidationError, match="at least 3"):
        PlaceArea(name="x", bbox=(-79, 35, -78, 36), polygon=[(35, -79)])
