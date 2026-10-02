"""``gmnspy viz`` — alias of ``gmnspy app SOURCE`` (the viewer is now the GMNSpy Workbench)."""

from __future__ import annotations

from pathlib import Path

import typer

from .workbench import run_workbench

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the ``viz`` alias on ``app``."""

    @app.command(name="viz")
    def viz(
        source: Path = typer.Argument(..., help="Path/URL to a GMNS network."),
        provider: str = typer.Option(None, "--provider", help="NL parser: stub | claude."),
        engine: str = typer.Option(
            None, "--engine", help="Ignored: DuckDB is the only engine (kept for compatibility)."
        ),
        basemap: str = typer.Option(None, "--basemap", help="Basemap: positron | esri (both keyless)."),
        host: str = typer.Option(None, "--host", help="Bind host."),
        port: int = typer.Option(None, "--port", help="Bind port."),
    ) -> None:
        """Serve the network viewer: now an alias of ``gmnspy app SOURCE``."""
        del engine  # accepted for backward compatibility only
        typer.echo("note: `gmnspy viz` is now `gmnspy app`", err=True)
        run_workbench([str(source)], provider=provider, basemap=basemap, host=host, port=port)
