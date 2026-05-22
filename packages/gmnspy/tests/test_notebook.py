"""Tests for the GMNS ``_repr_html_`` surface (task 4.9b / issue #92).

:class:`gmnspy.Network` overrides
:meth:`datagrove.dataset.Package._repr_html_` to add the GMNS spec
version and link/node row counts. These tests pin the cross-package
contract: a Network card should retain the Package shape while
advertising the GMNS-specific extras.
"""

from __future__ import annotations

from datagrove.engines.pandas_engine import PandasEngine
from gmnspy import Network
from gmnspy.fixtures import leavenworth


def _make_network() -> Network:
    """Load the Leavenworth fixture with the pandas engine.

    Pandas keeps tests deterministic (no backend processes) and the
    fixture is the canonical "small but realistic" GMNS dataset already
    used across the test suite.
    """
    return Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())


def test_network_repr_html_includes_spec_version() -> None:
    """The active GMNS spec version surfaces in the card metadata."""
    net = _make_network()
    html = net._repr_html_()
    assert net.spec_version  # sanity — fixture loads against a real spec
    assert net.spec_version in html


def test_network_repr_html_includes_link_node_counts() -> None:
    """The card surfaces link and node row counts."""
    net = _make_network()
    html = net._repr_html_()
    assert "links" in html
    assert "nodes" in html
    # The exact counts are fixture-stable: assert they're at least
    # present as integers > 0 via the link/node table preview rows.
    link_count = net.links.count()
    node_count = net.nodes.count()
    assert str(link_count) in html
    assert str(node_count) in html


def test_network_repr_html_extends_package_format() -> None:
    """Output still uses the datagrove card shape (div + table preview)."""
    net = _make_network()
    html = net._repr_html_()
    assert html.startswith("<div")
    assert "Network" in html
    # Table preview still renders.
    assert "<table" in html
    assert "name" in html
    assert "rows" in html
    assert "cols" in html
