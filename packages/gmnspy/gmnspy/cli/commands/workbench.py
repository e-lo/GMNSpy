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
    from gmnspy.workbench.paths import allowed_roots, is_allowed, is_url

    flags = {"select.provider": provider, "viz.basemap": basemap, "app.host": host, "app.port": port}
    overrides = {k: v for k, v in flags.items() if v is not None}
    resolved = [s if is_url(s) else str(Path(s).resolve()) for s in map(str, sources)]
    try:
        session = workbench.Session(overrides=overrides)
        # Sources named on the command line are trusted: allow exactly those paths for this session.
        extra = [s for s in resolved if not is_url(s) and not is_allowed(s, session.settings)]
        if extra:
            roots = [str(r) for r in allowed_roots(session.settings)] + extra
            session = workbench.Session(overrides={**overrides, "io.allowed_roots": roots})
            typer.echo(f"note: allowing {', '.join(extra)} for this session (io.allowed_roots)", err=True)
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    for source in resolved:
        try:
            session.dispatch(OpenNetwork(source=source))
        except workbench.ActionError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
    from gmnspy.workbench.server import is_loopback_host

    app_settings = session.settings.app
    if not is_loopback_host(app_settings.host):
        source = session.loaded.sources.get("app.host", "default")
        typer.echo(
            f"WARNING: binding to {app_settings.host!r} (set by the {source} layer) exposes the Workbench "
            "to other machines on the network. It has no authentication and can open local files — only "
            "do this on a trusted network.",
            err=True,
        )
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
