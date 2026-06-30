"""Tests for :mod:`gmnspy.osm.edit` — OSM editor deep-link helpers.

These helpers turn an OSM way / node id (or a validation :class:`Issue`
that points at one) into a deep link the user can click to jump
straight to the offending element in iD or JOSM. The URL format for iD
is undocumented but has been stable since 2015; the format tests pin
it so an upstream change is caught here rather than in production
reports.
"""

from __future__ import annotations

import pandas as pd
import pytest
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.reports import Category, Issue, Severity
from gmnspy import Network
from gmnspy.fixtures import leavenworth
from gmnspy.osm.edit import issue_osm_edit_url, osm_edit_url

# ---------------------------------------------------------------------------
# osm_edit_url — pure URL formatter
# ---------------------------------------------------------------------------


def test_osm_edit_url_way_id_format_pinned():
    """iD's way deep-link format is undocumented but stable since 2015."""
    assert osm_edit_url(12345) == "https://www.openstreetmap.org/edit?editor=id&way=12345"


def test_osm_edit_url_node_id_format_pinned():
    """iD's node deep-link uses ``node=<id>`` (not ``way=<id>``)."""
    assert osm_edit_url(99, kind="node") == "https://www.openstreetmap.org/edit?editor=id&node=99"


def test_osm_edit_url_relation_id_format_pinned():
    """Relations use ``relation=<id>``."""
    assert osm_edit_url(7, kind="relation") == "https://www.openstreetmap.org/edit?editor=id&relation=7"


def test_osm_edit_url_string_id_coerces_to_int():
    """Callers may pass ids straight from CSV (string-typed) — coerce."""
    assert osm_edit_url("12345") == "https://www.openstreetmap.org/edit?editor=id&way=12345"


def test_osm_edit_url_none_returns_none():
    """``None`` must round-trip to ``None`` so callers can chain without branching."""
    assert osm_edit_url(None) is None


def test_osm_edit_url_empty_string_returns_none():
    """Empty string (common from CSV) treated as missing → ``None``."""
    assert osm_edit_url("") is None


def test_osm_edit_url_non_numeric_returns_none():
    """A non-integer-shaped value isn't an OSM id — ``None``, no exception."""
    assert osm_edit_url("not-an-id") is None


def test_osm_edit_url_nan_returns_none():
    """pandas NaN (common when osm_way_id is missing in some rows) → ``None``."""
    import math

    assert osm_edit_url(math.nan) is None


def test_osm_edit_url_josm_editor_uses_remote_endpoint():
    """JOSM's remote-control endpoint is the localhost JOSM-RemoteControl port."""
    url = osm_edit_url(12345, editor="josm")
    assert url is not None
    # JOSM RemoteControl: http://127.0.0.1:8111/load_object?objects=w12345
    assert url.startswith("http://127.0.0.1:8111/")
    assert "w12345" in url


def test_osm_edit_url_josm_node_uses_n_prefix():
    """JOSM's remote-control object prefix: w/n/r for way/node/relation."""
    url = osm_edit_url(99, kind="node", editor="josm")
    assert url is not None
    assert "n99" in url


def test_osm_edit_url_unknown_editor_raises():
    """Unknown editor name is a programmer bug — raise, don't silently fall back."""
    with pytest.raises(ValueError, match="editor"):
        osm_edit_url(1, editor="emacs")  # type: ignore[arg-type]


def test_osm_edit_url_unknown_kind_raises():
    """Unknown ``kind`` is a programmer bug — raise."""
    with pytest.raises(ValueError, match="kind"):
        osm_edit_url(1, kind="building")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# issue_osm_edit_url — Issue + Network → URL or None
# ---------------------------------------------------------------------------


