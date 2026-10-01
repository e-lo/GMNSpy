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

#: Other canonical GMNS tables to expose in the data-table view when present.
_EXTRA_TABLES = ("lanes", "segments", "segment_lanes", "zones", "movements", "link_tod")


def _as_pandas(table):
    return table.to_pandas() if hasattr(table, "to_pandas") else table.execute()


def _extra_tables(net) -> dict:
    """Additional GMNS tables the network carries, kept **lazy** (best-effort).

    Returns the datagrove ``Table`` objects (not materialized) so the data-table
    view pages/sorts/filters them through the engine — on duckdb a large
    ``lane``/``segment_lane`` table never fully crosses into memory. Keyed by
    singular GMNS name (``lane``, ``segment``, …) for the pk convention.
    """
    out = {}
    for accessor in _EXTRA_TABLES:
        try:
            tbl = getattr(net, accessor)
            if tbl is not None and tbl.count() > 0:
                out[accessor[:-1] if accessor.endswith("s") else accessor] = tbl
        except (AttributeError, KeyError, ValueError, FileNotFoundError):
            continue
    return out


def register(app: typer.Typer) -> None:
    """Register the ``viz`` command on ``app``."""

    @app.command(name="viz")
    def viz(
        source: Path = typer.Argument(..., help="Path/URL to a GMNS network."),
        provider: str = typer.Option("stub", "--provider", help="NL parser: stub | claude."),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        basemap: str = typer.Option("positron", "--basemap", help="Basemap: positron | esri (both keyless)."),
        host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
        port: int = typer.Option(8850, "--port", help="Bind port."),
    ) -> None:
        """Serve the interactive network viewer at http://host:port.

        Basemap is keyless: ``positron`` (OpenFreeMap vector Positron, default) or
        ``esri`` (Esri Light Gray). No API key or secret is required.
        """
        import uvicorn

        from ...viz.server import build_app

        net = Network.from_source(source, engine=resolve_engine(engine))
        links = _as_pandas(net.links)
        nodes = _as_pandas(net.nodes)
        extra = _extra_tables(net)
        extra_note = f", +{len(extra)} table(s): {', '.join(extra)}" if extra else ""
        typer.echo(
            f"gmnspy viz on http://{host}:{port}  "
            f"({len(links)} links, {len(nodes)} nodes{extra_note}; basemap={basemap})"
        )
        uvicorn.run(build_app(links, nodes, provider=provider, basemap=basemap, tables=extra), host=host, port=port)
