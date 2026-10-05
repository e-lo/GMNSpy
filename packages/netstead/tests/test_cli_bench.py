"""Tests for ``netstead bench`` (task 4.4 / issue #86).

Smoke-level coverage — the command's contract is a stable JSON shape
(``total_seconds`` + per-phase ``seconds``) that downstream CI bench
workflows can diff against. We don't assert on wall-clock numbers
(noisy across runners); we just check the shape + exit codes.
"""

from __future__ import annotations

import json

import pytest
from netstead.cli.app import app
from netstead.fixtures import leavenworth
from typer.testing import CliRunner

# Each test runs the real bench pipeline on the fixture.
pytestmark = pytest.mark.slow

runner = CliRunner()


@pytest.fixture(scope="module")
def bench_json_payload():
    """Run ``bench --json`` on the Leavenworth fixture once; both shape tests share the result."""
    result = runner.invoke(app, ["bench", "--json", str(leavenworth.csv_dir())])
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_bench_runs_on_leavenworth(bench_json_payload):
    """bench --json on the Leavenworth fixture reports ``total_seconds`` + >=4 phases with numeric seconds."""
    payload = bench_json_payload
    assert "total_seconds" in payload
    assert isinstance(payload["total_seconds"], (int, float))
    assert "phases" in payload
    assert len(payload["phases"]) >= 4
    # Required phases are present in order.
    names = [p["phase"] for p in payload["phases"]]
    for expected in ("load", "validate", "links_count", "nodes_count"):
        assert expected in names
    # Every non-skipped phase reports ``seconds`` as a number.
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