def _osm_network(tmp_path) -> Network:
    """Return a tiny in-memory Network that looks OSM-sourced (has osm_way_id)."""
    link = pd.DataFrame(
        {
            "link_id": [1, 2],
            "from_node_id": [10, 11],
            "to_node_id": [11, 12],
            "directed": [True, True],
            "length": [100.0, 200.0],
            "osm_way_id": [5001, 5002],
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


def test_issue_osm_edit_url_link_with_osm_way_id(tmp_path):
    """Link-table issue on an OSM-sourced network → iD edit URL for the way."""
    net = _osm_network(tmp_path)
    issue = Issue(
        severity=Severity.WARNING,
        category=Category.SCHEMA,
        code="schema.required",
        message="link row 0: free_speed is null",
        table="link",
        row=0,
    )
    url = issue_osm_edit_url(issue, net)
    assert url == "https://www.openstreetmap.org/edit?editor=id&way=5001"


def test_issue_osm_edit_url_uses_extra_fast_path(tmp_path):
    """If ``issue.extra['osm_way_id']`` is set, prefer it over a table lookup."""
    net = _osm_network(tmp_path)
    issue = Issue(
        severity=Severity.WARNING,
        category=Category.DATA_QUALITY,
        code="quality.unknown",
        message="cross-cutting OSM finding",
        # Note: no table/row — must come from extra.
        extra={"osm_way_id": 9999},
    )
    url = issue_osm_edit_url(issue, net)
    assert url == "https://www.openstreetmap.org/edit?editor=id&way=9999"


def test_issue_osm_edit_url_node_on_osm_network(tmp_path):
    """Node-table issue on an OSM-sourced network → URL via the node's osm_node_id when present."""
    # Add an osm_node_id column to the node table this time.
    link = pd.DataFrame(
        {
            "link_id": [1],
            "from_node_id": [10],
            "to_node_id": [11],
            "directed": [True],
            "length": [100.0],
            "osm_way_id": [5001],
        }
    )
    node = pd.DataFrame(
        {
            "node_id": [10, 11],
            "x_coord": [-120.6, -120.5],
            "y_coord": [47.5, 47.6],
            "osm_node_id": [42, 43],
        }
    )
    csv_dir = tmp_path / "osm_net_with_node_provenance"
    csv_dir.mkdir()
    link.to_csv(csv_dir / "link.csv", index=False)
    node.to_csv(csv_dir / "node.csv", index=False)
    net = Network.from_source(csv_dir, engine=PandasEngine())

    issue = Issue(
        severity=Severity.WARNING,
        category=Category.SCHEMA,
        code="schema.range",
        message="node row 1: y_coord out of range",
        table="node",
        row=1,
    )
    url = issue_osm_edit_url(issue, net)
    assert url == "https://www.openstreetmap.org/edit?editor=id&node=43"


def test_issue_osm_edit_url_non_osm_network_returns_none():
    """Non-OSM network (no osm_way_id column in links) → None."""
    # The bundled Leavenworth CSV fixture has no OSM provenance columns.
    net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
    issue = Issue(
        severity=Severity.WARNING,
        category=Category.SCHEMA,
        code="schema.required",
        message="link row 0: x is null",
        table="link",
        row=0,
    )
    assert issue_osm_edit_url(issue, net) is None


def test_issue_osm_edit_url_no_table_no_extra_returns_none(tmp_path):
    """Cross-cutting issue with no table and no extra OSM hint → None."""
    net = _osm_network(tmp_path)
    issue = Issue(
        severity=Severity.ERROR,
        category=Category.STRUCTURAL,
        code="structural.missing_table",
        message="link table missing",
    )
    assert issue_osm_edit_url(issue, net) is None


def test_issue_osm_edit_url_josm_editor_propagates(tmp_path):
    """``editor='josm'`` round-trips through to the URL builder."""
    net = _osm_network(tmp_path)
    issue = Issue(
        severity=Severity.WARNING,
        category=Category.SCHEMA,
        code="schema.required",
        message="link row 0",
        table="link",
        row=0,
    )
    url = issue_osm_edit_url(issue, net, editor="josm")
    assert url is not None
    assert "127.0.0.1:8111" in url
    assert "w5001" in url
