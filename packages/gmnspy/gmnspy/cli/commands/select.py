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

from ...select.emit import to_fragment
from ...select.parse import ClaudeParser, StubParser
from ...select.resolve import resolve
from .._helpers import resolve_engine

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

    @app.command(name="select-serve")
    def select_serve(
        source: Path = typer.Argument(..., help="Path/URL to a GMNS network."),
        provider: str = typer.Option("stub", "--provider", help="Parser: stub | claude."),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
        port: int = typer.Option(8848, "--port", help="Bind port."),
    ) -> None:
        """Serve the interactive selection map: type an utterance, see it on the network.

        Loads the network once, then runs a local MapLibre web app where each
        utterance is parsed, resolved, and drawn (selection highlighted, gore/
        merge anchors marked) over a basemap. Requires the ``[server]`` extra.
        """
        import uvicorn

        from ...select.webapp import build_app

        net = Network.from_source(source, engine=resolve_engine(engine))
        links = net.links.to_pandas() if hasattr(net.links, "to_pandas") else net.links.execute()
        nodes = net.nodes.to_pandas() if hasattr(net.nodes, "to_pandas") else net.nodes.execute()
        typer.echo(f"gmnspy select map on http://{host}:{port}  ({len(links)} links, provider={provider})")
        uvicorn.run(build_app(links, nodes, provider=provider), host=host, port=port)


def _emit(payload: dict, json_out: bool) -> None:
    if json_out:
        typer.echo(json.dumps(payload, default=str))
    else:
        render_dict(payload)
