"""netstead CLI — thin orchestrator that registers commands from :mod:`netstead.cli.commands`.

Entry point: ``netstead = netstead.cli.app:app``. Starts from
:func:`corral.cli.app.build_app` (so users get every generic
command — ``validate``, ``info``, …) then layers GMNS-specific ones
on top via per-command :func:`register` calls.

Why per-command modules? At ~950 LOC with 9 sub-apps as nested closures
inside a single 521-line factory, the old layout forced readers hunting
for ``netstead clean simplify-geometry`` to scroll-search a giant file.
Splitting per command means each ``commands/<name>.py`` is the obvious
place to look.

The 5 prior ``importlib.import_module`` sites with divergent error
handling are now centralised in :func:`netstead.cli._extras.require_extra`.
"""

from __future__ import annotations

import typer
from corral.cli.app import build_app

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
    select,
    server,
    spec,
    validate,
    viz,
)

__all__ = ["app"]


def _build_netstead_app() -> typer.Typer:
    """Return the GMNS-aware typer app, layered on top of the corral generic app.

    Pulled out as a private factory so tests can build a fresh app
    rather than relying on the module-level singleton.
    """
    netstead_app = build_app()
    # Stamp a netstead-flavoured help string over the corral default
    # so ``netstead --help`` introduces itself correctly.
    netstead_app.info.help = (
        "netstead — GMNS network CLI. Inherits the generic corral commands "
        "(validate, info) and adds GMNS-aware overrides + the data-quality "
        "rule pack. Add --json to any command for machine-readable output."
    )

    # Order: GMNS-aware OVERRIDES of generic commands first (validate /
    # info), then the GMNS-specific commands (quality / spec / doctor /
    # bench), then the optional-extra commands (server / mcp / clean /
    # scope / index) so ``--help`` reads the same way it always has.
    validate.register(netstead_app)
    info.register(netstead_app)
    quality.register(netstead_app)
    spec.register(netstead_app)
    doctor.register(netstead_app)
    bench.register(netstead_app)
    server.register(netstead_app)
    mcp.register(netstead_app)
    clean.register(netstead_app)
    scope.register(netstead_app)
    index.register(netstead_app)
    build.register(netstead_app)
    select.register(netstead_app)
    viz.register(netstead_app)
    return netstead_app


# Module-level app for the `netstead` console-script entry point.
app = _build_netstead_app()


if __name__ == "__main__":  # pragma: no cover - manual smoke
    app()
