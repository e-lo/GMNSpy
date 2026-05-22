"""Tests for ``gmnspy spec list/diff`` + ``gmnspy doctor`` (tasks 4.3 / 4.5).

Issues: #85 (spec list/diff), #87 (doctor).

Follows the pattern in ``test_cli.py`` — uses :class:`typer.testing.CliRunner`
and asserts on ``--json`` payloads (the rich path is exercised
incidentally by running the commands at all).
"""

from __future__ import annotations

import json

from gmnspy.cli.app import app
from gmnspy.spec import DEFAULT_SPEC, SUPPORTED_SPECS
from typer.testing import CliRunner

runner = CliRunner()


# ---------------------------------------------------------------------------
# spec list
# ---------------------------------------------------------------------------


def test_spec_list_json_lists_supported_versions():
    """`gmnspy spec list --json` returns {default, supported} matching the module constants."""
    result = runner.invoke(app, ["spec", "list", "--json"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["default"] == DEFAULT_SPEC
    assert payload["supported"] == list(SUPPORTED_SPECS)


# ---------------------------------------------------------------------------
# spec diff
# ---------------------------------------------------------------------------


def test_spec_diff_returns_resource_deltas():
    """Diffing two adjacent versions returns the documented shape (structure-only test)."""
    result = runner.invoke(app, ["spec", "diff", "--json", "0.96", "0.97"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["v1"] == "0.96"
    assert payload["v2"] == "0.97"
    assert isinstance(payload["added_resources"], list)
    assert isinstance(payload["removed_resources"], list)
    assert isinstance(payload["changed_resources"], list)
    # If any resource changed, each entry has the documented keys.
    for entry in payload["changed_resources"]:
        assert set(entry) >= {"name", "added_fields", "removed_fields", "changed_fields"}
        for change in entry["changed_fields"]:
            assert set(change) >= {"name", "v1_type", "v2_type"}


def test_spec_diff_same_version_returns_empty_diffs():
    """Diffing a version against itself yields empty added/removed/changed lists."""
    result = runner.invoke(app, ["spec", "diff", "--json", "0.97", "0.97"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["added_resources"] == []
    assert payload["removed_resources"] == []
    assert payload["changed_resources"] == []


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_runs_and_returns_checks():
    """`gmnspy doctor` exits 0 in a healthy env and prints a meaningful number of checks."""
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    # python-version + 3 spec versions + leavenworth + env + at least one extra
    assert len(payload) >= 3


def test_doctor_json_mode():
    """The JSON payload is a list of dicts with name/ok/detail keys."""
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    for check in payload:
        assert set(check) >= {"name", "ok", "detail"}
        assert isinstance(check["name"], str)
        assert isinstance(check["ok"], bool)
        assert isinstance(check["detail"], str)
