"""``gmnspy bench`` — read/validate/connectivity timing (issue #86)."""

from __future__ import annotations

from pathlib import Path

import typer
from datagrove.cli.render import render_dict

from gmnspy import Network

from .._helpers import resolve_engine

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the ``bench`` command on ``app``."""

    @app.command(name="bench")
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

        eng = resolve_engine(engine)

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
