"""``gmnspy select`` — natural-language selection of GMNS elements.

Parses an utterance into a structured intent, resolves it against a network,
and emits a validated GMNS selection fragment (or the ambiguity/not-found
diagnostics). Selection only — no edit is applied.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from datagrove.cli.render import render_dict

from gmnspy import Network

from .._helpers import resolve_engine
from ...select.emit import to_fragment
from ...select.parse import ClaudeParser, StubParser
from ...select.resolve import resolve

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the ``select`` command on ``app``."""

    @app.command(name="select")
    def select(
        utterance: str = typer.Argument(..., help='e.g. "I-40 EB between Harrison Ave and NC 54".'),
        source: Path = typer.Argument(..., help="Path/URL to a GMNS network."),
        provider: str = typer.Option("stub", "--provider", help="Parser: stub | claude."),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Resolve a natural-language selection to GMNS link/node ids.

        Prints the validated selection fragment on success. On an ambiguous
        result it prints the fragment plus candidate notes; on not-found it
        prints diagnostics and exits non-zero.
        """
        parser = ClaudeParser() if provider == "claude" else StubParser()
        intent = parser.parse(utterance)

        net = Network.from_source(source, engine=resolve_engine(engine))
        result = resolve(intent, net)

        if result.status == "not_found":
            payload = {"status": result.status, "diagnostics": result.diagnostics}
            _emit(payload, json_out)
            raise typer.Exit(code=1)

        fragment = to_fragment(result)
        if result.status == "ambiguous":
            fragment["_status"] = "ambiguous"
            fragment["_diagnostics"] = result.diagnostics
        _emit(fragment, json_out)


def _emit(payload: dict, json_out: bool) -> None:
    if json_out:
        typer.echo(json.dumps(payload, default=str))
    else:
        render_dict(payload)
