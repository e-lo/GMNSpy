"""Unit tests for the interactive single-file HTML renderer (task 2.2, issue #61).

The renderer consumes the same :class:`~datagrove.validation.ValidationReport`
as the rich + JSON renderers. Output is a single self-contained HTML string —
CSS + JS + data embedded — that can be opened in a browser as-is.

These tests assert the contract documented in
``docs/architecture.md`` §6.3:

- severity ordering (ERROR → WARNING → INFO → DATA_QUALITY)
- filter controls (table, severity, category, code)
- click-to-expand row context
- embedded JSON payload for "Export JSON"
- Vega-Lite map section when geo-located issues are present
- offline-safe by default (no external CSS / no external JS *except* the
  documented Vega-Lite CDN tag, used only when geo data triggers the map)

The map view's runtime Vega-Lite script tag is a deliberate offline-mode
trade-off — see ``render_html`` docstring.
"""

from __future__ import annotations

import json
import re

import pytest
from datagrove.validation import (
    Category,
    Issue,
    Severity,
    ValidationReport,
    render_html,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _issue(
    severity: Severity = Severity.ERROR,
    category: Category = Category.SCHEMA,
    code: str = "schema.required",
    message: str = "x",
    table: str | None = None,
    column: str | None = None,
    row: int | None = None,
    fix_hint: str | None = None,
    extra: dict | None = None,
) -> Issue:
    return Issue(
        severity=severity,
        category=category,
        code=code,
        message=message,
        table=table,
        column=column,
        row=row,
        fix_hint=fix_hint,
        extra=extra or {},
    )


@pytest.fixture
def mixed_report() -> ValidationReport:
    """A report containing one issue of each severity for ordering tests."""
    report = ValidationReport(spec_version="0.97", source="leavenworth.gmns")
    # Add deliberately OUT OF ORDER — the renderer must re-sort.
    report.add_issue(
        _issue(
            Severity.INFO,
            Category.STRUCTURAL,
            "structural.optional",
            "info-msg-marker",
            table="segment",
        )
    )
    report.add_issue(
        _issue(
            Severity.DATA_QUALITY,
            Category.DATA_QUALITY,
            "quality.high_speed",
            "quality-msg-marker",
            table="link",
        )
    )
    report.add_issue(
        _issue(
            Severity.WARNING,
            Category.SYNC_STATE,
            "sync.fk_stale",
            "warning-msg-marker",
            table="node",
        )
    )
    report.add_issue(
        _issue(
            Severity.ERROR,
            Category.SCHEMA,
            "schema.required",
            "error-msg-marker",
            table="link",
            column="from_node_id",
            row=0,
            fix_hint="Provide a value for from_node_id.",
        )
    )
    return report


@pytest.fixture
def geo_report() -> ValidationReport:
    """A report with three issues carrying geo coords in ``extra``."""
    report = ValidationReport(spec_version="0.97", source="leavenworth.gmns")
    report.add_issue(
        _issue(
            Severity.ERROR,
            Category.SCHEMA,
            "schema.bad_geometry",
            "bad-geom-1",
            table="link",
            row=0,
            extra={"lon": -120.6612, "lat": 47.5963},
        )
    )
    report.add_issue(
        _issue(
            Severity.WARNING,
            Category.DATA_QUALITY,
            "quality.high_speed_residential",
            "speed-issue-2",
            table="link",
            row=4,
            extra={"x": -120.6650, "y": 47.5975, "v_kph": 80},
        )
    )
    report.add_issue(
        _issue(
            Severity.WARNING,
            Category.STRUCTURAL,
            "structural.dangling_node",
            "dangling-3",
            table="node",
            row=11,
            extra={"lon": -120.6701, "lat": 47.5982},
        )
    )
    return report


# ---------------------------------------------------------------------------
# Output shape + contract
# ---------------------------------------------------------------------------


class TestRenderHtmlShape:
    def test_render_html_returns_string_starting_with_doctype(self, mixed_report):
        out = render_html(mixed_report)
        assert isinstance(out, str)
        assert out.lstrip().lower().startswith("<!doctype html>")
        # Closes too — basic well-formedness check.
        assert "</html>" in out.lower()

    def test_render_html_includes_all_severity_groups(self, mixed_report):
        """Severity section headings appear in canonical order."""
        out = render_html(mixed_report)
        # Section heading text — uppercased per the template convention.
        for label in ("ERROR", "WARNING", "INFO", "DATA_QUALITY"):
            assert label in out, f"missing severity heading: {label}"
        # Ordering check.
        idx_error = out.index("ERROR")
        idx_warning = out.index("WARNING")
        idx_info = out.index("INFO")
        idx_quality = out.index("DATA_QUALITY")
        assert idx_error < idx_warning < idx_info < idx_quality

    def test_render_html_includes_issue_messages(self, mixed_report):
        out = render_html(mixed_report)
        for msg in (
            "error-msg-marker",
            "warning-msg-marker",
            "info-msg-marker",
            "quality-msg-marker",
        ):
            assert msg in out, f"missing message text: {msg}"

    def test_render_html_includes_summary_counts(self, mixed_report):
        """Header shows the per-severity numeric badges."""
        out = render_html(mixed_report)
        # 1 of each severity in the mixed fixture.
        # Look for the digits within the badge spans — pattern, not exact match
        # of surrounding whitespace, so the template can format badges freely.
        assert re.search(r'class="badge error"[^>]*>\s*1\b', out)
        assert re.search(r'class="badge warning"[^>]*>\s*1\b', out)
        assert re.search(r'class="badge info"[^>]*>\s*1\b', out)
        assert re.search(r'class="badge data_quality"[^>]*>\s*1\b', out)

    def test_render_html_is_self_contained_no_external_css_js_except_map(self, mixed_report):
        """No external CSS/JS allowed in the report — offline-safe.

        Exception (documented in render_html docstring): the Vega-Lite map
        section pulls Vega-Lite from a CDN at runtime when geo coords are
        present. The non-geo fixture used here MUST be fully offline.
        """
        out = render_html(mixed_report)
        assert '<link rel="stylesheet" href="http' not in out, (
            "External stylesheet found — report must be self-contained. Inline all CSS via the template."
        )
        assert '<script src="http' not in out, (
            "External script found — only the Vega-Lite map section may "
            "load from a CDN, and it's gated behind the presence of geo "
            "coords (this fixture has none)."
        )

    def test_render_html_includes_embedded_json(self, mixed_report):
        """The 'Export JSON' button needs the raw report-data blob inline."""
        out = render_html(mixed_report)
        m = re.search(
            r'<script[^>]*id="report-data"[^>]*type="application/json"[^>]*>(.*?)</script>',
            out,
            flags=re.DOTALL,
        )
        assert m is not None, "embedded report-data script tag missing"
        data = json.loads(m.group(1))
        assert data == mixed_report.to_dict()

    def test_render_html_clean_report(self):
        """An empty report renders without error and declares CLEAN."""
        report = ValidationReport(source="empty.gmns")
        out = render_html(report)
        assert isinstance(out, str)
        assert "empty.gmns" in out
        # Verdict copy — case-insensitive 'clean'.
        assert "CLEAN" in out


# ---------------------------------------------------------------------------
# Geo / map handling
# ---------------------------------------------------------------------------


class TestRenderHtmlMap:
    def test_render_html_with_geo_data(self, geo_report):
        """Issues with lon/lat (or x/y) trigger the map section."""
        out = render_html(geo_report, include_map=True)
        assert 'id="map-section"' in out
        assert 'id="map"' in out

    def test_render_html_without_geo_data_skips_map(self, mixed_report):
        """No geo coords anywhere → no map section even when opted in."""
        out = render_html(mixed_report, include_map=True)
        assert 'id="map-section"' not in out

    def test_render_html_include_map_false_skips_map(self, geo_report):
        """`include_map=False` overrides geo presence."""
        out = render_html(geo_report, include_map=False)
        assert 'id="map-section"' not in out


# ---------------------------------------------------------------------------
# Misc API
# ---------------------------------------------------------------------------


class TestRenderHtmlAPI:
    def test_render_html_title_override(self, mixed_report):
        title = "Custom Title For This Run"
        out = render_html(mixed_report, title=title)
        # The title should land in the <title> tag and the <h1> header.
        assert f"<title>{title}</title>" in out
        assert title in out

    def test_to_html_shortcut_method(self, mixed_report):
        """`report.to_html()` must equal `render_html(report)`."""
        assert mixed_report.to_html() == render_html(mixed_report)

    def test_to_html_shortcut_passes_kwargs(self, geo_report):
        """to_html forwards title + include_map."""
        a = geo_report.to_html(title="Custom", include_map=False)
        b = render_html(geo_report, title="Custom", include_map=False)
        assert a == b


# ---------------------------------------------------------------------------
# Doctest example — keeps the docstring honest
# ---------------------------------------------------------------------------


def test_render_html_doctest_example():
    """The Examples block in render_html's docstring must actually run.

    We run a focused doctest on just the ``render_html`` symbol (not the
    full module) so this test only fails when the function we own here
    regresses — sibling renderers' doctests are exercised via pytest's
    ``--doctest-modules`` collection, which uses its own flag set.

    ELLIPSIS is enabled to match the project's pytest doctest config.
    """
    import doctest

    from datagrove.validation.report import render_html

    finder = doctest.DocTestFinder()
    runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
    tests = finder.find(render_html)
    assert tests, "render_html has no doctest examples"
    for t in tests:
        runner.run(t)
    results = runner.summarize(verbose=False)
    assert results.failed == 0, f"doctest failures in render_html: {results}"


# ---------------------------------------------------------------------------
# Packaging — template resources must be discoverable
# ---------------------------------------------------------------------------


def test_render_html_jinja2_template_loadable():
    """`importlib.resources` can read the bundled template files.

    Guards against packaging regressions where the .j2/.css/.js files in
    `datagrove/validation/templates/` are missing from the wheel.
    """
    from importlib import resources

    files = resources.files("datagrove.validation.templates")
    assert (files / "report.html.j2").is_file()
    assert (files / "report.css").is_file()
    assert (files / "report.js").is_file()
