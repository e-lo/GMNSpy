"""``gmnspy app`` — the GMNSpy Workbench: map + tables + selection over one live session.

Requires the ``[server]`` extra. ``gmnspy viz`` and ``gmnspy select-serve`` are
aliases that call :func:`run_workbench`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import typer

__all__ = ["register", "run_workbench"]


def run_workbench(
    sources: Sequence[str],
    *,
    provider: str | None = None,
    basemap: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Build a session from settings + flag overrides, open ``sources``, and serve it (blocks)."""
    from gmnspy import workbench
    from gmnspy.config import SettingsError
    from gmnspy.workbench.actions import OpenNetwork

    flags = {"select.provider": provider, "viz.basemap": basemap, "app.host": host, "app.port": port}
    try:
        session = workbench.Session(overrides={k: v for k, v in flags.items() if v is not None})
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    for source in sources:
        resolved = str(source)
        path = Path(resolved)
        if path.exists():
            resolved = str(path.resolve())
        try:
            session.dispatch(OpenNetwork(source=resolved))
        except workbench.ActionError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
    app_settings = session.settings.app
    opened = ", ".join(session.registry.ids()) or "none (open one from the header)"
    typer.echo(f"GMNSpy Workbench on http://{app_settings.host}:{app_settings.port}  (networks: {opened})")
    workbench.serve(session)


def register(app: typer.Typer) -> None:
    """Register the ``app`` command on ``app``."""

    @app.command(name="app")
    def app_cmd(
        sources: list[str] = typer.Argument(None, help="GMNS network paths/URLs to open."),
        provider: str = typer.Option(None, "--provider", help="NL parser: stub | claude (default: settings)."),
        basemap: str = typer.Option(None, "--basemap", help="Basemap: positron | esri (default: settings)."),
        host: str = typer.Option(None, "--host", help="Bind host (default: settings, 127.0.0.1)."),
        port: int = typer.Option(None, "--port", help="Bind port (default: settings, 8850)."),
    ) -> None:
        """Serve the GMNSpy Workbench: open, inspect, and select on GMNS networks in the browser."""
        run_workbench(sources or [], provider=provider, basemap=basemap, host=host, port=port)
