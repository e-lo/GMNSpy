"""Validation-output formats for GMNS findings.

After the v1.0 :mod:`gmnspy.map` split, this module's scope is
**spreadsheet exports of findings** — flat CSV and XLSX writers that
take a list of :class:`~datagrove.reports.Issue` and produce a file
suitable for triage in Excel, Google Sheets, or jq.

The interactive HTML map viewer lives in :mod:`gmnspy.map` now:

* :class:`gmnspy.map.NetworkMap` — embeddable component.
* :func:`gmnspy.map.render_network_html` — standalone HTML doc.
* :func:`gmnspy.map.render_validation_html` — validation report page
  (map + findings table).

Importing :func:`render_network_html` / :func:`render_validation_html`
from :mod:`gmnspy.reports` still works for the v1.x line but emits a
:class:`DeprecationWarning`. Migrate to :mod:`gmnspy.map`.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from .findings_table import write_findings_csv, write_findings_xlsx

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.reports import Issue, ValidationReport

    from gmnspy.network import Network

__all__ = [
    "render_network_html",
    "render_validation_html",
    "write_findings_csv",
    "write_findings_xlsx",
]


def render_network_html(network: Network, issues: list[Issue] | None = None, **opts: Any) -> str:
    """Deprecated alias for :func:`gmnspy.map.render_network_html`."""
    warnings.warn(
        "gmnspy.reports.render_network_html has moved to gmnspy.map.render_network_html.",
        DeprecationWarning,
        stacklevel=2,
    )
    from gmnspy.map import render_network_html as _impl

    return _impl(network, issues, **opts)


def render_validation_html(network: Network, report: ValidationReport, **opts: Any) -> str:
    """Deprecated alias for :func:`gmnspy.map.render_validation_html`."""
    warnings.warn(
        "gmnspy.reports.render_validation_html has moved to gmnspy.map.render_validation_html.",
        DeprecationWarning,
        stacklevel=2,
    )
    from gmnspy.map import render_validation_html as _impl

    return _impl(network, report, **opts)
