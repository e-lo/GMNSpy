"""Tests for the ``gmnspy bench-suite`` CLI command.

Smoke-level: the command's contract is a structured document on stdout (json /
csv / md). We assert exit codes + shape, not wall-clock numbers.
"""

from __future__ import annotations

import json

import pytest
from gmnspy.cli.app import app
from typer.testing import CliRunner

# Each test runs the real benchmark suite on the fixture.
pytestmark = pytest.mark.slow

runner = CliRunner()


@pytest.fixture(scope="module")
def viz_pack_suite_doc():
    """Run the viz_pack suite once (JSON); markdown rendering is checked from these same results."""
    # viz_pack only keeps it fast and avoids the [nl] extra dependency.
    result = runner.invoke(app, ["bench-suite", "--sizes", "S", "--operations", "viz_pack", "--repeats", "1"])
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_bench_suite_json_viz_only_small(viz_pack_suite_doc):
    doc = viz_pack_suite_doc
    assert doc["schema_version"] == "1"
    assert any(r["operation"] == "viz_pack" for r in doc["results"])


def test_bench_suite_markdown_format(viz_pack_suite_doc):
    """Markdown rendering of the same results the JSON test already produced (no second suite run)."""
    from gmnspy.bench import report

    rendered = report.render_markdown(viz_pack_suite_doc)
    assert "## viz_pack" in rendered
    assert "## Caveats" in rendered


def test_bench_suite_rejects_unknown_format():
    result = runner.invoke(app, ["bench-suite", "--sizes", "S", "--operations", "viz_pack", "--format", "bogus"])
    assert result.exit_code != 0
