"""Tests for the `gmnspy select` CLI command (orchestration + output)."""

import json
from importlib import resources

import pandas as pd
import pytest
import typer
from gmnspy.cli.commands import select as select_cmd
from typer.testing import CliRunner


class _Table:
    def __init__(self, df):
        self._df = df

    def to_pandas(self):
        return self._df


class _FakeNet:
    def __init__(self, links, nodes):
        self.links = _Table(links)
        self.nodes = _Table(nodes)


@pytest.fixture
def patched_net(monkeypatch):
    base = resources.files("gmnspy.fixtures.rdu_i40").joinpath("parquet")
    links = pd.read_parquet(base.joinpath("link.parquet"))
    nodes = pd.read_parquet(base.joinpath("node.parquet"))
    monkeypatch.setattr(select_cmd.Network, "from_source", lambda *a, **k: _FakeNet(links, nodes))


def _run(args):
    app = typer.Typer()
    select_cmd.register(app)

    # register a second no-op command so Typer treats `select` as a subcommand
    @app.command(name="_noop")
    def _noop():  # pragma: no cover
        pass

    return CliRunner().invoke(app, args)


def test_cli_resolved_emits_fragment_json(patched_net):
    res = _run(
        [
            "select",
            "I-40 EB between South Miami Boulevard and Airport Boulevard",
            "dummy",
            "--provider",
            "stub",
            "--json",
        ]
    )
    assert res.exit_code == 0, res.output
    frag = json.loads(res.stdout)
    assert frag["links"]["link_id"][0] == 5021
    assert frag["from"]["node_id"] == 170505098


def test_cli_not_found_exits_nonzero(patched_net):
    res = _run(
        ["select", "I-40 EB between Nowhere Street and Airport Boulevard", "dummy", "--provider", "stub", "--json"]
    )
    assert res.exit_code != 0


def test_cli_unknown_provider_exits_2(tmp_path, monkeypatch):
    monkeypatch.setenv("GMNSPY_CONFIG_DIR", str(tmp_path / "user"))
    monkeypatch.chdir(tmp_path)
    res = _run(["select", "Main Street", "dummy", "--provider", "gpt"])
    assert res.exit_code == 2 and "invalid settings" in res.output


def test_cli_missing_key_exits_1_with_how_to(tmp_path, monkeypatch):
    monkeypatch.setenv("GMNSPY_CONFIG_DIR", str(tmp_path / "user"))
    monkeypatch.chdir(tmp_path)
    for name in ("GMNSPY_OPENAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    res = _run(["select", "Main Street", "dummy", "--provider", "openai"])
    assert res.exit_code == 1 and "OpenAI: no API key is configured" in res.output
