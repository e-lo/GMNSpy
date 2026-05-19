"""Validators for datagrove (architecture §4 + §6.3).

This module owns the **validator functions** — schema checks (task 2.3),
structural checks (2.5), foreign-key checks (2.4), and the sync-state
``DirtyTracker`` (2.6). Each validator produces a
:class:`~datagrove.reports.ValidationReport`, the unified artifact that
lives in :mod:`datagrove.reports` alongside the rich/JSON/HTML
renderers.

The :class:`ValidationReport`, :class:`Issue`, :class:`Severity`,
:class:`Category` types and the :func:`render_rich` / :func:`render_json`
/ :func:`render_html` renderers are re-exported here so the legacy
``from datagrove.validation import ValidationReport`` import path keeps
working — callers that want the canonical home should import from
:mod:`datagrove.reports`.

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

# Back-compat re-exports from the new canonical home.
from datagrove.reports import (
    Category,
    Issue,
    Severity,
    ValidationReport,
    render_html,
    render_json,
    render_rich,
)

from .foreign_keys import check_foreign_key, check_foreign_keys
from .structural import check_structural, check_structural_from_source
from .sync_state import DirtyTracker, FKStamp, TableHash, hash_column, hash_table

__all__ = [
    "Category",
    "DirtyTracker",
    "FKStamp",
    "Issue",
    "Severity",
    "TableHash",
    "ValidationReport",
    "check_foreign_key",
    "check_foreign_keys",
    "check_structural",
    "check_structural_from_source",
    "hash_column",
    "hash_table",
    "render_html",
    "render_json",
    "render_rich",
]
