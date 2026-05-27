"""Unit tests for the foundational report types.

These tests exercise the small public contract of
:mod:`datagrove.reports.types`: the two str-enums, the frozen
:class:`Issue` value object, and the mutable :class:`ValidationReport`
that aggregates them across a run.

The downstream validators (schema / FK / structural / sync_state — Phase
2 tasks 2.3-2.6) consume these types verbatim, so any change here is a
breaking change to the validation contract — keep the surface small.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime

import pytest
from datagrove.reports import (
    Category,
    Issue,
    Severity,
    ValidationReport,
)

# ---------------------------------------------------------------------------
# Severity + Category enums
# ---------------------------------------------------------------------------


class TestSeverityEnum:
    def test_is_str_enum(self):
        """Severity members ARE strings — required for stable JSON round-trip."""
        assert isinstance(Severity.ERROR, str)
        assert Severity.ERROR == "error"

    def test_round_trip_from_value(self):
        """Severity("error") recovers the canonical member."""
        assert Severity("error") is Severity.ERROR
        assert Severity("warning") is Severity.WARNING
        assert Severity("info") is Severity.INFO

    def test_three_levels_present(self):
        """The three-level model (Error/Warning/Info) is the contract.

        Data quality is a :class:`Category`, not a Severity — a
        quality finding picks Warning or Info based on its urgency.
        """
        assert {s.value for s in Severity} == {"error", "warning", "info"}


class TestCategoryEnum:
    def test_is_str_enum(self):
        assert isinstance(Category.SCHEMA, str)
        assert Category.SCHEMA == "schema"

    def test_round_trip_from_value(self):
        assert Category("schema") is Category.SCHEMA
        assert Category("structural") is Category.STRUCTURAL
        assert Category("foreign_key") is Category.FOREIGN_KEY
        assert Category("sync_state") is Category.SYNC_STATE
        assert Category("data_quality") is Category.DATA_QUALITY

    def test_all_five_categories_present(self):
        assert {c.value for c in Category} == {
            "schema",
            "structural",
            "foreign_key",
            "sync_state",
            "data_quality",
        }


# ---------------------------------------------------------------------------
# Issue dataclass — frozen, hashable, fully populated
# ---------------------------------------------------------------------------


class TestIssue:
    def test_required_fields_only(self):
        """severity / category / code / message are required; rest default to None."""
        issue = Issue(
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            code="schema.required",
            message="link.from_node_id row 12: value is null",
        )
        assert issue.severity is Severity.ERROR
        assert issue.category is Category.SCHEMA
        assert issue.code == "schema.required"
        assert issue.message.startswith("link.from_node_id")
        assert issue.table is None
        assert issue.column is None
        assert issue.row is None
        assert issue.fix_hint is None
        assert issue.extra == {}

    def test_full_population(self):
        issue = Issue(
            severity=Severity.WARNING,
            category=Category.FOREIGN_KEY,
            code="fk.missing_target",
            message="link row 12: from_node_id=99 not found in node.node_id",
            table="link",
            column="from_node_id",
            row=12,
            fix_hint="Add a node row with node_id=99, or remove the link.",
            extra={"target_table": "node", "target_field": "node_id"},
        )
        assert issue.table == "link"
        assert issue.column == "from_node_id"
        assert issue.row == 12
        assert issue.fix_hint.startswith("Add a node")
        assert issue.extra["target_table"] == "node"

    def test_is_frozen(self):
        """Frozen so an Issue can be safely held in a report after data mutates."""
        issue = Issue(
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            code="schema.required",
            message="x",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            issue.message = "mutated"  # type: ignore[misc]

    def test_is_hashable(self):
        """Hashable so issues can dedupe via set membership."""
        a = Issue(severity=Severity.ERROR, category=Category.SCHEMA, code="schema.required", message="x")
        b = Issue(severity=Severity.ERROR, category=Category.SCHEMA, code="schema.required", message="x")
        c = Issue(severity=Severity.ERROR, category=Category.SCHEMA, code="schema.required", message="y")
        # equal payload => equal hash + equality
        assert hash(a) == hash(b)
        assert a == b
        # different payload => unequal
        assert a != c
        assert {a, b, c} == {a, c}

    def test_code_is_required(self):
        """code has no default — it's the stable identifier callers grep for."""
        with pytest.raises(TypeError):
            Issue(severity=Severity.ERROR, category=Category.SCHEMA, message="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ValidationReport — mutation surface
# ---------------------------------------------------------------------------


def _issue(
    severity: Severity = Severity.ERROR,
    category: Category = Category.SCHEMA,
    code: str = "schema.required",
    message: str = "x",
    table: str | None = None,
) -> Issue:
    return Issue(severity=severity, category=category, code=code, message=message, table=table)


class TestValidationReportMutation:
    def test_empty_report_defaults(self):
        report = ValidationReport()
        assert report.issues == []
        assert report.metadata == {}
        assert report.spec_version is None
        assert report.source is None
        assert isinstance(report.created_at, datetime)

    def test_add_issue_appends(self):
        report = ValidationReport()
        issue = _issue()
        report.add_issue(issue)
        assert report.issues == [issue]

    def test_add_builder_constructs_and_returns(self):
        """add() is the convenience builder validators call directly."""
        report = ValidationReport()
        returned = report.add(
            severity=Severity.WARNING,
            category=Category.FOREIGN_KEY,
            code="fk.missing_target",
            message="x",
            table="link",
        )
        assert isinstance(returned, Issue)
        assert returned.severity is Severity.WARNING
        assert returned.table == "link"
        assert report.issues == [returned]


# ---------------------------------------------------------------------------
# ValidationReport — query surface
# ---------------------------------------------------------------------------


@pytest.fixture
def mixed_report() -> ValidationReport:
    """Tiny report with each severity across two tables, plus a data-quality finding."""
    report = ValidationReport(spec_version="0.97", source="leavenworth.gmns")
    report.add_issue(_issue(Severity.ERROR, Category.SCHEMA, "schema.required", "e1", "link"))
    report.add_issue(_issue(Severity.ERROR, Category.FOREIGN_KEY, "fk.missing_target", "e2", "link"))
    report.add_issue(_issue(Severity.WARNING, Category.SYNC_STATE, "sync.fk_stale", "w1", "node"))
    report.add_issue(_issue(Severity.INFO, Category.STRUCTURAL, "structural.optional_missing", "i1"))
    # Quality finding: severity carries urgency, category=DATA_QUALITY carries the source.
    report.add_issue(_issue(Severity.WARNING, Category.DATA_QUALITY, "quality.high_speed", "q1", "link"))
    return report


class TestValidationReportQuery:
    def test_by_severity(self, mixed_report):
        errors = mixed_report.by_severity(Severity.ERROR)
        assert len(errors) == 2
        assert [i.code for i in errors] == ["schema.required", "fk.missing_target"]
        assert mixed_report.by_severity(Severity.INFO) == [
            i for i in mixed_report.issues if i.severity is Severity.INFO
        ]

    def test_by_category(self, mixed_report):
        fks = mixed_report.by_category(Category.FOREIGN_KEY)
        assert len(fks) == 1
        assert fks[0].code == "fk.missing_target"

    def test_by_table(self, mixed_report):
        link_issues = mixed_report.by_table("link")
        assert len(link_issues) == 3
        assert all(i.table == "link" for i in link_issues)

    def test_by_table_excludes_none_tables(self, mixed_report):
        """Issues with table=None (cross-cutting) MUST NOT match a table query."""
        assert all(i.table is not None for i in mixed_report.by_table("node"))

    def test_count_total(self, mixed_report):
        assert mixed_report.count() == 5

    def test_count_by_severity(self, mixed_report):
        # Two WARNING: one sync-state plus the data-quality finding.
        assert mixed_report.count(Severity.ERROR) == 2
        assert mixed_report.count(Severity.WARNING) == 2
        assert mixed_report.count(Severity.INFO) == 1

    def test_count_by_category_data_quality(self, mixed_report):
        """Category.DATA_QUALITY is the dimension that survived the dedupe."""
        assert len(mixed_report.by_category(Category.DATA_QUALITY)) == 1


# ---------------------------------------------------------------------------
# ValidationReport — verdict properties
# ---------------------------------------------------------------------------


class TestValidationReportVerdict:
    def test_empty_is_clean(self):
        report = ValidationReport()
        assert report.has_errors is False
        assert report.has_warnings is False
        assert report.is_clean is True

    def test_info_only_is_clean(self):
        """Info alone — including INFO data-quality findings — does NOT break is_clean."""
        report = ValidationReport()
        report.add_issue(_issue(Severity.INFO, Category.STRUCTURAL, "structural.optional", "i"))
        report.add_issue(_issue(Severity.INFO, Category.DATA_QUALITY, "quality.missing_optional", "q"))
        assert report.has_errors is False
        assert report.has_warnings is False
        assert report.is_clean is True

    def test_warning_breaks_clean(self):
        report = ValidationReport()
        report.add_issue(_issue(Severity.WARNING, Category.SYNC_STATE, "sync.fk_stale", "w"))
        assert report.has_warnings is True
        assert report.has_errors is False
        assert report.is_clean is False

    def test_error_breaks_clean(self):
        report = ValidationReport()
        report.add_issue(_issue(Severity.ERROR, Category.SCHEMA, "schema.required", "e"))
        assert report.has_errors is True
        assert report.is_clean is False


# ---------------------------------------------------------------------------
# ValidationReport — serialization
# ---------------------------------------------------------------------------


class TestValidationReportSerialization:
    def test_to_dict_is_json_serializable(self, mixed_report):
        """to_dict() output must round-trip through json.dumps without custom encoders."""
        dumped = json.dumps(mixed_report.to_dict())
        recovered = json.loads(dumped)
        assert isinstance(recovered, dict)
        assert recovered["summary"]["error"] == 2

    def test_to_dict_stable_keyset(self, mixed_report):
        """Top-level keys are the contract — downstream HTML renderer + MCP rely on them."""
        d = mixed_report.to_dict()
        assert set(d.keys()) == {
            "report_version",
            "spec_version",
            "source",
            "created_at",
            "metadata",
            "summary",
            "issues",
        }

    def test_to_dict_summary_keys(self, mixed_report):
        d = mixed_report.to_dict()
        assert set(d["summary"].keys()) == {"error", "warning", "info", "data_quality", "is_clean"}
        assert d["summary"]["is_clean"] is False

    def test_to_dict_issue_keys(self, mixed_report):
        d = mixed_report.to_dict()
        issue_dict = d["issues"][0]
        assert set(issue_dict.keys()) == {
            "severity",
            "category",
            "code",
            "message",
            "table",
            "column",
            "row",
            "fix_hint",
            "extra",
        }
        # Enums serialize as their .value string, not the repr
        assert issue_dict["severity"] == "error"
        assert issue_dict["category"] == "schema"

    def test_to_dict_created_at_isoformat(self, mixed_report):
        d = mixed_report.to_dict()
        # iso format is parseable
        datetime.fromisoformat(d["created_at"])

    def test_to_json_is_parseable(self, mixed_report):
        recovered = json.loads(mixed_report.to_json())
        assert recovered["summary"]["error"] == 2

    def test_to_json_indent_kwarg(self, mixed_report):
        compact = mixed_report.to_json(indent=0)
        # indent=0 still emits newlines, but no leading spaces on lines
        assert "\n" in compact
