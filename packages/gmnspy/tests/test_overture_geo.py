"""Tests for gmnspy.overture._geo — pure geometry helpers (WKT, length, slicing)."""

from __future__ import annotations

import pytest
from gmnspy.overture import _geo


class TestWktRoundTrip:
    def test_format_then_parse_is_identity(self):
        coords = [(0.0, 0.0), (0.0, 1.5), (-71.1, 42.0)]
        assert _geo.parse_wkt_linestring(_geo.wkt_linestring(coords)) == coords

    def test_parse_rejects_non_linestring(self):
        with pytest.raises(ValueError, match="LINESTRING"):
            _geo.parse_wkt_linestring("POINT (0 0)")


class TestLength:
    def test_one_degree_latitude_is_about_111km(self):
        assert _geo.line_length_m([(0.0, 0.0), (0.0, 1.0)]) == pytest.approx(111195, rel=0.01)

    def test_empty_and_single_point_are_zero(self):
        assert _geo.line_length_m([]) == 0.0
        assert _geo.line_length_m([(1.0, 2.0)]) == 0.0


class TestSliceLine:
    def test_full_range_returns_endpoints(self):
        assert _geo.slice_line([(0.0, 0.0), (0.0, 2.0)], 0.0, 1.0) == [(0.0, 0.0), (0.0, 2.0)]

    def test_half_interpolates_midpoint(self):
        assert _geo.slice_line([(0.0, 0.0), (0.0, 2.0)], 0.0, 0.5) == [(0.0, 0.0), (0.0, 1.0)]

    def test_keeps_interior_vertices_between_fractions(self):
        coords = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        # 0.25..0.75 of a 2-unit line spans y in [0.5, 1.5]; vertex at y=1.0 is kept.
        sliced = _geo.slice_line(coords, 0.25, 0.75)
        assert sliced == [(0.0, 0.5), (0.0, 1.0), (0.0, 1.5)]

    def test_rejects_degenerate_range(self):
        with pytest.raises(ValueError, match="at_start"):
            _geo.slice_line([(0.0, 0.0), (0.0, 1.0)], 0.5, 0.5)

    def test_rejects_too_few_points(self):
        with pytest.raises(ValueError, match="two coordinates"):
            _geo.slice_line([(0.0, 0.0)], 0.0, 1.0)
