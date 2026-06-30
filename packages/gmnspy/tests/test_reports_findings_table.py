"""Tests for :mod:`gmnspy.reports.findings_table` — CSV/XLSX writers.

These writers are the spreadsheet half of the CLI's report-output
options (``gmnspy validate --csv`` / ``--xlsx``). They take a flat
``list[Issue]`` so non-validation Issue sources (quality rules, graph
checks) can also be exported through the same path.
"""

from __future__ import annotations

import csv

import pytest
from datagrove.reports import Category, Issue, Severity
from gmnspy.reports import write_findings_csv, write_findings_xlsx


def _sample_issues() -> list[Issue]:
    """A small representative issue set covering optional fields + extra."""
    return [
        Issue(
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            code="schema.required",
            message="link.from_node_id row 0: value is null",
            table="link",
            column="from_node_id",
            row=0,
            fix_hint="Provide a value for from_node_id.",
        ),
        Issue(
            severity=Severity.WARNING,
            category=Category.FOREIGN_KEY,
            code="fk.missing_target",
            message="link row 12: from_node_id=99 not found in node.node_id",
            table="link",
            column="from_node_id",
            row=12,
            extra={"target_table": "node", "target_value": 99},
        ),
        Issue(
            severity=Severity.INFO,
            category=Category.STRUCTURAL,
            code="structural.optional_missing",
            message="optional table 'segment' not present",
        ),
    ]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_write_findings_csv_round_trip(tmp_path):
    """CSV reads back as the same rows we wrote."""
    issues = _sample_issues()
    out = tmp_path / "findings.csv"

    write_findings_csv(issues, out)

    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 3
    assert rows[0]["severity"] == "error"
    assert rows[0]["code"] == "schema.required"
    assert rows[0]["table"] == "link"
    assert rows[0]["column"] == "from_node_id"
    assert rows[0]["row"] == "0"
    assert "value is null" in rows[0]["message"]
    assert "Provide a value" in rows[0]["fix_hint"]


def test_write_findings_csv_empty_list_writes_header_only(tmp_path):
    """An empty issue list still writes a usable file (header row only)."""
    out = tmp_path / "empty.csv"
    write_findings_csv([], out)
    text = out.read_text(encoding="utf-8")
    # Header exists (so downstream tools see the columns) but no data rows.
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "severity" in lines[0]
    assert "code" in lines[0]


def test_write_findings_csv_extra_is_serialized_as_json(tmp_path):
    """``extra`` payload survives as a JSON column so spreadsheet users can read it."""
    import json

    out = tmp_path / "findings.csv"
    write_findings_csv(_sample_issues(), out)
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    # FK row had extra={"target_table": "node", "target_value": 99}
    fk_row = next(r for r in rows if r["code"] == "fk.missing_target")
    extra = json.loads(fk_row["extra"]) if fk_row["extra"] else {}
    assert extra == {"target_table": "node", "target_value": 99}


def test_write_findings_csv_handles_none_columns_as_empty(tmp_path):
    """``table=None`` / ``row=None`` etc. render as empty CSV cells, not literal 'None'."""
    out = tmp_path / "findings.csv"
    write_findings_csv(_sample_issues(), out)
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    cross_cutting = next(r for r in rows if r["code"] == "structural.optional_missing")
    assert cross_cutting["table"] == ""
    assert cross_cutting["column"] == ""
    assert cross_cutting["row"] == ""


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def test_write_findings_xlsx_opens_with_openpyxl(tmp_path):
    """The written file must round-trip through ``openpyxl.load_workbook``."""
    openpyxl = pytest.importorskip("openpyxl")

    out = tmp_path / "findings.xlsx"
    write_findings_xlsx(_sample_issues(), out)

    wb = openpyxl.load_workbook(out, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    assert "severity" in header
    assert "code" in header
    # 3 data rows + 1 header row.
    assert len(rows) == 4


def test_write_findings_xlsx_empty_list_writes_header_only(tmp_path):
    """An empty issue list still produces a valid workbook with just the header row."""
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "empty.xlsx"
    write_findings_xlsx([], out)
    wb = openpyxl.load_workbook(out, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert len(rows) == 1
    assert "severity" in rows[0]


def test_write_findings_xlsx_without_openpyxl_raises_helpful_error(tmp_path, monkeypatch):
    """When ``openpyxl`` isn't installed, the error must mention ``[reports]`` extra."""
    import sys

    # Hide openpyxl from importlib for the duration of the test.
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    out = tmp_path / "findings.xlsx"
    with pytest.raises(ImportError, match=r"\[reports\]"):
        write_findings_xlsx(_sample_issues(), out)
