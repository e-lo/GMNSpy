"""Validation-report artifacts + renderers (architecture §4 + §6.3).

This module is the **single home** for the report data types and the
renderers that turn them into rich-console text, JSON, or interactive
single-file HTML. Validators in :mod:`datagrove.validation` produce
:class:`ValidationReport` instances; renderers here format them.

Public surface
--------------

- :class:`Severity` — ``ERROR``, ``WARNING``, ``INFO``.
- :class:`Category` — ``SCHEMA``, ``STRUCTURAL``, ``FOREIGN_KEY``,
  ``SYNC_STATE``, ``DATA_QUALITY``.
- :class:`Issue` — one frozen, hashable finding.
- :class:`ValidationReport` — mutable aggregate of issues + run metadata.
- :func:`render_rich` — pretty rich-console string.
- :func:`render_json` — stable JSON snapshot.
- :func:`render_html` — interactive single-file HTML report.

The legacy ``datagrove.validation`` import path re-exports the same
symbols for back-compat — existing code that does
``from datagrove.validation import ValidationReport`` keeps working.
"""

from .render import render_html, render_json, render_rich
from .types import Category, Issue, Severity, ValidationReport, severity_rank

__all__ = [
    "Category",
    "Issue",
    "Severity",
    "ValidationReport",
    "render_html",
    "render_json",
    "render_rich",
    "severity_rank",
]
