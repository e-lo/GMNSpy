"""Validation framework for datagrove.

:class:`ValidationReport` is the single object returned from every
validation path — schema checks (task 2.3), structural checks (2.5),
foreign-key checks (2.4), the sync-state ``DirtyTracker`` (2.6), and
the data-quality plugins registered through ``datagrove.quality``
(Phase 3). Producers populate one report per run; the renderers in
:mod:`datagrove.validation.report` turn it into rich-console text,
JSON, or HTML.

The HTML renderer (interactive single-file: Jinja2 + DataTables +
Vega-Lite map view) is task 2.2 / GitHub issue #61 and will live in
:mod:`datagrove.validation.report` alongside the rich + JSON
renderers. Until it lands, the JSON output is the canonical
machine-readable form.

Public surface
--------------

- :class:`Severity` — ``ERROR``, ``WARNING``, ``INFO``, ``DATA_QUALITY``.
- :class:`Category` — ``SCHEMA``, ``STRUCTURAL``, ``FOREIGN_KEY``,
  ``SYNC_STATE``, ``DATA_QUALITY``.
- :class:`Issue` — one frozen, hashable finding.
- :class:`ValidationReport` — mutable aggregate; carries issues + run
  metadata; provides query helpers + serialisation shortcuts.
- :func:`render_rich` — pretty rich-console string.
- :func:`render_json` — stable JSON snapshot.

Domain packages (notably :mod:`gmnspy.quality`) register additional
rules via the ``datagrove.quality.rules`` entry-point group. Their
issues use ``category=DATA_QUALITY`` so they slot into the same report
as everything else and the consumer doesn't need to know which package
they came from.

Examples:
    >>> from datagrove.validation import (
    ...     ValidationReport, Severity, Category, render_json,
    ... )
    >>> r = ValidationReport(source="x.gmns", spec_version="0.97")
    >>> _ = r.add(
    ...     severity=Severity.ERROR,
    ...     category=Category.SCHEMA,
    ...     code="schema.required",
    ...     message="link.from_node_id row 0: value is null",
    ...     table="link",
    ... )
    >>> r.has_errors
    True
    >>> import json
    >>> json.loads(render_json(r))["summary"]["error"]
    1
"""

from .report import render_json, render_rich
from .types import Category, Issue, Severity, ValidationReport

__all__ = [
    "Category",
    "Issue",
    "Severity",
    "ValidationReport",
    "render_json",
    "render_rich",
]
