"""Interactive network-on-map HTML viewer + spreadsheet writers for GMNS findings.

The renderers in this package overlay :class:`~datagrove.reports.Issue` objects
onto the actual link / node geometry of a :class:`~gmnspy.network.Network` and
emit a single self-contained HTML file with a Leaflet map pane above and a
filterable table below (composed from
:func:`datagrove.reports.render_html`'s table fragment). For
OpenStreetMap-sourced networks, each popup carries a one-click deep link to
the iD editor (see :mod:`gmnspy.osm.edit`).

The viewer is GMNS-specific by composition only — the underlying issue
container is the engine-agnostic
:class:`datagrove.reports.ValidationReport`, so any
:class:`~datagrove.reports.Issue` source (validation, GMNS quality rules,
graph topology checks, custom user rules) plugs in here unchanged.

Optional ``[reports]`` extra (``pip install 'gmnspy[reports]'``) pulls in
``openpyxl`` (XLSX writer), ``jinja2`` (template engine — also a transitive
datagrove dep), and ``shapely`` (link-midpoint geometry for markers).
Importing this package is cheap and does NOT require the extra; individual
functions raise a helpful :class:`ImportError` only when they actually need
the missing library.
"""

from __future__ import annotations

from .findings_table import write_findings_csv, write_findings_xlsx
from .html_map import render_network_html, render_validation_html

__all__ = [
    "render_network_html",
    "render_validation_html",
    "write_findings_csv",
    "write_findings_xlsx",
]
