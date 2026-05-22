"""Tests for the notebook ``_repr_html_`` surface (task 4.9a / issue #91).

Each public dataclass on the read-and-edit surface — :class:`Package`,
:class:`Table`, :class:`ValidationReport`, :class:`EditResult` — ships
a Jupyter-friendly ``_repr_html_`` that returns a small self-contained
HTML card. These tests pin the contract:

* every renderer returns a non-empty ``<div``-prefixed string;
* the user-visible identity fields (table name, row counts, severity
  labels, diff counts) actually show up;
* user-controlled values are HTML-escaped (no XSS leak through a hostile
  table name).

The cards are intentionally plain — inline CSS, stdlib-only escaping —
so the tests assert on substring presence rather than HTML structure.
"""

from __future__ import annotations

from datetime import datetime

from datagrove.dataset import Package, Table
from datagrove.editing import Diff, Edit, EditResult
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.reports import Category, Severity, ValidationReport


def _make_package() -> Package:
    """Build a tiny in-memory package with two named tables."""
    engine = PandasEngine()
    link = Table(
        name="link",
        expr=engine.from_records([{"id": 1, "from_node": 10}, {"id": 2, "from_node": 20}]),
        engine=engine,
    )
    node = Table(name="node", expr=engine.from_records([{"id": 10}]), engine=engine)
    return Package.from_tables({"link": link, "node": node})


# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------


def test_package_repr_html_returns_html_string() -> None:
    """Output starts with ``<div`` and names the package."""
    pkg = _make_package()
    html = pkg._repr_html_()
    assert html.startswith("<div")
    assert "Package" in html
    # The default Package.from_tables() name is "synthesized" — the
    # spec's name field should be reflected in the header.
    assert "synthesized" in html


def test_package_repr_html_lists_tables() -> None:
    """The card preview enumerates each loaded table with its row count."""
    pkg = _make_package()
    html = pkg._repr_html_()
    assert "link" in html
    assert "node" in html
    # Row counts pushed down through Table.count() should land in the card.
    assert ">2<" in html  # link has 2 rows
    assert ">1<" in html  # node has 1 row


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------


def test_table_repr_html_includes_name_and_count() -> None:
    """The card lists the table name and exposes the row count."""
    engine = PandasEngine()
    t = Table(
        name="links",
        expr=engine.from_records([{"a": 1}, {"a": 2}, {"a": 3}]),
        engine=engine,
    )
    html = t._repr_html_()
    assert "links" in html
    # Row count is 3 — should appear in the kv line.
    assert ">3<" in html


def test_table_repr_html_shows_dirty_badge_when_dirty() -> None:
    """A dirty table renders the ``dirty`` badge; clean tables don't."""
    engine = PandasEngine()
    t = Table(name="t", expr=engine.from_records([{"a": 1}]), engine=engine)
    assert "dirty" not in t._repr_html_()
    t.dirty = True
    html = t._repr_html_()
    assert "dirty" in html


def test_table_repr_html_truncates_long_column_list() -> None:
    """Tables with >12 columns get the ``(+N more)`` note."""
    engine = PandasEngine()
    cols = {f"c{i}": i for i in range(20)}
    t = Table(name="wide", expr=engine.from_records([cols]), engine=engine)
    html = t._repr_html_()
    assert "+8 more" in html  # 20 columns total, 12 shown


# ---------------------------------------------------------------------------
# ValidationReport
# ---------------------------------------------------------------------------


def test_validation_report_repr_html_groups_by_severity() -> None:
    """Per-severity counts surface as labeled cells in the card."""
    report = ValidationReport(source="x.gmns")
    report.add(
        severity=Severity.ERROR,
        category=Category.SCHEMA,
        code="schema.required",
        message="missing required field",
    )
    report.add(
        severity=Severity.WARNING,
        category=Category.SYNC_STATE,
        code="sync.fk_stale",
        message="fk stale",
    )
    html = report._repr_html_()
    assert "ERROR" in html
    assert "WARNING" in html
    assert "INFO" in html
    assert "DATA_QUALITY" in html


def test_validation_report_repr_html_truncates_long_issue_list() -> None:
    """A 50-issue report collapses the tail into a +N-more note."""
    report = ValidationReport(source="big.gmns")
    for i in range(50):
        report.add(
            severity=Severity.INFO,
            category=Category.SCHEMA,
            code="schema.note",
            message=f"row {i} is informational",
            table="link",
            row=i,
        )
    html = report._repr_html_()
    # 10 issues shown by default → 40 remaining.
    assert "+40 more issues" in html


def test_validation_report_repr_html_includes_spec_version() -> None:
    """When spec_version is set it shows up in the card metadata."""
    report = ValidationReport(spec_version="0.97", source="x.gmns")
    html = report._repr_html_()
    assert "0.97" in html


# ---------------------------------------------------------------------------
# EditResult
# ---------------------------------------------------------------------------


def test_edit_result_repr_html_shows_diff_counts() -> None:
    """The diff line surfaces +/-/~ counts and the edit identity."""
    edit = Edit(op="add_rows", table="link", payload={"rows": [{"id": 1}, {"id": 2}]})
    diff = Diff(edit=edit, rows_added=2, rows_removed=0, rows_changed=0)
    res = EditResult(
        edit=edit,
        diff=diff,
        rollback_data=None,
        applied_at=datetime(2026, 5, 22, 9, 30, 0),
    )
    html = res._repr_html_()
    assert html.startswith("<div")
    assert "+2 added" in html
    assert "-0 removed" in html
    assert "~0 changed" in html
    assert "add_rows" in html
    assert "link" in html


def test_edit_result_repr_html_includes_session_and_timestamp() -> None:
    """The session id (when set) and applied_at timestamp appear in the body."""
    edit = Edit(op="delete_rows", table="node", payload={})
    diff = Diff(edit=edit, rows_added=0, rows_removed=5, rows_changed=0)
    res = EditResult(
        edit=edit,
        diff=diff,
        rollback_data={"snapshot": []},
        applied_at=datetime(2026, 5, 22, 14, 15, 0),
        session_id="sess-abc",
    )
    html = res._repr_html_()
    assert "sess-abc" in html
    assert "2026-05-22" in html


# ---------------------------------------------------------------------------
# Escaping — the only contract that's load-bearing for security
# ---------------------------------------------------------------------------


def test_repr_html_escapes_user_input_in_table_name() -> None:
    """A hostile table name renders escaped; no raw ``<script>`` in the HTML."""
    engine = PandasEngine()
    t = Table(name="<script>alert(1)</script>", expr=engine.from_records([{"a": 1}]), engine=engine)
    html = t._repr_html_()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_repr_html_escapes_user_input_in_package_table_names() -> None:
    """A package whose table key contains HTML metacharacters escapes them."""
    engine = PandasEngine()
    t = Table(name="x<y>", expr=engine.from_records([{"a": 1}]), engine=engine)
    pkg = Package.from_tables({"x<y>": t})
    html = pkg._repr_html_()
    assert "<y>" not in html
    assert "&lt;y&gt;" in html


def test_repr_html_escapes_user_input_in_report_messages() -> None:
    """A hostile message string renders escaped in the issue table."""
    report = ValidationReport()
    report.add(
        severity=Severity.ERROR,
        category=Category.SCHEMA,
        code="schema.required",
        message="<img src=x onerror=alert(1)>",
        table="link",
    )
    html = report._repr_html_()
    assert "<img" not in html
    assert "&lt;img" in html
