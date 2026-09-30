"""``gmnspy viz`` — interactive network viewer (deck.gl + MapLibre).

Loads a network once and serves the viewer web app: the whole (sub)network
rendered from binary typed-arrays, hover-to-inspect links, and NL selection
highlighting. Requires the ``[server]`` extra.
"""
from __future__ import annotations

from pathlib import Path

import typer

from gmnspy import Network

from .._helpers import resolve_engine

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the ``viz`` command on ``app``."""

    @app.command(name="viz")
    def viz(
        source: Path = typer.Argument(..., help="Path/URL to a GMNS network."),
        provider: str = typer.Option("stub", "--provider", help="NL parser: stub | claude."),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
        port: int = typer.Option(8850, "--port", help="Bind port."),
    ) -> None:
        """Serve the interactive network viewer at http://host:port."""
        import uvicorn

        from ...viz.server import build_app

        net = Network.from_source(source, engine=resolve_engine(engine))
        links = net.links.to_pandas() if hasattr(net.links, "to_pandas") else net.links.execute()
        nodes = net.nodes.to_pandas() if hasattr(net.nodes, "to_pandas") else net.nodes.execute()
        typer.echo(f"gmnspy viz on http://{host}:{port}  ({len(links)} links, {len(nodes)} nodes)")
        uvicorn.run(build_app(links, nodes, provider=provider), host=host, port=port)
