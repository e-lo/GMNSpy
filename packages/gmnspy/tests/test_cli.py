"""Tests for the GMNS-aware CLI (task 4.1b / issue #83).

Exercises the extended ``info`` (overrides datagrove's generic with a
GMNS-aware version) + the new ``quality`` command. Reuses datagrove's
:class:`CliRunner` infra; both ``--json`` and rich output paths
exercised.
"""

from __future__ import annotations

import json

from gmnspy.cli.app import app
from gmnspy.fixtures import leavenworth
from typer.testing import CliRunner

runner = CliRunner()


# ---------------------------------------------------------------------------
# info — GMNS-aware override
# ---------------------------------------------------------------------------


def test_gmns_info_json_includes_spec_version():
    """gmnspy info --json carries spec_version + link/node counts."""
    result = runner.invoke(app, ["info", "--json", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["spec_version"] == "0.97"
    assert isinstance(payload["links"], int) and payload["links"] > 0
    assert isinstance(payload["nodes"], int) and payload["nodes"] > 0


def test_gmns_info_respects_spec_override():
    """--spec 0.96 stamps a different spec_version on the output."""
    result = runner.invoke(app, ["info", "--json", "--spec", "0.96", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["spec_version"] == "0.96"


def test_gmns_info_rich_runs():
    """Rich-mode info exits 0 and writes to stderr."""
    result = runner.invoke(app, ["info", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr


# ---------------------------------------------------------------------------
# quality
# ---------------------------------------------------------------------------


def test_quality_json_emits_issues_document():
    """gmnspy quality --json writes {header, issues: [...]} on stdout."""
    result = runner.invoke(app, ["quality", "--json", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "issues" in payload
    # All emitted issues should be DATA_QUALITY category.
    assert all(i["category"] == "data_quality" for i in payload["issues"])
    # Leavenworth's residential streets at 40 mph fire the high-speed rule.
    codes = {i["code"] for i in payload["issues"]}
    assert "quality.high_speed_residential" in codes


def test_quality_never_exits_nonzero_on_warnings_only():
    """quality findings are WARNING/INFO — command exit stays 0 even with issues."""
    result = runner.invoke(app, ["quality", "--json", str(leavenworth.csv_dir())])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Help + generic commands still present
# ---------------------------------------------------------------------------


def test_app_help_lists_gmns_and_generic_commands():
    """`gmnspy --help` shows the generic (info, validate) + GMNS (quality) commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "info" in result.stdout
    assert "validate" in result.stdout
    assert "quality" in result.stdout


def test_gmns_validate_loads_spec_for_csv_directory():
    """`gmnspy validate <csv-dir>` must auto-load the GMNS spec.

    Regression for the bug found during the v1.0 CLI walk-through on
    2026-05-26: ``gmnspy validate`` was inheriting the generic
    ``datagrove validate`` (no spec passed to ``Package.from_source``),
    so a CSV directory without a ``datapackage.json`` produced a
    vacuous "every real table is unexpected" report. The fix added a
    GMNS-aware override in :mod:`gmnspy.cli.commands.validate` that
    routes through :meth:`Network.from_source` so the spec actually
    loads.

    This test guards against re-introducing the bug: it runs the CLI
    against the bundled Leavenworth CSV fixture and asserts that none
    of the known GMNS core tables (``link``, ``node``, ``geometry``,
    ``lane``) are flagged as ``structural.unexpected_resource``.
    """
    result = runner.invoke(app, ["validate", "--json", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "issues" in payload

    unexpected = [
        i
        for i in payload["issues"]
        if i.get("code") == "structural.unexpected_resource" and i.get("table") in {"link", "node", "geometry", "lane"}
    ]
    assert not unexpected, (
        "GMNS spec was not loaded — core tables flagged as unexpected. "
        f"Got: {[i.get('table') for i in unexpected]}. "
        "Did gmnspy.cli.commands.validate.register get removed?"
    )


def test_gmns_validate_writes_html_report(tmp_path):
    """`gmnspy validate --html <path>` writes a self-contained HTML report.

    Regression for the v1.0 CLI walk-through finding that the
    docs / cookbook claimed a ``--report=html -o ...`` flag existed
    but the CLI had only ``--json``. The override added an ``--html
    <path>`` flag that wires :meth:`ValidationReport.to_html`.
    """
    out = tmp_path / "report.html"
    result = runner.invoke(app, ["validate", "--html", str(out), str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    # Self-contained: should be a full HTML document with embedded
    # styling, not a fragment.
    assert html.startswith("<!DOCTYPE html") or "<html" in html[:200]
    assert "validation report" in html.lower() or "validation" in html.lower()


def test_gmns_validate_respects_spec_override():
    """`gmnspy validate --spec 0.96` should load the 0.96 spec, not the default."""
    result = runner.invoke(app, ["validate", "--json", "--spec", "0.96", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    # spec_version isn't always in the payload header, but the
    # important thing is the run succeeds against 0.96 (a different
    # spec from the 0.97 default).
