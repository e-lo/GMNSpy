"""Tests for `gmnspy app` and its viz / select-serve aliases."""

import json
from pathlib import Path

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


def test_app_warns_on_public_bind(served):
    result = runner.invoke(app, ["app", "--host", "0.0.0.0"])
    assert result.exit_code == 0, result.output
    assert "0.0.0.0" in result.output
    assert "no authentication" in result.output
    assert "session" in result.output  # names the source layer that set app.host


def test_app_loopback_bind_has_no_warning(served):
    result = runner.invoke(app, ["app"])
    assert result.exit_code == 0, result.output
    assert "no authentication" not in result.output


def test_viz_passes_url_source_unmangled():
    """A ``Path`` argument would collapse ``https://`` to ``https:/``; ``viz`` must take a raw string."""
    url = "https://example.invalid/net"
    result = runner.invoke(app, ["viz", url])
    assert result.exit_code == 1
    assert url in result.output


def test_select_serve_passes_url_source_unmangled():
    url = "https://example.invalid/net"
    result = runner.invoke(app, ["select-serve", url])
    assert result.exit_code == 1
    assert url in result.output


def test_app_resolves_relative_source_to_absolute_path(served, monkeypatch, rdu_source):
    monkeypatch.chdir(Path(rdu_source).parent)
    relative = Path(rdu_source).name
    result = runner.invoke(app, ["app", relative])
    assert result.exit_code == 0, result.output
    (session,) = served
    recorded_source = session.history[0].action["source"]
    assert Path(recorded_source).is_absolute()
    assert recorded_source == str(Path(rdu_source).resolve())


def test_cli_sources_outside_allowed_roots_are_trusted_for_the_session(served, monkeypatch, rdu_source, tmp_path):
    """A path typed on the command line is the user's explicit choice: the CLI allows exactly that path."""
    monkeypatch.setenv("GMNSPY_IO__ALLOWED_ROOTS", json.dumps([str(tmp_path / "elsewhere")]))
    result = runner.invoke(app, ["app", rdu_source])
    assert result.exit_code == 0, result.output
    (session,) = served
    roots = session.settings.io.allowed_roots
    assert str(Path(rdu_source).resolve()) in roots and str((tmp_path / "elsewhere").resolve()) in roots
    assert session.loaded.sources["io.allowed_roots"] == "session" and "allowing" in result.output
    assert session.registry.ids() == ["rdu-i40"]


def test_cli_does_not_widen_roots_when_already_allowed(served, monkeypatch, rdu_source):
    monkeypatch.setenv("GMNSPY_IO__ALLOWED_ROOTS", json.dumps([str(Path(rdu_source).parent)]))
    result = runner.invoke(app, ["app", rdu_source])
    assert result.exit_code == 0 and "allowing" not in result.output
    assert served[0].loaded.sources["io.allowed_roots"] == "env"
