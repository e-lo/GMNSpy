"""Unit tests for the rich-console and JSON renderers.

The HTML renderer (task 2.2 / issue #61) lives alongside in
``render.py`` and consumes the same
:class:`~datagrove.reports.ValidationReport` instance.
"""

from __future__ import annotations

import json

import pytest
from datagrove.reports import (
    Category,
    Issue,
    Severity,
    ValidationReport,
    render_json,
    render_rich,
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
    fix_hint: str | None = None,
) -> Issue:
    return Issue(
        severity=severity,
        category=category,
        code=code,
        message=message,
        table=table,
        fix_hint=fix_hint,
    )


@pytest.fixture
def mixed_report() -> ValidationReport:
    """A report containing one issue of each severity for ordering tests."""
    report = ValidationReport(spec_version="0.97", source="leavenworth.gmns")
    # Add deliberately OUT OF ORDER — the renderer must re-sort.
    report.add_issue(_issue(Severity.INFO, Category.STRUCTURAL, "structural.optional", "info-msg"))
    # Data-quality findings use Category.DATA_QUALITY with a real severity.
    # Here it's INFO (awareness-only) so it sorts to the bottom alongside
    # the structural info above.
    report.add_issue(
        _issue(
            Severity.INFO,
            Category.DATA_QUALITY,
            "quality.high_speed",
            "quality-msg",
            table="link",
        )
    )
    report.add_issue(
        _issue(
            Severity.WARNING,
            Category.SYNC_STATE,
            "sync.fk_stale",
            "warning-msg",
            table="node",
        )
    )
    report.add_issue(
        _issue(
            Severity.ERROR,
            Category.SCHEMA,
            "schema.required",
            "error-msg",
            table="link",
            fix_hint="Provide a value for from_node_id.",
        )
    )
    return report


# ---------------------------------------------------------------------------
# render_rich
# ---------------------------------------------------------------------------


class TestRenderRich:
    def test_returns_non_empty_string(self, mixed_report):
        out = render_rich(mixed_report)
        assert isinstance(out, str)
        assert len(out) > 0

    def test_includes_source_in_header(self, mixed_report):
        assert "leavenworth.gmns" in render_rich(mixed_report)

    def test_includes_spec_version_in_header(self, mixed_report):
        assert "0.97" in render_rich(mixed_report)

    def test_severity_ordering(self, mixed_report):
        """Renderer MUST group ERROR -> WARNING -> INFO.

        Both ``info-msg`` (structural) and ``quality-msg`` (data-quality)
        are ``Severity.INFO`` and therefore appear in the same trailing
        section.
        """
        out = render_rich(mixed_report)
        # Locate each severity's distinguishing message text
        idx_error = out.index("error-msg")
        idx_warning = out.index("warning-msg")
        idx_info = out.index("info-msg")
        idx_quality = out.index("quality-msg")
        assert idx_error < idx_warning < idx_info
        assert idx_error < idx_warning < idx_quality

    def test_fix_hint_rendered_when_present(self, mixed_report):
        assert "Provide a value for from_node_id." in render_rich(mixed_report)

    def test_clean_empty_report_renders(self):
        """Empty report must render cleanly, declaring the run clean."""
        report = ValidationReport(source="empty.gmns")
        out = render_rich(report)
        assert isinstance(out, str)
        assert "empty.gmns" in out
        # Verdict line shows the run is clean
        assert "clean" in out.lower()

    def test_string_dunder_matches_render_rich(self, mixed_report):
        """__str__ is documented as an alias of render_rich(self)."""
        assert str(mixed_report) == render_rich(mixed_report)

    def test_codes_appear_in_output(self, mixed_report):
        out = render_rich(mixed_report)
        for code in ("schema.required", "sync.fk_stale", "structural.optional", "quality.high_speed"):
            assert code in out


# ---------------------------------------------------------------------------
# render_json
# ---------------------------------------------------------------------------


class TestRenderJson:
    def test_returns_parseable_json(self, mixed_report):
        recovered = json.loads(render_json(mixed_report))
        assert isinstance(recovered, dict)

    def test_includes_report_version(self, mixed_report):
        d = json.loads(render_json(mixed_report))
        assert d["report_version"] == "1"

    def test_round_trip_preserves_counts(self, mixed_report):
        d = json.loads(render_json(mixed_report))
        assert d["summary"]["error"] == 1
        assert d["summary"]["warning"] == 1
        # Two INFO: the structural one and the data-quality one (which is
        # now Severity.INFO + Category.DATA_QUALITY rather than the
        # removed Severity.DATA_QUALITY).
        assert d["summary"]["info"] == 2
        # Category-based count survives — see ValidationReport.to_dict.
        assert d["summary"]["data_quality"] == 1
        assert len(d["issues"]) == 4

    def test_round_trip_preserves_issue_payload(self, mixed_report):
        d = json.loads(render_json(mixed_report))
        # Find the schema.required error and check every field round-trips
        err = next(i for i in d["issues"] if i["code"] == "schema.required")
        assert err["severity"] == "error"
        assert err["category"] == "schema"
        assert err["table"] == "link"
        assert err["fix_hint"] == "Provide a value for from_node_id."

    def test_indent_kwarg(self, mixed_report):
        out = render_json(mixed_report, indent=4)
        # 4-space indent shows up in the body of the formatted JSON
        assert '\n    "' in out

    def test_empty_report_renders(self):
        d = json.loads(render_json(ValidationReport()))
        assert d["issues"] == []
        assert d["summary"]["is_clean"] is True
