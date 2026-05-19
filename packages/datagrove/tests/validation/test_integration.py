"""End-to-end smoke test of the validation report contract.

Builds a representative report (3 errors + 2 warnings + 1 info + 1
data_quality), then exercises both renderers in the same shape that
the validators (tasks 2.3-2.6) and the HTML renderer (task 2.2) will.
"""

from __future__ import annotations

import json

from datagrove.validation import (
    Category,
    Severity,
    ValidationReport,
    render_json,
    render_rich,
)


def _build_full_report() -> ValidationReport:
    report = ValidationReport(spec_version="0.97", source="leavenworth.gmns")

    # 3 errors
    report.add(
        severity=Severity.ERROR,
        category=Category.SCHEMA,
        code="schema.required",
        message="link.from_node_id row 0: value is null",
        table="link",
        column="from_node_id",
        row=0,
        fix_hint="Provide a value for from_node_id.",
    )
    report.add(
        severity=Severity.ERROR,
        category=Category.FOREIGN_KEY,
        code="fk.missing_target",
        message="link row 12: from_node_id=99 not found in node.node_id",
        table="link",
        column="from_node_id",
        row=12,
        fix_hint="Add a node row with node_id=99, or remove the link.",
    )
    report.add(
        severity=Severity.ERROR,
        category=Category.STRUCTURAL,
        code="structural.missing_table",
        message="required table 'link' is missing from the package",
        table=None,
        fix_hint="Add a link.csv or link.parquet to the data package.",
    )

    # 2 warnings
    report.add(
        severity=Severity.WARNING,
        category=Category.SYNC_STATE,
        code="sync.fk_stale",
        message="link FK to node was last validated against an older content hash",
        table="link",
        fix_hint="Re-run validation; or set strict=False to suppress.",
    )
    report.add(
        severity=Severity.WARNING,
        category=Category.SCHEMA,
        code="schema.enum",
        message="link.facility_type row 4: value 'mystery' not in enum",
        table="link",
        column="facility_type",
        row=4,
    )

    # 1 info
    report.add(
        severity=Severity.INFO,
        category=Category.STRUCTURAL,
        code="structural.optional_missing",
        message="optional table 'segment' is not present — skipping segment checks",
    )

    # 1 data quality
    report.add(
        severity=Severity.DATA_QUALITY,
        category=Category.DATA_QUALITY,
        code="quality.high_speed_residential",
        message="link row 27: 65 mph speed limit on a residential facility",
        table="link",
        row=27,
        fix_hint="Confirm speed_limit; residential typically <= 30 mph.",
    )

    return report


def test_report_contains_all_seven_issues():
    report = _build_full_report()
    assert report.count() == 7
    assert report.count(Severity.ERROR) == 3
    assert report.count(Severity.WARNING) == 2
    assert report.count(Severity.INFO) == 1
    assert report.count(Severity.DATA_QUALITY) == 1


def test_rich_output_contains_all_seven_codes():
    report = _build_full_report()
    rendered = render_rich(report)
    for code in (
        "schema.required",
        "fk.missing_target",
        "structural.missing_table",
        "sync.fk_stale",
        "schema.enum",
        "structural.optional_missing",
        "quality.high_speed_residential",
    ):
        assert code in rendered, f"missing code {code} in rich output"


def test_json_output_contains_all_seven_issues_and_correct_counts():
    report = _build_full_report()
    data = json.loads(render_json(report))
    assert len(data["issues"]) == 7
    assert data["summary"] == {
        "error": 3,
        "warning": 2,
        "info": 1,
        "data_quality": 1,
        "is_clean": False,
    }
    assert data["spec_version"] == "0.97"
    assert data["source"] == "leavenworth.gmns"


def test_round_trip_via_json():
    """The JSON snapshot must round-trip without losing any issue payload."""
    report = _build_full_report()
    data = json.loads(render_json(report))
    rehydrated_codes = sorted(i["code"] for i in data["issues"])
    original_codes = sorted(i.code for i in report.issues)
    assert rehydrated_codes == original_codes
