"""GMNS-aware CLI — extends :mod:`datagrove.cli.app` with GMNS commands.

Entry point: ``gmnspy = gmnspy.cli.app:app``. Starts from
:func:`datagrove.cli.app.build_app` (so users get every generic
command — ``validate``, ``info``, …) then layers GMNS-specific ones
on top:

* ``info`` — GMNS-aware: prints :attr:`Network.spec_version` + the
  named-table summary (links, nodes, segments, …) rather than the
  generic resource list.
* ``quality`` — runs the :mod:`gmnspy.quality` rule pack.
* ``spec list`` / ``spec diff`` — introspect vendored GMNS spec
  versions (task 4.3 / issue #85).
* ``doctor`` — environment + spec smoke checks (task 4.5 / issue #87).

Every command keeps the ``--json`` + ``--yes`` contract from
:mod:`datagrove.cli` so an agent that learned the datagrove surface
already knows the GMNS surface.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path

import typer
from datagrove.cli.app import build_app
from datagrove.cli.render import render_dict, render_issues, render_table
from datagrove.quality import RuleConfig, run_quality

from gmnspy import Network
from gmnspy.quality import register_all
from gmnspy.spec import DEFAULT_SPEC, SUPPORTED_SPECS, load_gmns_spec

__all__ = ["app"]

logger = logging.getLogger(__name__)


def _build_gmnspy_app() -> typer.Typer:
    """Return the GMNS-aware typer app, layered on top of the datagrove generic app.

    Pulled out as a private factory so tests can build a fresh app
    rather than relying on the module-level singleton.
    """
    gmnspy_app = build_app()
    # Stamp a gmnspy-flavoured help string over the datagrove default
    # so ``gmnspy --help`` introduces itself correctly.
    gmnspy_app.info.help = (
        "gmnspy — GMNS network CLI. Inherits the generic datagrove commands "
        "(validate, info) and adds GMNS-aware overrides + the data-quality "
        "rule pack. Add --json to any command for machine-readable output."
    )

    # Replace the generic ``info`` with a GMNS-aware one. typer's
    # second registration under the same name wins, so existing
    # behaviour for end users is unchanged.
    @gmnspy_app.command(name="info")
    def gmns_info(
        source: Path = typer.Argument(..., help="Path / URL to a GMNS network."),
        spec_version: str = typer.Option(None, "--spec", help="Override the default GMNS spec version."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout instead of rich panels."),
    ) -> None:
        """Print GMNS-aware metadata about ``source`` — spec version + table summary."""
        net = Network.from_source(source, spec_version=spec_version)
        data = {
            "name": net.spec.name,
            "source": str(source),
            "spec_version": net.spec_version,
            "engine": type(net.engine).__name__,
            "links": net.safe_count("link"),
            "nodes": net.safe_count("node"),
            "table_count": len(net.tables),
            "tables": sorted(net.tables.keys()),
        }
        render_dict(data, json_out=json_out, title=f"gmnspy info: {source}")

    @gmnspy_app.command(name="quality")
    def quality_cmd(
        source: Path = typer.Argument(..., help="Path / URL to a GMNS network."),
        spec_version: str = typer.Option(None, "--spec", help="Override the default GMNS spec version."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout instead of rich panels."),
    ) -> None:
        """Run the GMNS data-quality rule pack against ``source``.

        Each rule emits Severity.WARNING / INFO findings with category
        DATA_QUALITY. The output is a ValidationReport (rendered as a
        rich table or JSON document per ``--json``).
        """
        # Ensure rules are registered even when the entry point isn't
        # picked up (e.g. editable installs that skipped re-install).
        register_all()
        net = Network.from_source(source, spec_version=spec_version)
        report = run_quality(net, config={code: RuleConfig() for code in []})
        render_issues(report.issues, json_out=json_out, header=f"quality report: {source}")
        # Quality issues are WARNING/INFO by default — never exit non-zero
        # from this command. Callers wanting hard fail use --json + check
        # for non-empty issues themselves.

    # ------------------------------------------------------------------
    # spec — vendored GMNS spec introspection (task 4.3 / issue #85)
    # ------------------------------------------------------------------
    spec_app = typer.Typer(no_args_is_help=True, help="GMNS spec utilities — list and diff vendored versions.")
    gmnspy_app.add_typer(spec_app, name="spec")

    @spec_app.command(name="list")
    def spec_list(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a rich table."),
    ) -> None:
        """List the GMNS spec versions vendored in this build of gmnspy."""
        data = {"default": DEFAULT_SPEC, "supported": list(SUPPORTED_SPECS)}
        render_dict(data, json_out=json_out, title="gmnspy spec list")

    @spec_app.command(name="diff")
    def spec_diff(
        v1: str = typer.Argument(..., help="Baseline GMNS spec version (e.g. 0.96)."),
        v2: str = typer.Argument(..., help="Comparison GMNS spec version (e.g. 0.97)."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a rich summary."),
    ) -> None:
        """Diff two vendored GMNS spec versions resource-by-resource."""
        diff = _diff_specs(v1, v2)
        if json_out:
            render_dict(diff, json_out=True)
            return
        # Human-readable summary: one row per "changed" resource plus
        # bare lists for added/removed. Keep it compact — the JSON
        # payload is the authoritative shape.
        summary = {
            "v1": diff["v1"],
            "v2": diff["v2"],
            "added_resources": ", ".join(diff["added_resources"]) or "(none)",
            "removed_resources": ", ".join(diff["removed_resources"]) or "(none)",
            "changed_resources": ", ".join(r["name"] for r in diff["changed_resources"]) or "(none)",
        }
        render_dict(summary, json_out=False, title=f"spec diff: {v1} -> {v2}")

    # ------------------------------------------------------------------
    # doctor — environment diagnostic (task 4.5 / issue #87)
    # ------------------------------------------------------------------
    @gmnspy_app.command(name="doctor")
    def doctor(
        json_out: bool = typer.Option(False, "--json", help="Emit checks as a JSON array."),
    ) -> None:
        """Run environment + spec smoke checks. Exits non-zero on any failure."""
        checks: list[dict[str, object]] = [
            _check_python_version(),
            *_check_optional_extras(),
            *_check_spec_versions(),
            _check_leavenworth_loads(),
            _check_auto_approve_env(),
        ]
        render_table(checks, json_out=json_out, title="gmnspy doctor")
        if any(not c["ok"] for c in checks):
            raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # bench — read/validate/connectivity timing (task 4.4 / issue #86)
    # ------------------------------------------------------------------
    @gmnspy_app.command(name="bench")
    def bench(
        source: Path = typer.Argument(..., help="Path/URL to a GMNS network."),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Run read/validate/connectivity benchmarks; print timings.

        Phases timed (each via time.perf_counter):

        * ``load`` — :meth:`Network.from_source`.
        * ``validate`` — :meth:`Network.validate` (structural/schema only).
        * ``links_count`` + ``nodes_count`` — trivial materialisation sanity.
        * ``is_connected`` — full graph index build + component count
          (skipped silently when the ``[clean]`` extra is missing).

        Output is a dict with ``phases`` (list of ``{phase, seconds}``) and
        a ``total_seconds`` summary. ``--json`` writes the dict to stdout for
        machine consumption; otherwise rendered via the standard rich panel.
        """
        import time

        eng = _resolve_engine(engine)

        timings: list[dict] = []

        def _time(phase: str, fn):
            t0 = time.perf_counter()
            result = fn()
            timings.append({"phase": phase, "seconds": round(time.perf_counter() - t0, 4)})
            return result

        net = _time("load", lambda: Network.from_source(source, engine=eng))
        _time("validate", lambda: net.validate(foreign_keys=False, sync_state=False))
        _time("links_count", lambda: net.links.count())
        _time("nodes_count", lambda: net.nodes.count())
        # Connectivity needs the [clean] extra (igraph). Skip silently if not available.
        try:
            from gmnspy.semantics import is_connected

            _time("is_connected", lambda: is_connected(net))
        except ImportError:
            timings.append({"phase": "is_connected", "seconds": None, "skipped": "igraph not installed"})

        total = round(sum(t["seconds"] for t in timings if t.get("seconds") is not None), 4)
        data = {
            "source": str(source),
            "engine": type(eng).__name__,
            "total_seconds": total,
            "phases": timings,
        }
        render_dict(data, json_out=json_out, title=f"bench: {source}")

    # ------------------------------------------------------------------
    # server — self-hostable FastAPI app (task 4.10 / issue #91)
    # ------------------------------------------------------------------
    server_app = typer.Typer(no_args_is_help=True, help="Run the gmnspy self-hostable HTTP server.")
    gmnspy_app.add_typer(server_app, name="server")

    @server_app.command(name="run")
    def server_run(
        config: Path = typer.Option(None, "--config", "-c", help="Path to server config (YAML/JSON)."),
        bind: str = typer.Option(None, "--bind", help="Override config bind address (default 127.0.0.1)."),
        port: int = typer.Option(None, "--port", help="Override config port (default 8000)."),
    ) -> None:
        """Start the gmnspy HTTP server with config from ``--config``.

        Reads :class:`datagrove.api.ServerSettings` from the config
        file (or uses defaults — localhost, no packages, auth=bearer
        with no token, which fails fast on first request).

        The CLI ``--bind`` / ``--port`` flags override the matching
        config keys for one-off testing without editing the file.
        """
        # Optional-extra modules go through importlib so the
        # static contract `gmnspy.cli must not import gmnspy.server`
        # holds. The import-linter scans static imports only; runtime
        # discovery via importlib is the architecture-blessed way to
        # thread a CLI entry point into an optional submodule.
        try:
            server_module = importlib.import_module("gmnspy.server")
            api_module = importlib.import_module("datagrove.api")
            uvicorn = importlib.import_module("uvicorn")
        except ImportError as e:
            typer.secho(
                f"gmnspy server requires the [server] extra: pip install 'gmnspy[server]' ({e})",
                fg="red",
                err=True,
            )
            raise typer.Exit(code=1) from None

        settings = api_module.load_settings(config) if config else api_module.ServerSettings()
        if bind is not None:
            settings.bind = bind
        if port is not None:
            settings.port = port

        app_instance = server_module.build_app(settings)
        uvicorn.run(app_instance, host=settings.bind, port=settings.port)

    # ------------------------------------------------------------------
    # mcp serve — stateless MCP server over stdio (task 4.11 / issue #94)
    # ------------------------------------------------------------------
    mcp_app = typer.Typer(no_args_is_help=True, help="Run the gmnspy MCP server for AI-agent access.")
    gmnspy_app.add_typer(mcp_app, name="mcp")

    @mcp_app.command(name="serve")
    def mcp_serve(
        name: str = typer.Option("gmnspy", "--name", help="MCP server display name."),
    ) -> None:
        """Start the gmnspy MCP server on stdio (for Claude Desktop / Claude Code).

        Configure your MCP client to launch ``gmnspy mcp serve`` as a
        subprocess (typical example:

        .. code-block:: json

            {"mcpServers": {"gmnspy": {"command": "gmnspy", "args": ["mcp", "serve"]}}}

        ). Tools exposed: ``describe_network``, ``validate_package``,
        ``quality_check``, ``connected_components``, ``scope_from_nodes``,
        plus the generic datagrove tools.
        """
        try:
            gmnspy_mcp = importlib.import_module("gmnspy.mcp")
        except ImportError as e:
            typer.secho(
                f"gmnspy mcp requires the [mcp] extra: pip install 'gmnspy[mcp]' ({e})",
                fg="red",
                err=True,
            )
            raise typer.Exit(code=1) from None

        server = gmnspy_mcp.build_server(name=name)
        # FastMCP.run() defaults to stdio when called with no transport;
        # stdio is what MCP-host applications expect (Claude Desktop,
        # Claude Code, etc.).
        server.run()

    # ------------------------------------------------------------------
    # clean — network-editing ops (task 4.6 / issue #88)
    # ------------------------------------------------------------------
    #
    # Each subcommand wraps an op from :mod:`gmnspy.clean` (optional
    # ``[clean]`` extra). The op runs inside a :class:`Session` so we
    # get atomic rollback + a diff to show; ``--dry-run`` rolls back
    # before write so the on-disk network is unchanged. Without
    # ``--dest`` the modified network is written back over ``source``;
    # with ``--dest`` it goes to the given path (mirroring the
    # ``gmnspy info``/``validate`` convention of leaving the source
    # alone when the caller asks for somewhere else).
    clean_app = typer.Typer(no_args_is_help=True, help="GMNS network-editing ops (requires the 'clean' extra).")
    gmnspy_app.add_typer(clean_app, name="clean")

    @clean_app.command(name="simplify-geometry")
    def clean_simplify(
        source: Path = typer.Argument(..., help="Path to the GMNS network to edit."),
        dest: Path = typer.Option(
            None, "--dest", help="Where to write the modified network. Default: overwrite source."
        ),
        mode: str = typer.Option("redundant_only", "--mode", help="redundant_only or douglas_peucker."),
        tolerance: float = typer.Option(0.0, "--tolerance", help="Tolerance in CRS units (douglas_peucker only)."),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Print what would change; do not write."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Simplify link geometries on the network at ``source``."""
        clean = _import_clean()
        net, Session = _load_network_and_session_cls(source, engine)
        with Session(net) as session:
            result = clean.simplify_geometry(net, session, mode=mode, tolerance=tolerance)
            summary = _summarise_results(result, op="simplify_geometry", source=source, dest=dest, dry_run=dry_run)
            if dry_run:
                session.rollback()
            else:
                _write_network(net, source=source, dest=dest)
        render_dict(summary, json_out=json_out, title=f"gmnspy clean simplify-geometry: {source}")

    @clean_app.command(name="merge-close-nodes")
    def clean_merge(
        source: Path = typer.Argument(..., help="Path to the GMNS network to edit."),
        dest: Path = typer.Option(
            None, "--dest", help="Where to write the modified network. Default: overwrite source."
        ),
        threshold_m: float = typer.Option(5.0, "--threshold-m", help="Distance threshold in node CRS units."),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Print what would change; do not write."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Merge node pairs within ``--threshold-m`` of each other; rewrite incident links."""
        clean = _import_clean()
        net, Session = _load_network_and_session_cls(source, engine)
        with Session(net) as session:
            results = clean.merge_close_nodes(net, session, threshold_m=threshold_m)
            summary = _summarise_results(results, op="merge_close_nodes", source=source, dest=dest, dry_run=dry_run)
            if dry_run:
                session.rollback()
            else:
                _write_network(net, source=source, dest=dest)
        render_dict(summary, json_out=json_out, title=f"gmnspy clean merge-close-nodes: {source}")

    @clean_app.command(name="remove-orphans")
    def clean_remove_orphans(
        source: Path = typer.Argument(..., help="Path to the GMNS network to edit."),
        dest: Path = typer.Option(
            None, "--dest", help="Where to write the modified network. Default: overwrite source."
        ),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Print what would change; do not write."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Drop nodes with no incident links."""
        clean = _import_clean()
        net, Session = _load_network_and_session_cls(source, engine)
        with Session(net) as session:
            result = clean.remove_orphans(net, session)
            summary = _summarise_results(result, op="remove_orphans", source=source, dest=dest, dry_run=dry_run)
            if dry_run:
                session.rollback()
            else:
                _write_network(net, source=source, dest=dest)
        render_dict(summary, json_out=json_out, title=f"gmnspy clean remove-orphans: {source}")

    @clean_app.command(name="recompute-lengths")
    def clean_recompute_lengths(
        source: Path = typer.Argument(..., help="Path to the GMNS network to edit."),
        dest: Path = typer.Option(
            None, "--dest", help="Where to write the modified network. Default: overwrite source."
        ),
        geodesic: bool = typer.Option(False, "--geodesic", help="Compute haversine length in meters (WGS84)."),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Print what would change; do not write."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Recompute ``link.length`` from the inline geometry column."""
        clean = _import_clean()
        net, Session = _load_network_and_session_cls(source, engine)
        with Session(net) as session:
            result = clean.recompute_lengths(net, session, geodesic=geodesic)
            summary = _summarise_results(result, op="recompute_lengths", source=source, dest=dest, dry_run=dry_run)
            if dry_run:
                session.rollback()
            else:
                _write_network(net, source=source, dest=dest)
        render_dict(summary, json_out=json_out, title=f"gmnspy clean recompute-lengths: {source}")

    # ------------------------------------------------------------------
    # scope — network-aware scope ops (task 4.6 / issue #88)
    # ------------------------------------------------------------------
    #
    # Read-only: each subcommand builds a :class:`NetworkScope` from a
    # seed and prints {node_count, link_count, node_ids, link_ids}.
    # ``gmnspy.scope`` is part of core (no extra needed) but the
    # underlying :class:`GraphIndex` requires igraph (the [clean]
    # extra) — surface a typed error if igraph is absent.
    scope_app = typer.Typer(no_args_is_help=True, help="Build a NetworkScope and print its (links, nodes) sets.")
    gmnspy_app.add_typer(scope_app, name="scope")

    @scope_app.command(name="from-nodes")
    def scope_from_nodes_cmd(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        node_ids: list[int] = typer.Argument(..., help="Seed node ids."),
        path_between: bool = typer.Option(True, "--path-between/--no-path-between"),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Build a scope from seed node ids and print its (links, nodes) sets."""
        scope_mod = _import_scope()
        net = Network.from_source(source)
        with _scope_errors():
            scope = scope_mod.from_nodes(net, node_ids, path_between=path_between)
        render_dict(_summarise_scope(scope), json_out=json_out, title=f"gmnspy scope from-nodes: {source}")

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
        net = Network.from_source(source)
        with _scope_errors():
            scope = scope_mod.from_node(net, node_id, network_buffer=network_buffer)
        render_dict(_summarise_scope(scope), json_out=json_out, title=f"gmnspy scope from-node: {source}")

    @scope_app.command(name="connected-component")
    def scope_connected_component_cmd(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        seed_node_id: int = typer.Argument(..., help="Seed node id whose component to return."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Scope = the weakly-connected component containing ``seed_node_id``."""
        scope_mod = _import_scope()
        net = Network.from_source(source)
        with _scope_errors():
            scope = scope_mod.connected_component(net, seed_node_id)
        render_dict(_summarise_scope(scope), json_out=json_out, title=f"gmnspy scope connected-component: {source}")

    @scope_app.command(name="from-zone")
    def scope_from_zone_cmd(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        zone_ids: list[int] = typer.Argument(..., help="Zone ids whose nodes (+ incident links) to include."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Scope = all nodes with ``zone_id`` in ``zone_ids`` plus their incident links."""
        scope_mod = _import_scope()
        net = Network.from_source(source)
        with _scope_errors():
            scope = scope_mod.from_zone(net, zone_ids)
        render_dict(_summarise_scope(scope), json_out=json_out, title=f"gmnspy scope from-zone: {source}")

    # ------------------------------------------------------------------
    # index — spatial + graph index build/status/drop (task 4.6 / issue #88)
    # ------------------------------------------------------------------
    #
    # Sidecars land under ``<source.parent>/_gmnspy_indexes/`` per
    # :func:`gmnspy.indexes.cache.cache_path`. ``build`` content-hashes
    # the link table (and node table for the graph index) so a re-build
    # over identical data is a cheap no-op.
    index_app = typer.Typer(no_args_is_help=True, help="Spatial + graph index build/status/drop.")
    gmnspy_app.add_typer(index_app, name="index")

    @index_app.command(name="build")
    def index_build(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        spatial: bool = typer.Option(True, "--spatial/--no-spatial"),
        graph: bool = typer.Option(True, "--graph/--no-graph"),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Build spatial + graph indexes for the network at ``source``; cache to disk."""
        indexes = _import_indexes()
        net = Network.from_source(source)
        # Spatial index needs an inline ``geometry`` column on links;
        # auto-skip (with a logged note) rather than crashing so the
        # default ``build`` works on geometry-table-backed networks too.
        # Callers wanting to assemble + index in one go should run
        # :func:`gmnspy.semantics.assemble_link_geometry` first.
        skipped_spatial = False
        if spatial and "geometry" not in net.links.columns():
            spatial = False
            skipped_spatial = True
        with _scope_errors():
            spatial_idx, graph_idx = indexes.build_indexes(
                links=net.links,
                nodes=net.nodes if graph else None,
                spatial=spatial,
                graph=graph,
            )
        paths: list[str] = []
        if spatial_idx is not None:
            p = _save_index_sidecar(indexes, source, net, "spatial", spatial_idx, kind_target="link")
            paths.append(str(p))
        if graph_idx is not None:
            p = _save_index_sidecar(indexes, source, net, "graph", graph_idx, kind_target="link+node")
            paths.append(str(p))
        summary = {
            "source": str(source),
            "spatial": spatial_idx is not None,
            "graph": graph_idx is not None,
            "paths": paths,
            "skipped_spatial_no_geometry": skipped_spatial,
        }
        render_dict(summary, json_out=json_out, title=f"gmnspy index build: {source}")

    @index_app.command(name="status")
    def index_status(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Report which index sidecars exist next to ``source``."""
        paths = _list_index_sidecars(source)
        summary = {
            "source": str(source),
            "spatial": any(".spatial." in p.name for p in paths),
            "graph": any(".graph." in p.name for p in paths),
            "paths": [str(p) for p in paths],
        }
        render_dict(summary, json_out=json_out, title=f"gmnspy index status: {source}")

    @index_app.command(name="drop")
    def index_drop(
        source: Path = typer.Argument(..., help="Path to the GMNS network."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Delete cached spatial + graph sidecars next to ``source``."""
        paths = _list_index_sidecars(source)
        removed: list[str] = []
        for p in paths:
            try:
                p.unlink()
                removed.append(str(p))
            except OSError:  # pragma: no cover - race; surface but don't crash
                continue
        render_dict(
            {"source": str(source), "removed": removed, "count": len(removed)},
            json_out=json_out,
            title=f"gmnspy index drop: {source}",
        )

    return gmnspy_app


def _resolve_engine(name: str | None):
    """Thin CLI wrapper around :func:`datagrove.engines.resolve_engine`.

    Converts the public resolver's :class:`ValueError` (raised on an
    unknown engine name) into :class:`typer.BadParameter` so the CLI
    exits with a clean non-zero + help message instead of a traceback.
    The actual ``name → Engine`` logic lives in :mod:`datagrove.engines`
    so both CLIs share it.
    """
    from datagrove.engines import resolve_engine

    try:
        return resolve_engine(name)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


# ---------------------------------------------------------------------------
# spec diff helpers (task 4.3 / issue #85)
# ---------------------------------------------------------------------------


def _field_map(resource) -> dict[str, str | None]:  # type: ignore[no-untyped-def]
    """Return ``{field_name: type}`` for a resource, or ``{}`` if schemaless.

    Uses :attr:`Resource.table_schema` (the Python attribute name —
    accessing ``.schema`` directly emits a FutureWarning and returns a
    bound method, not the schema data).
    """
    schema = resource.table_schema
    if schema is None or isinstance(schema, str):
        return {}
    return {f.name: f.type for f in schema.fields}


def _diff_specs(v1: str, v2: str) -> dict[str, object]:
    """Compute a structural diff between two vendored GMNS spec versions.

    Returns a dict with ``v1``, ``v2``, ``added_resources``,
    ``removed_resources``, and ``changed_resources`` keys; see
    docstring on the CLI command for the exact shape.
    """
    pkg_v1 = load_gmns_spec(v1)
    pkg_v2 = load_gmns_spec(v2)
    res_v1 = {r.name: r for r in pkg_v1.resources}
    res_v2 = {r.name: r for r in pkg_v2.resources}
    names_v1 = set(res_v1)
    names_v2 = set(res_v2)

    changed: list[dict[str, object]] = []
    for name in sorted(names_v1 & names_v2):
        fields_v1 = _field_map(res_v1[name])
        fields_v2 = _field_map(res_v2[name])
        added_fields = sorted(set(fields_v2) - set(fields_v1))
        removed_fields = sorted(set(fields_v1) - set(fields_v2))
        changed_fields = [
            {"name": fname, "v1_type": fields_v1[fname], "v2_type": fields_v2[fname]}
            for fname in sorted(set(fields_v1) & set(fields_v2))
            if fields_v1[fname] != fields_v2[fname]
        ]
        if added_fields or removed_fields or changed_fields:
            changed.append(
                {
                    "name": name,
                    "added_fields": added_fields,
                    "removed_fields": removed_fields,
                    "changed_fields": changed_fields,
                }
            )

    return {
        "v1": v1,
        "v2": v2,
        "added_resources": sorted(names_v2 - names_v1),
        "removed_resources": sorted(names_v1 - names_v2),
        "changed_resources": changed,
    }


# ---------------------------------------------------------------------------
# doctor check helpers (task 4.5 / issue #87)
# ---------------------------------------------------------------------------


#: Minimum supported Python — kept in lockstep with pyproject ``requires-python``.
#: Lift to a constant so the ``_check_python_version`` doctor entry can format
#: both the comparison and the message from one source of truth.
_MIN_PYTHON: tuple[int, int] = (3, 11)


def _check_python_version() -> dict[str, object]:
    """Verify Python is at or above :data:`_MIN_PYTHON` — matches pyproject ``requires-python``."""
    ver = sys.version_info
    min_str = ".".join(str(p) for p in _MIN_PYTHON)
    ok = (ver.major, ver.minor) >= _MIN_PYTHON
    return {
        "name": "python_version",
        "ok": ok,
        "detail": f"{ver.major}.{ver.minor}.{ver.micro} ({'>=' + min_str if ok else 'requires >=' + min_str})",
    }


# Optional-extra → import probe. Each entry is (extra-name, module-to-import).
# The extra is informational; the import is what actually decides ok/!ok.
_EXTRA_PROBES: tuple[tuple[str, str], ...] = (
    ("clean", "shapely"),
    ("clean", "igraph"),
    ("server", "fastapi"),
    ("mcp", "mcp"),
    ("notebook", "ipywidgets"),
)


def _check_optional_extras() -> list[dict[str, object]]:
    """One check per (extra, probe-module). ``ok=False`` is informational, not fatal — see _check_leavenworth_loads."""
    out: list[dict[str, object]] = []
    for extra, module in _EXTRA_PROBES:
        try:
            importlib.import_module(module)
            out.append({"name": f"extra:{extra}[{module}]", "ok": True, "detail": "importable"})
        except ImportError as exc:
            out.append(
                {
                    "name": f"extra:{extra}[{module}]",
                    "ok": True,  # optional — absence is not a failure
                    "detail": f"not installed ({exc.__class__.__name__}); install with `uv sync --extra {extra}`",
                }
            )
    return out


def _check_spec_versions() -> list[dict[str, object]]:
    """Each vendored spec version must parse without error."""
    out: list[dict[str, object]] = []
    for version in SUPPORTED_SPECS:
        try:
            pkg = load_gmns_spec(version)
            out.append(
                {
                    "name": f"spec:{version}",
                    "ok": True,
                    "detail": f"{len(pkg.resources)} resources",
                }
            )
        except Exception as exc:  # pragma: no cover - vendored data is checked in
            out.append({"name": f"spec:{version}", "ok": False, "detail": f"{exc.__class__.__name__}: {exc}"})
    return out


def _check_leavenworth_loads() -> dict[str, object]:
    """Smoke test: the Leavenworth fixture should load + report a link table."""
    try:
        from gmnspy.fixtures import leavenworth

        net = Network.from_source(leavenworth.csv_dir())
        link_count = net.safe_count("link")
        return {
            "name": "fixture:leavenworth",
            "ok": link_count is not None and link_count > 0,
            "detail": f"loaded {link_count} links from csv fixture",
        }
    except Exception as exc:
        return {
            "name": "fixture:leavenworth",
            "ok": False,
            "detail": f"{exc.__class__.__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# clean / scope / index helpers (task 4.6 / issue #88)
# ---------------------------------------------------------------------------
#
# Optional-extra resolution goes through importlib so the import-linter
# contract ``gmnspy.cli ↛ gmnspy.clean`` (and the corollary for the
# scope/index ops needing igraph) holds; the contract is enforced on
# static imports only, so runtime discovery is the architecture-blessed
# path. Each ``_import_*`` helper exits non-zero with the install hint
# when the extra is missing — same shape as ``gmnspy server run``.


def _import_clean():
    """Resolve :mod:`gmnspy.clean` at call time so the import-linter contract holds."""
    try:
        return importlib.import_module("gmnspy.clean")
    except ImportError as e:
        typer.secho(
            f"gmnspy clean requires the [clean] extra: pip install 'gmnspy[clean]' ({e})",
            fg="red",
            err=True,
        )
        raise typer.Exit(code=1) from None


def _import_scope():
    """Resolve :mod:`gmnspy.scope` — core module but its index ops need igraph."""
    return importlib.import_module("gmnspy.scope")


def _import_indexes():
    """Resolve :mod:`gmnspy.indexes` — core module but build needs igraph + shapely at call time."""
    return importlib.import_module("gmnspy.indexes")


def _load_network_and_session_cls(source: Path, engine_name: str | None = None):
    """Return ``(Network, Session class)`` — :class:`Session` lives in datagrove, imported here so each op is one-line.

    ``engine_name`` follows the same ibis/pandas/polars resolution as
    :func:`_resolve_engine`. Callers can override the default ibis
    engine to dodge backend-specific edge cases (e.g. duckdb refusing
    null-typed columns when re-materialising via ``engine.from_records``
    during a ``replace_table`` edit on a fixture that carries empty
    string columns typed as null).
    """
    from datagrove.editing import Session

    return Network.from_source(source, engine=_resolve_engine(engine_name)), Session


def _summarise_results(results, *, op: str, source: Path, dest: Path | None, dry_run: bool) -> dict[str, object]:
    """Render an :class:`EditResult` (or list thereof) into the CLI's standard summary dict."""
    if not isinstance(results, list):
        results = [results]
    return {
        "op": op,
        "source": str(source),
        "dest": str(dest) if dest is not None else str(source),
        "dry_run": dry_run,
        "edits": [
            {
                "table": r.edit.table,
                "op": r.edit.op,
                "rows_added": r.diff.rows_added,
                "rows_removed": r.diff.rows_removed,
                "rows_changed": r.diff.rows_changed,
            }
            for r in results
        ],
    }


def _write_network(net: Network, *, source: Path, dest: Path | None) -> None:
    """Write ``net`` back to ``dest`` (or ``source`` when ``dest`` is None).

    Uses :meth:`Package.write`; the format is inferred from the
    target's extension, falling back to ``parquet`` for directory
    targets — matches the read-path convention so a round-trip lands
    the same logical package.

    Suppresses :class:`OutOfSyncWarning` (raised by the dirty tracker
    on tables we just edited). The whole point of these CLI ops is
    "edit then write" — the dirty flag is expected, and the warning
    would be promoted to an error under the project's
    ``filterwarnings = ["error"]`` pytest config.
    """
    import warnings

    from datagrove.dataset.package import OutOfSyncWarning

    target = dest if dest is not None else source
    overwrite = target.exists()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", OutOfSyncWarning)
        net.write(target, overwrite=overwrite)


class _ScopeErrors:
    """Context manager that converts library errors (ScopeError / ImportError) into typer.Exit(1) with a clean message.

    Class form (not a function-decorated ``contextlib.contextmanager``)
    so ``typer`` sees ``with _scope_errors():`` as a regular block — no
    generator-induced surprises around its exception handling.
    """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            return False
        # ScopeError or any sibling gmnspy error — surface the message
        # rather than the full traceback (the user typed a CLI command).
        if issubclass(exc_type, ImportError):
            typer.secho(
                f"missing optional extra: {exc_val} (try `pip install 'gmnspy[clean]'`)",
                fg="red",
                err=True,
            )
            raise typer.Exit(code=1) from None
        # gmnspy.scope.ScopeError / gmnspy.clean.CleanError both subclass
        # gmnspy.NetworkError; catch by name to avoid importing the optional
        # modules just to register the class hierarchy here.
        if exc_type.__name__ in {"ScopeError", "CleanError", "NetworkError", "ValueError"}:
            typer.secho(f"error: {exc_val}", fg="red", err=True)
            raise typer.Exit(code=1) from None
        return False  # let everything else propagate (real bugs, KeyboardInterrupt, …)


def _scope_errors() -> _ScopeErrors:
    """Return the shared error-conversion context manager."""
    return _ScopeErrors()


def _summarise_scope(scope) -> dict[str, object]:
    """Render a :class:`NetworkScope` into the CLI's standard summary dict."""
    return {
        "node_count": len(scope.node_ids),
        "link_count": len(scope.link_ids),
        "node_ids": sorted(scope.node_ids),
        "link_ids": sorted(scope.link_ids),
        "provenance": scope.provenance,
    }


def _save_index_sidecar(indexes, source: Path, net: Network, kind: str, index_obj, *, kind_target: str) -> Path:
    """Hash the relevant source table(s), compute the sidecar path, write the index."""
    from datagrove.validation import hash_table

    if kind_target == "link":
        content_hash = hash_table(net.links.expr, net.engine)
    else:
        # graph index keys off both links + nodes — combine the digests
        # by hashing the concatenation; only the first 8 chars land in
        # the filename anyway (see cache_path docstring).
        import hashlib

        link_h = hash_table(net.links.expr, net.engine)
        node_h = hash_table(net.nodes.expr, net.engine)
        content_hash = hashlib.sha256(f"{link_h}::{node_h}".encode()).hexdigest()
    path = indexes.cache_path(str(source), kind, content_hash)
    indexes.save_cached(path, index_obj)
    return path


def _list_index_sidecars(source: Path) -> list[Path]:
    """Return sorted sidecar parquet files for the network at ``source`` (empty list when none)."""
    sidecar_dir = source.parent / "_gmnspy_indexes"
    if not sidecar_dir.is_dir():
        return []
    return sorted(sidecar_dir.glob(f"{source.stem}.*.parquet"))


def _check_auto_approve_env() -> dict[str, object]:
    """Informational: report whether DATAGROVE_AUTO_APPROVE is set."""
    value = os.environ.get("DATAGROVE_AUTO_APPROVE")
    return {
        "name": "env:DATAGROVE_AUTO_APPROVE",
        "ok": True,  # informational only
        "detail": f"set to {value!r}" if value is not None else "unset (interactive consent required)",
    }


# Module-level app for the `gmnspy` console-script entry point.
app = _build_gmnspy_app()


if __name__ == "__main__":  # pragma: no cover - manual smoke
    app()
