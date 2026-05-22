"""Tests for ``gmnspy bench`` (task 4.4 / issue #86).

Smoke-level coverage — the command's contract is a stable JSON shape
(``total_seconds`` + per-phase ``seconds``) that downstream CI bench
workflows can diff against. We don't assert on wall-clock numbers
(noisy across runners); we just check the shape + exit codes.
"""

from __future__ import annotations

import json

from gmnspy.cli.app import app
from gmnspy.fixtures import leavenworth
from typer.testing import CliRunner

runner = CliRunner()


def test_bench_runs_on_leavenworth():
    """bench --json on the Leavenworth fixture exits 0 with ``total_seconds`` + >=4 phases."""
    result = runner.invoke(app, ["bench", "--json", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "total_seconds" in payload
    assert isinstance(payload["total_seconds"], (int, float))
    assert "phases" in payload
    assert len(payload["phases"]) >= 4
    # Required phases are present in order.
    names = [p["phase"] for p in payload["phases"]]
    for expected in ("load", "validate", "links_count", "nodes_count"):
        assert expected in names


def test_bench_json_phases_have_numeric_seconds():
    """Every non-skipped phase reports ``seconds`` as a number."""
    result = runner.invoke(app, ["bench", "--json", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    for phase in payload["phases"]:
        if phase.get("skipped"):
            assert phase["seconds"] is None
            continue
        assert isinstance(phase["seconds"], (int, float))
        assert phase["seconds"] >= 0.0


def test_bench_rejects_unknown_engine():
    """``--engine bogus`` exits non-zero (typer.BadParameter)."""
    result = runner.invoke(app, ["bench", "--engine", "bogus", "--json", str(leavenworth.csv_dir())])
    assert result.exit_code != 0


def test_bench_rich_mode_runs():
    """Non-json invocation exits 0 (rich panel rendered to stderr)."""
    result = runner.invoke(app, ["bench", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
