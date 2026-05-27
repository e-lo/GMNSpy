"""``gmnspy validate`` — GMNS-aware validation that actually loads the spec.

Overrides the generic :func:`datagrove.cli.app.validate`. The generic
command calls ``Package.from_source(source)`` with no spec, which works
when ``source`` is a ``datapackage.json`` (the spec rides along in the
file) but produces a vacuous "every table is unexpected" report for the
common case of a **CSV directory** without a manifest.

The override loads the resolved GMNS spec via :class:`Network` so the
structural / schema / FK passes have something to compare against.

Also adds an ``--html`` flag (and matching ``--out``) so users can write
the interactive single-file HTML report straight from the CLI without
needing to drop into Python. The rendering itself lives in
:func:`datagrove.reports.render_html` — this command just wires it up.
"""

from __future__ import annotations

from pathlib import Path

import typer
from datagrove.cli.prompts import ApprovalRequired, run_with_approval
from datagrove.cli.render import console, render_issues

from gmnspy import Network

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the GMNS-aware ``validate`` command on ``app``.

    typer's second registration under the same name wins, so this
    cleanly overrides the inherited datagrove ``validate``. Existing
    invocations like ``gmnspy validate <path>`` keep working — they
    just now actually load the GMNS spec.
    """

    @app.command(name="validate")
    def gmns_validate(
        source: Path = typer.Argument(
            ...,
            help="Path / URL to a GMNS network (datapackage.json or CSV/Parquet/DuckDB directory).",
        ),
        spec_version: str = typer.Option(
            None,
            "--spec",
            help="Override the default GMNS spec version (e.g. '0.96'). Defaults to gmnspy.DEFAULT_SPEC.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit JSON on stdout instead of rich panels.",
        ),
        html_out: Path | None = typer.Option(
            None,
            "--html",
            help="Write the interactive single-file HTML report to this path. "
            "The console output is still rendered too (use --json to suppress).",
        ),
        yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Auto-approve any gated ops (alternative to DATAGROVE_AUTO_APPROVE=1).",
        ),
    ) -> None:
        """Validate ``source`` against the GMNS spec.

        Runs the four-pass validator (structural / schema / foreign-key
        / sync-state) with the GMNS spec auto-loaded — so reading a
        CSV directory without a ``datapackage.json`` gets the real
        per-table schema checks, not the empty "every table is
        unexpected" output of the generic ``datagrove validate``.

        Exit code is non-zero iff any ERROR-severity issue is recorded.

        Examples:
            Validate the bundled Leavenworth fixture as CSVs (no
            ``datapackage.json`` alongside)::

                $ gmnspy validate path/to/leavenworth/csv
                validation report: ...
                0 errors, 0 warnings, 9 info

            Write an interactive HTML report::

                $ gmnspy validate path/to/network --html report.html
        """
        net = Network.from_source(source, spec_version=spec_version)
        try:
            report = run_with_approval(net.validate, yes=yes)
        except ApprovalRequired:
            console.print("[yellow]validation declined — exiting 1.[/yellow]")
            raise typer.Exit(code=1) from None

        if html_out is not None:
            html_out.write_text(
                report.to_html(title=f"gmnspy validate — {source}"),
                encoding="utf-8",
            )
            console.print(f"[green]wrote HTML report to {html_out}[/green]")

        render_issues(report.issues, json_out=json_out, header=f"validation report: {source}")

        # Exit non-zero on hard errors so CI / scripts can branch.
        if any(getattr(i, "severity", None) and i.severity.value == "error" for i in report.issues):
            raise typer.Exit(code=1)
