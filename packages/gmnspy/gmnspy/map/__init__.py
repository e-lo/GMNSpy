"""Embeddable interactive maps for GMNS networks.

This module is the home of the visualization component:

* :class:`NetworkMap` — the reusable embeddable component. Any host
  page (notebook cell, validation report, custom dashboard) can
  include shared head assets once and drop in one or more
  per-instance body fragments. Multiple maps coexist on a single page
  via unique UIDs.
* :func:`render_network_html` — full standalone HTML of just the
  network map. Thin wrapper over :meth:`NetworkMap.to_html`.
* :func:`render_validation_html` — full validation report page that
  composes a NetworkMap with the findings table, filter bar, and
  unlocated-findings sidebar.

For spreadsheet exports of findings (CSV/XLSX), see
:mod:`gmnspy.reports.findings_table`.

Optional ``[reports]`` extra (``pip install 'gmnspy[reports]'``) pulls
in ``jinja2`` for templating. Leaflet itself is vendored — no internet
required when the report is opened.
"""

from __future__ import annotations

from .component import NetworkMap
from .render import render_network_html, render_validation_html

__all__ = ["NetworkMap", "render_network_html", "render_validation_html"]
