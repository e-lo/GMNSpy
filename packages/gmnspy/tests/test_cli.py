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


def test_generic_validate_still_works_under_gmnspy():
    """The inherited datagrove `validate` command still works on a GMNS network."""
    result = runner.invoke(app, ["validate", "--json", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "issues" in payload
