"""``gmnspy info`` — GMNS-aware network metadata.

Replaces the generic ``info`` registered by :mod:`datagrove.cli.app` with
one that adds GMNS-specific context: spec version + the named-table
summary (links, nodes, …) rather than a flat resource list.
"""

from __future__ import annotations

from pathlib import Path

import typer
from datagrove.cli.render import render_dict

from gmnspy import Network

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the GMNS-aware ``info`` command on ``app``.

    typer's second registration under the same name wins, so this
    cleanly overrides the inherited datagrove ``info`` and existing
    invocations like ``gmnspy info <path>`` keep working unchanged.
    """

    @app.command(name="info")
    def gmns_info(
        source: Path = typer.Argument(..., help="Path / URL to a GMNS network."),
        spec_version: str = typer.Option(None, "--spec", help="Override the default GMNS spec version."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout instead of rich panels."),
    ) -> None:
        """Print GMNS-aware metadata about ``source`` — spec version + table summary."""
        net = Network.from_source(source, spec_version=spec_version)
        # Build tables as a LIST OF OBJECTS (not a list of names or a
        # name-keyed dict) so the --json output is naturally jq-able:
        #     gmnspy info --json $LV | jq '.tables[] | {name, rows}'
        # Each entry carries fields that an agent or shell pipeline
        # is likely to want without a second pass.
        tables = []
        for name in sorted(net.tables.keys()):
            tables.append(
                {
                    "name": name,
                    "rows": net.safe_count(name),
                }
            )
        data = {
            "name": net.spec.name,
            "source": str(source),
            "spec_version": net.spec_version,
            "engine": type(net.engine).__name__,
            "links": net.safe_count("link"),
            "nodes": net.safe_count("node"),
            "table_count": len(net.tables),
            "tables": tables,
        }
        render_dict(data, json_out=json_out, title=f"gmnspy info: {source}")
