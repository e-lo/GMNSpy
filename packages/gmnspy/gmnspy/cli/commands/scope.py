"""``gmnspy scope`` — read-only network-aware scope builders (issue #88).

Each subcommand builds a :class:`NetworkScope` from a seed and prints
``{node_count, link_count, node_ids, link_ids}``. ``gmnspy.scope`` is
part of core (no extra needed) but the underlying :class:`GraphIndex`
requires igraph (the ``[clean]`` extra) — surface a typed error if
igraph is absent.

Domain errors raised by ``gmnspy.scope`` (subclasses of ``ScopeError``)
are converted to clean CLI exits with a red message; non-domain
exceptions propagate.
"""

from __future__ import annotations

from pathlib import Path

import typer
from datagrove.cli.render import render_dict

from gmnspy import Network

from .._extras import require_extra
from .._helpers import summarise_scope

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the ``scope`` sub-app on ``app``."""
    scope_app = typer.Typer(no_args_is_help=True, help="Build a NetworkScope and print its (links, nodes) sets.")
    app.add_typer(scope_app, name="scope")

    @scope_app.command(name="from-nodes")
    def scope_from_nodes_cmd(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        node_ids: list[int] = typer.Argument(..., help="Seed node ids."),
        path_between: bool = typer.Option(True, "--path-between/--no-path-between"),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Build a scope from seed node ids and print its (links, nodes) sets."""
        scope_mod = _import_scope()
        ScopeError = scope_mod.ScopeError

        net = Network.from_source(source)
        try:
            scope = scope_mod.from_nodes(net, node_ids, path_between=path_between)
        except ScopeError as exc:
            typer.secho(f"error: {exc}", fg="red", err=True)
            raise typer.Exit(code=1) from exc
        render_dict(summarise_scope(scope), json_out=json_out, title=f"gmnspy scope from-nodes: {source}")

    @scope_app.command(name="from-node")
    def scope_from_node_cmd(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        node_id: int = typer.Argument(..., help="Seed node id."),
        network_buffer: str = typer.Option(
            "0.5mi", "--network-buffer", help="Distance with unit (e.g. '0.5mi', '800m')."
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Scope = all nodes within ``--network-buffer`` network-distance of ``node_id``."""
        scope_mod = _import_scope()
        ScopeError = scope_mod.ScopeError

        net = Network.from_source(source)
        try:
            scope = scope_mod.from_node(net, node_id, network_buffer=network_buffer)
        except ScopeError as exc:
            typer.secho(f"error: {exc}", fg="red", err=True)
            raise typer.Exit(code=1) from exc
        render_dict(summarise_scope(scope), json_out=json_out, title=f"gmnspy scope from-node: {source}")

    @scope_app.command(name="connected-component")
    def scope_connected_component_cmd(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        seed_node_id: int = typer.Argument(..., help="Seed node id whose component to return."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Scope = the weakly-connected component containing ``seed_node_id``."""
        scope_mod = _import_scope()
        ScopeError = scope_mod.ScopeError

        net = Network.from_source(source)
        try:
            scope = scope_mod.connected_component(net, seed_node_id)
        except ScopeError as exc:
            typer.secho(f"error: {exc}", fg="red", err=True)
            raise typer.Exit(code=1) from exc
        render_dict(summarise_scope(scope), json_out=json_out, title=f"gmnspy scope connected-component: {source}")

    @scope_app.command(name="from-zone")
    def scope_from_zone_cmd(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        zone_ids: list[int] = typer.Argument(..., help="Zone ids whose nodes (+ incident links) to include."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Scope = all nodes with ``zone_id`` in ``zone_ids`` plus their incident links."""
        scope_mod = _import_scope()
        ScopeError = scope_mod.ScopeError

        net = Network.from_source(source)
        try:
            scope = scope_mod.from_zone(net, zone_ids)
        except ScopeError as exc:
            typer.secho(f"error: {exc}", fg="red", err=True)
            raise typer.Exit(code=1) from exc
        render_dict(summarise_scope(scope), json_out=json_out, title=f"gmnspy scope from-zone: {source}")


def _import_scope():
    """Resolve :mod:`gmnspy.scope` — core module but its index ops need igraph at call time.

    ``gmnspy.scope`` itself is part of the core install (no extra needed),
    so the import never fails; the helper exists so future error handling
    (e.g. wrapping the igraph optional-dep hint on .from_node) lands in
    one place. Routed through :func:`require_extra` for consistency with
    the clean / mcp / server commands.
    """
    return require_extra("gmnspy.scope", "clean")
