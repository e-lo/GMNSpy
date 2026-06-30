"""Tests for :mod:`gmnspy.reports.html_map` — interactive network-on-map HTML viewer.

The renderer takes a :class:`~gmnspy.network.Network` and an optional
list of :class:`~datagrove.reports.Issue` overlays and produces one
self-contained HTML document with a Leaflet map pane on top and a
filterable findings table below. These tests pin the contract: the
output is a single file (no remote ``<script src>``), markers carry the
right data, popups respect the no-WKT rule, and the bridge
(``data-issue-id`` on each marker + matching row) is in place.
"""

from __future__ import annotations

import re

import pandas as pd
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.reports import Category, Issue, Severity, ValidationReport
from gmnspy import Network
from gmnspy.fixtures import leavenworth
from gmnspy.reports import render_network_html, render_validation_html

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _osm_network(tmp_path) -> Network:
    """Tiny in-memory network with osm_way_id provenance."""
    link = pd.DataFrame(
        {
            "link_id": [1, 2],
            "from_node_id": [10, 11],
            "to_node_id": [11, 12],
            "directed": [True, True],
            "length": [100.0, 200.0],
            "osm_way_id": [5001, 5002],
            "geometry": [
                "LINESTRING (-120.6 47.5, -120.5 47.6)",
                "LINESTRING (-120.5 47.6, -120.4 47.7)",
            ],
        }
    )
    node = pd.DataFrame(
        {
            "node_id": [10, 11, 12],
            "x_coord": [-120.6, -120.5, -120.4],
            "y_coord": [47.5, 47.6, 47.7],
        }
    )
    csv_dir = tmp_path / "osm_net"
    csv_dir.mkdir()
    link.to_csv(csv_dir / "link.csv", index=False)
    node.to_csv(csv_dir / "node.csv", index=False)
    return Network.from_source(csv_dir, engine=PandasEngine())


def _leavenworth_network() -> Network:
    """The bundled non-OSM CSV fixture."""
    return Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())


# ---------------------------------------------------------------------------
# Generality — network alone
# ---------------------------------------------------------------------------


def test_render_network_html_no_issues_returns_self_contained_html(tmp_path):
    """``render_network_html(network, None)`` works — network alone."""
    net = _osm_network(tmp_path)
    html = render_network_html(net)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    # Single self-contained file: NO remote script/style references.
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html
    assert "unpkg.com" not in html
    assert "cdn.jsdelivr.net" not in html
    # Leaflet is inlined (we just look for its banner comment).
    assert "Leaflet" in html


def test_render_network_html_empty_issues_treated_like_none(tmp_path):
    """An empty issue list renders identically to ``issues=None`` (no overlays)."""
    net = _osm_network(tmp_path)
    html = render_network_html(net, [])
    assert "Findings (0)" not in html  # the table section is not rendered for empty
    # Map div is still present.
    assert 'id="gv-map"' in html


# ---------------------------------------------------------------------------
# Marker / popup contract
# ---------------------------------------------------------------------------


def test_explicit_coord_issue_gets_a_marker(tmp_path):
    """An issue with explicit lon/lat in ``extra`` becomes a map marker."""
    net = _osm_network(tmp_path)
    issue = Issue(
        severity=Severity.WARNING,
        category=Category.DATA_QUALITY,
        code="quality.example",
        message="point of interest",
        extra={"lon": -120.55, "lat": 47.55},
    )
    html = render_network_html(net, [issue])
    # The payload blob is JSON — search for the lon coordinate as a number.
    assert "-120.55" in html
    assert "47.55" in html


def test_link_issue_on_osm_network_popup_has_edit_in_osm(tmp_path):
    """OSM-sourced link issue should produce an Edit in OSM link in the table."""
    net = _osm_network(tmp_path)
    issue = Issue(
        severity=Severity.WARNING,
        category=Category.SCHEMA,
        code="schema.required",
        message="link row 0: free_speed is null",
        table="link",
        row=0,
    )
    html = render_network_html(net, [issue])
    # iD URL for way 5001 should be present.
    assert "https://www.openstreetmap.org/edit?editor=id&amp;way=5001" in html or (
        "https://www.openstreetmap.org/edit?editor=id&way=5001" in html
    )


def test_link_issue_on_non_osm_network_has_no_osm_link():
    """Non-OSM network: NO openstreetmap.org/edit URL anywhere."""
    net = _leavenworth_network()
    issue = Issue(
        severity=Severity.WARNING,
        category=Category.SCHEMA,
        code="schema.required",
        message="link row 0",
        table="link",
        row=0,
    )
    html = render_network_html(net, [issue])
    assert "openstreetmap.org/edit" not in html


