"""Tests for `gmnspy app` and its viz / select-serve aliases."""

import pytest
from gmnspy.cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def served(monkeypatch, tmp_path):
    """Capture the session handed to serve() instead of starting uvicorn; isolate config."""
    monkeypatch.setenv("GMNSPY_CONFIG_DIR", str(tmp_path / "user"))
    monkeypatch.chdir(tmp_path)
    captured = []
    monkeypatch.setattr("gmnspy.workbench.serve", captured.append)
    return captured


def test_app_opens_sources_and_applies_flag_overrides(served, rdu_source):
    result = runner.invoke(app, ["app", rdu_source, "--port", "9301", "--basemap", "esri"])
    assert result.exit_code == 0, result.output
    (session,) = served
    assert session.registry.ids() == ["rdu-i40"]
    assert (session.settings.app.port, session.settings.viz.basemap) == (9301, "esri")
    assert session.loaded.sources["app.port"] == "session"
    assert "http://127.0.0.1:9301" in result.output


def test_app_with_no_sources_starts_empty(served):
    assert runner.invoke(app, ["app"]).exit_code == 0
    assert len(served[0].registry) == 0


def test_app_bad_source_exits_1(served, tmp_path):
    result = runner.invoke(app, ["app", str(tmp_path / "missing")])
    assert result.exit_code == 1 and "could not open" in result.output and served == []


def test_app_bad_flag_value_exits_2(served):
    result = runner.invoke(app, ["app", "--provider", "gpt"])
    assert result.exit_code == 2 and "invalid settings" in result.output


def test_viz_is_an_alias(served, rdu_source):
    result = runner.invoke(app, ["viz", rdu_source, "--port", "9302"])
    assert result.exit_code == 0 and "gmnspy app" in result.output
    assert served[0].settings.app.port == 9302


def test_select_serve_is_an_alias(served, rdu_source):
    result = runner.invoke(app, ["select-serve", rdu_source, "--provider", "stub"])
    assert result.exit_code == 0 and served[0].registry.ids() == ["rdu-i40"]
