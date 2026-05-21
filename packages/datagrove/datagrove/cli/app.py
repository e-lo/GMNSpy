"""Generic datagrove CLI — typer app + ``build_app()`` factory.

Two entry points compose on the same factory:

* ``datagrove = datagrove.cli.app:app`` ships only the generic
  commands (validate, info — extended in Phase 4 task 4.2 with convert,
  scope, describe).
* ``gmnspy = gmnspy.cli.app:app`` calls :func:`build_app` to get a
  fresh Typer with the generic commands, then layers GMNS-aware ones
  on top (``quality``, GMNS-aware ``info``, etc.).

Reusing the factory keeps both CLIs identical for the validate/info
contract — same flags, same ``--json`` shape, same approval handling.

Every command accepts ``--json`` (so an agent gets a single
machine-readable document on stdout) and ``--yes/-y`` (auto-approve
gated ops, see :mod:`datagrove.cli.prompts`).
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from datagrove.dataset import Package
from datagrove.operations import ApprovalRequired

from .prompts import run_with_approval
from .render import console, render_dict, render_issues

__all__ = ["app", "build_app"]

logger = logging.getLogger(__name__)


def build_app() -> typer.Typer:
    """Return a fresh :class:`typer.Typer` with the generic datagrove commands.

    Used by both the ``datagrove`` and ``gmnspy`` entry points so the
    two CLIs share the same validate/info contracts. Domain extensions
    (gmnspy) call this then attach their own commands; the returned
    app is otherwise independent (calling :func:`build_app` twice
    yields two unrelated apps).
    """
    typer_app = typer.Typer(
        no_args_is_help=True,
        rich_markup_mode="rich",
        context_settings={"help_option_names": ["-h", "--help"]},
        help=(
            "datagrove — generic Frictionless data-package CLI. Add --json to any command for machine-readable output."
        ),
    )

    @typer_app.command(name="validate")
    def validate(
        source: Path = typer.Argument(..., help="Path / URL to a data package (datapackage.json or table directory)."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout instead of rich panels."),
        yes: bool = typer.Option(
            False, "--yes", "-y", help="Auto-approve any gated ops (alternative to DATAGROVE_AUTO_APPROVE=1)."
        ),
    ) -> None:
        """Validate ``source`` against its declared Frictionless schema.

        Runs structural + schema + foreign-key + sync-state validators
        and renders the resulting :class:`~datagrove.reports.ValidationReport`.
        Exit code is non-zero iff any ERROR-severity issue is recorded.
        """
        package = Package.from_source(source)
        try:
            report = run_with_approval(package.validate, yes=yes)
        except ApprovalRequired:
            console.print("[yellow]validation declined — exiting 1.[/yellow]")
            raise typer.Exit(code=1) from None
        render_issues(report.issues, json_out=json_out, header=f"validation report: {source}")
        # Exit non-zero on hard errors so CI / scripts can branch.
        if any(getattr(i, "severity", None) and i.severity.value == "error" for i in report.issues):
            raise typer.Exit(code=1)

    @typer_app.command(name="info")
    def info(
        source: Path = typer.Argument(..., help="Path / URL to a data package."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout instead of rich panels."),
    ) -> None:
        """Print metadata about ``source`` — table list, row counts, spec name."""
        package = Package.from_source(source)
        data = {
            "name": package.spec.name,
            "source": str(source),
            "engine": type(package.engine).__name__,
            "table_count": len(package.tables),
            "tables": _table_summary(package),
        }
        render_dict(data, json_out=json_out, title=f"info: {source}")

    return typer_app


def _table_summary(package: Package) -> list[dict]:
    """Return ``[{name, rows, columns}]`` for every table in ``package``.

    Materialises one row count per table; if a table is lazy and large,
    the engine pushes the count down to its backend so this remains
    cheap on regional-scale parquet sources.
    """
    out: list[dict] = []
    for name, table in package.tables.items():
        try:
            row_count = table.count()
            col_list = table.columns()
        except Exception as exc:  # pragma: no cover - per-table resilience
            logger.warning("info: skipping table %r — %s", name, exc)
            continue
        out.append({"name": name, "rows": row_count, "columns": col_list})
    return out


# The default ``datagrove`` entry point app — module-level so the
# console script resolves it as `datagrove.cli.app:app`. Build it
# once; consumers wanting a fresh app call :func:`build_app` again.
app = build_app()


if __name__ == "__main__":  # pragma: no cover - manual smoke
    app()
