"""``gmnspy validate`` — GMNS-aware validation that actually loads the spec.

Overrides the generic :func:`datagrove.cli.app.validate`. The generic
command calls ``Package.from_source(source)`` with no spec, which works
when ``source`` is a ``datapackage.json`` (the spec rides along in the
file) but produces a vacuous "every table is unexpected" report for the
common case of a **CSV directory** without a manifest.

The override loads the resolved GMNS spec via :class:`Network` so the
structural / schema / FK passes have something to compare against. It
also wires up the four output flags users actually want from the CLI:

* ``--html`` — interactive network-on-map viewer
  (:func:`gmnspy.reports.render_validation_html`). Falls back gracefully
  to datagrove's table-only HTML when the ``[reports]`` extra is not
  installed, so ``--html`` always writes a file.
* ``--csv`` — flat findings CSV (no engine deps).
* ``--xlsx`` — single-sheet findings workbook (requires
  ``openpyxl`` from the ``[reports]`` extra).
* ``--json`` — unchanged stdout JSON of the full report.
"""

from __future__ import annotations

import importlib
import sys
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
            help=(
                "Write the interactive network-on-map HTML viewer to this path. "
                "Falls back to a table-only HTML report when the [reports] extra "
                "is not installed."
            ),
        ),
        csv_out: Path | None = typer.Option(
            None,
            "--csv",
            help="Write the flat findings table to this CSV path.",
        ),
        xlsx_out: Path | None = typer.Option(
            None,
            "--xlsx",
            help="Write the flat findings table to this XLSX path (requires [reports] extra).",
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
            Validate the bundled Leavenworth fixture as CSVs::

                $ gmnspy validate path/to/leavenworth/csv

            Write the interactive map+table HTML viewer::

                $ gmnspy validate path/to/network --html report.html

            Export findings to a spreadsheet::

                $ gmnspy validate path/to/network --csv f.csv --xlsx f.xlsx
        """
        net = Network.from_source(source, spec_version=spec_version)
        try:
            report = run_with_approval(net.validate, yes=yes)
        except ApprovalRequired:
            console.print("[yellow]validation declined — exiting 1.[/yellow]")
            raise typer.Exit(code=1) from None

        if html_out is not None:
            _write_html(net, report, html_out, source=source)
        if csv_out is not None:
            _write_csv(report, csv_out)
        if xlsx_out is not None:
            _write_xlsx(report, xlsx_out)

        render_issues(report.issues, json_out=json_out, header=f"validation report: {source}")

        # Exit non-zero on hard errors so CI / scripts can branch.
        if any(getattr(i, "severity", None) and i.severity.value == "error" for i in report.issues):
            raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Output writers — kept inline so the command body stays readable.
# ---------------------------------------------------------------------------


def _write_html(net: Network, report, path: Path, *, source: Path) -> None:
    """Write the map+table HTML viewer, falling back to datagrove's table-only on ImportError.

    Uses :func:`importlib.import_module` rather than a static import so the
    import-linter contract ``gmnspy.cli ↛ gmnspy.{map,reports}`` keeps
    holding — the CLI is the optional-extras integration point and
    threads the extra in at call time.
    """
    try:
        gmnspy_map = importlib.import_module("gmnspy.map")
    except ImportError:
        # The [reports] extra (jinja2 / openpyxl) isn't installed — emit
        # the datagrove table-only report and steer the user to the right
        # install command.
        print(
            "note: the gmnspy[reports] extra is not installed — writing the table-only "
            "HTML report (no map). Install with: pip install 'gmnspy[reports]'",
            file=sys.stderr,
        )
        path.write_text(report.to_html(title=f"gmnspy validate — {source}"), encoding="utf-8")
        console.print(f"[green]wrote HTML report to {path}[/green]")
        return

    html = gmnspy_map.render_validation_html(net, report)
    path.write_text(html, encoding="utf-8")
    console.print(f"[green]wrote HTML report to {path}[/green]")


def _write_csv(report, path: Path) -> None:
    """Write the findings table as CSV. No optional extras required."""
    findings = importlib.import_module("gmnspy.reports.findings_table")
    findings.write_findings_csv(report.issues, path)
    console.print(f"[green]wrote CSV findings to {path}[/green]")


def _write_xlsx(report, path: Path) -> None:
    """Write the findings table as XLSX. Requires the [reports] extra."""
    findings = importlib.import_module("gmnspy.reports.findings_table")
    findings.write_findings_xlsx(report.issues, path)
    console.print(f"[green]wrote XLSX findings to {path}[/green]")
