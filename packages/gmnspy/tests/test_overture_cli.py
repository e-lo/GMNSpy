"""Tests for ``gmnspy build --source overture``.

Exercises the Overture branch of the CLI end-to-end against the committed local
GeoParquet fixture (``--data-root``), so no network / S3 is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

from gmnspy.cli.app import app
from typer.testing import CliRunner

runner = CliRunner()

FIXTURE_ROOT = str(Path(__file__).resolve().parent / "fixtures" / "overture")


def test_build_overture_bbox_writes_network(tmp_path):
    dest = tmp_path / "net"
    result = runner.invoke(
        app,
        [
            "build",
            str(dest),
            "--bbox",
            "-0.5,-0.5,0.5,0.5",
            "--source",
            "overture",
            "--data-root",
            FIXTURE_ROOT,
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"] == "overture"
    assert payload["links"] == 5
    assert payload["nodes"] == 4
    assert dest.exists()


def test_overture_only_options_rejected_for_osm():
    result = runner.invoke(
        app,
        ["build", "out", "--bbox", "0,0,1,1", "--source", "osm", "--data-root", FIXTURE_ROOT],
    )
    assert result.exit_code != 0
    assert "overture" in result.output.lower()


def test_empty_area_exits_nonzero_with_message(tmp_path):
    result = runner.invoke(
        app,
        [
            "build",
            str(tmp_path / "net"),
            "--bbox",
            "10,10,11,11",
            "--source",
            "overture",
            "--data-root",
            FIXTURE_ROOT,
        ],
    )
    assert result.exit_code == 1
    assert "no Overture segments matched" in result.output
