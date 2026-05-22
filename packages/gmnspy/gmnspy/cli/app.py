"""GMNS-aware CLI — extends :mod:`datagrove.cli.app` with GMNS commands.

Entry point: ``gmnspy = gmnspy.cli.app:app``. Starts from
:func:`datagrove.cli.app.build_app` (so users get every generic
command — ``validate``, ``info``, …) then layers GMNS-specific ones
on top:

* ``info`` — GMNS-aware: prints :attr:`Network.spec_version` + the
  named-table summary (links, nodes, segments, …) rather than the
  generic resource list.
* ``quality`` — runs the :mod:`gmnspy.quality` rule pack.

Future Phase 4 tasks add ``read``, ``spec``, ``clean``, ``index`` per
the architecture (tasks 4.3 / 4.6).

Every command keeps the ``--json`` + ``--yes`` contract from
:mod:`datagrove.cli` so an agent that learned the datagrove surface
already knows the GMNS surface.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from datagrove.cli.app import build_app
from datagrove.cli.render import render_dict, render_issues
from datagrove.quality import RuleConfig, run_quality

from gmnspy import Network
from gmnspy.quality import register_all

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
            "links": _safe_count(net, "link"),
            "nodes": _safe_count(net, "node"),
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

    return gmnspy_app


def _resolve_engine(name: str | None):
    """Resolve an engine by name (``ibis`` / ``pandas`` / ``polars``).

    Mirrors the helper used by other Phase-4 commands; kept local so this
    module doesn't depend on the 4.2 helper landing first.
    """
    from datagrove.engines import get_engine

    if name is None:
        return get_engine()
    name = name.lower()
    if name == "ibis":
        from datagrove.engines.ibis_engine import IbisEngine

        return IbisEngine()
    if name == "pandas":
        from datagrove.engines.pandas_engine import PandasEngine

        return PandasEngine()
    if name == "polars":
        from datagrove.engines.polars_engine import PolarsEngine

        return PolarsEngine()
    raise typer.BadParameter(f"unknown engine {name!r}")


def _safe_count(net: Network, table_name: str) -> int | None:
    """Return ``net.tables[table_name].count()`` or ``None`` if the table is absent."""
    table = net.tables.get(table_name)
    if table is None:
        return None
    try:
        return table.count()
    except Exception:  # pragma: no cover - best effort for `info`
        return None


# Module-level app for the `gmnspy` console-script entry point.
app = _build_gmnspy_app()


if __name__ == "__main__":  # pragma: no cover - manual smoke
    app()
