"""gmnspy CLI — thin orchestrator that registers commands from :mod:`gmnspy.cli.commands`.

Entry point: ``gmnspy = gmnspy.cli.app:app``. Starts from
:func:`datagrove.cli.app.build_app` (so users get every generic
command — ``validate``, ``info``, …) then layers GMNS-specific ones
on top via per-command :func:`register` calls.

Why per-command modules? At ~950 LOC with 9 sub-apps as nested closures
inside a single 521-line factory, the old layout forced readers hunting
for ``gmnspy clean simplify-geometry`` to scroll-search a giant file.
Splitting per command means each ``commands/<name>.py`` is the obvious
place to look.

The 5 prior ``importlib.import_module`` sites with divergent error
handling are now centralised in :func:`gmnspy.cli._extras.require_extra`.
"""

from __future__ import annotations

import typer
from datagrove.cli.app import build_app

from .commands import (
    bench,
    build,
    clean,
    doctor,
    index,
    info,
    mcp,
    quality,
    scope,
    server,
    spec,
    validate,
)

__all__ = ["app"]


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

    # Order: GMNS-aware OVERRIDES of generic commands first (validate /
    # info), then the GMNS-specific commands (quality / spec / doctor /
    # bench), then the optional-extra commands (server / mcp / clean /
    # scope / index) so ``--help`` reads the same way it always has.
    validate.register(gmnspy_app)
    info.register(gmnspy_app)
    quality.register(gmnspy_app)
    spec.register(gmnspy_app)
    doctor.register(gmnspy_app)
    bench.register(gmnspy_app)
    server.register(gmnspy_app)
    mcp.register(gmnspy_app)
    clean.register(gmnspy_app)
    scope.register(gmnspy_app)
    index.register(gmnspy_app)
    build.register(gmnspy_app)
    return gmnspy_app


# Module-level app for the `gmnspy` console-script entry point.
app = _build_gmnspy_app()


if __name__ == "__main__":  # pragma: no cover - manual smoke
    app()