def test_popup_has_no_wkt_geometry_string(tmp_path):
    """Popups must not dump the raw WKT LINESTRING — protect against giant tooltips."""
    net = _osm_network(tmp_path)
    issue = Issue(
        severity=Severity.WARNING,
        category=Category.SCHEMA,
        code="schema.required",
        message="link row 0: free_speed is null",
        table="link",
        row=0,
    )
    html = render_network_html(net, [issue])
    # The geometry column in the source DOES contain "LINESTRING (...)" but
    # that's never echoed into the payload or table.
    payload_match = re.search(r"__GMNSPY_DATA__ = (\{.*?\});", html, re.S)
    assert payload_match is not None, "expected window.__GMNSPY_DATA__ blob"
    payload = payload_match.group(1)
    assert "LINESTRING" not in payload


# ---------------------------------------------------------------------------
# Marker → row bridge
# ---------------------------------------------------------------------------


def test_each_marker_and_table_row_share_an_issue_id(tmp_path):
    """Every located issue's marker and its table row carry a matching data-issue-id."""
    net = _osm_network(tmp_path)
    issues = [
        Issue(
            severity=Severity.WARNING,
            category=Category.SCHEMA,
            code="schema.required",
            message="link row 0",
            table="link",
            row=0,
        ),
        Issue(
            severity=Severity.WARNING,
            category=Category.DATA_QUALITY,
            code="quality.example",
            message="point",
            extra={"lon": -120.55, "lat": 47.55},
        ),
    ]
    html = render_network_html(net, issues)
    # Every issue_id in the payload appears as data-issue-id on a table row.
    payload_match = re.search(r"__GMNSPY_DATA__ = (\{.*?\});", html, re.S)
    assert payload_match is not None
    payload = payload_match.group(1)
    issue_ids_in_payload = re.findall(r'"issue_id":\s*"([^"]+)"', payload)
    assert len(issue_ids_in_payload) >= 1
    for iid in issue_ids_in_payload:
        assert f'data-issue-id="{iid}"' in html


def test_unlocated_issue_goes_to_sidebar_with_issue_id():
    """A cross-cutting issue with no coords appears in the sidebar AND has a row in the table."""
    net = _leavenworth_network()
    issue = Issue(
        severity=Severity.ERROR,
        category=Category.STRUCTURAL,
        code="structural.missing_table",
        message="some required table missing",
    )
    html = render_network_html(net, [issue])
    assert "Unlocated findings" in html
    assert "data-unlocated-issue-id=" in html
    assert "structural.missing_table" in html


def test_payload_contains_severity_code_message_for_each_marker(tmp_path):
    """Marker payload includes the popup fields (severity, code, message, fix_hint)."""
    net = _osm_network(tmp_path)
    issues = [
        Issue(
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            code="schema.specific_code_xyz",
            message="meaningful message about row 0",
            table="link",
            row=0,
            fix_hint="hint about fixing",
        ),
    ]
    html = render_network_html(net, issues)
    assert "schema.specific_code_xyz" in html
    assert "meaningful message about row 0" in html
    assert "hint about fixing" in html


# ---------------------------------------------------------------------------
# render_validation_html wrapper
# ---------------------------------------------------------------------------


def test_render_validation_html_wraps_render_network_html(tmp_path):
    """The validation wrapper passes through report.issues + a source-aware title."""
    net = _osm_network(tmp_path)
    report = ValidationReport(source="my_net.gmns", spec_version="0.97")
    report.add(
        severity=Severity.WARNING,
        category=Category.SCHEMA,
        code="schema.required",
        message="link row 0",
        table="link",
        row=0,
    )
    html = render_validation_html(net, report)
    assert "my_net.gmns" in html  # source in title
    assert "schema.required" in html  # the issue rendered


# ---------------------------------------------------------------------------
# Header counters
# ---------------------------------------------------------------------------


def test_header_shows_located_vs_unlocated_split(tmp_path):
    """Header counter shows N on map · M unlocated."""
    net = _osm_network(tmp_path)
    issues = [
        Issue(
            severity=Severity.WARNING,
            category=Category.SCHEMA,
            code="schema.required",
            message="link row 0",
            table="link",
            row=0,
        ),  # located via link midpoint
        Issue(
            severity=Severity.ERROR,
            category=Category.STRUCTURAL,
            code="structural.x",
            message="cross-cutting",
        ),  # unlocated
    ]
    html = render_network_html(net, issues)
    assert "1 on map" in html
    assert "1 unlocated" in html
