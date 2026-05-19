"""Rendering for :class:`~datagrove.validation.ValidationReport`.

This module contains the two renderers that are in scope for Phase 2
task 2.1:

- :func:`render_rich` — formatted rich-console string, suitable for the
  CLI default output. Uses the ``rich`` library that already ships as
  a datagrove dependency.
- :func:`render_json` — stable JSON snapshot with an explicit
  ``report_version`` field, for machine and AI consumers (the MCP
  server, the FastAPI server, the ``--json`` flag on every CLI).

The interactive single-file HTML renderer is task 2.2 (issue #61) and
will live here too — it consumes the same ``ValidationReport`` without
touching the producers.

Severity ordering in the rich output is part of the contract:
``ERROR -> WARNING -> INFO -> DATA_QUALITY``. Within each severity
group, issues are further grouped by table (with ``None``-table /
cross-cutting issues rendered first, since they tend to be the
structural problems that explain everything else).
"""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .types import (
    Issue,
    Severity,
    ValidationReport,
    severity_rank,
)

__all__ = ["render_json", "render_rich"]


# ---------------------------------------------------------------------------
# Colour + label mapping (inline by design — these are tiny, only used here,
# and clearer next to the rendering code than imported from a constants
# module).
# ---------------------------------------------------------------------------

_SEVERITY_STYLE: dict[Severity, str] = {
    Severity.ERROR: "bold red",
    Severity.WARNING: "yellow",
    Severity.INFO: "blue",
    Severity.DATA_QUALITY: "magenta",
}

_SEVERITY_LABEL: dict[Severity, str] = {
    Severity.ERROR: "ERROR",
    Severity.WARNING: "WARNING",
    Severity.INFO: "INFO",
    Severity.DATA_QUALITY: "DATA_QUALITY",
}


# ---------------------------------------------------------------------------
# Rich console renderer
# ---------------------------------------------------------------------------


def render_rich(report: ValidationReport) -> str:
    """Render the report as a rich-formatted string.

    Layout:

    - Header panel: ``source`` + ``spec_version`` + per-severity counts.
    - One section per severity in canonical order (ERROR, WARNING, INFO,
      DATA_QUALITY). Within each section, issues are grouped by table.
      Each issue is one row: ``[code] message`` with the severity colour;
      a second indented line shows ``table:column[row]`` plus the
      ``fix_hint`` when present.
    - Footer: totals + the ``is_clean`` verdict.

    The function returns the rendered string; the caller decides whether
    to ``print()`` it, write it to a file, or stream it elsewhere — so
    the same renderer works for the CLI, the notebook, and tests.

    Args:
        report: The report to render.

    Returns:
        The rendered string. Includes ANSI colour codes — strip with
        ``rich.text.Text.from_ansi(s).plain`` if a plaintext copy is
        needed.

    Examples:
        >>> from datagrove.validation import (
        ...     ValidationReport, Severity, Category,
        ... )
        >>> r = ValidationReport(source="x.gmns", spec_version="0.97")
        >>> r.add(severity=Severity.ERROR, category=Category.SCHEMA,
        ...       code="schema.required",
        ...       message="link.from_node_id row 0: value is null",
        ...       table="link")
        Issue(...)
        >>> out = render_rich(r)
        >>> "schema.required" in out
        True
        >>> "x.gmns" in out
        True
    """
    # `record=True` captures the rich output into an internal buffer so
    # callers get a plain Python string back. force_terminal=True keeps
    # the ANSI colour codes in the export so tests can assert on them
    # and the CLI displays colour even when stdout isn't a TTY.
    buffer = StringIO()
    console = Console(
        file=buffer,
        force_terminal=True,
        color_system="truecolor",
        width=120,
        record=False,
    )

    _render_header(console, report)
    _render_body(console, report)
    _render_footer(console, report)

    return buffer.getvalue()


def _render_header(console: Console, report: ValidationReport) -> None:
    """Top panel: source + spec version + per-severity counts."""
    title_parts = ["Validation report"]
    if report.source:
        title_parts.append(f"— {report.source}")
    title = " ".join(title_parts)

    body = Text()
    body.append("spec_version: ", style="dim")
    body.append(f"{report.spec_version or 'unspecified'}\n")
    body.append("counts: ", style="dim")
    body.append(
        ", ".join(
            f"{_SEVERITY_LABEL[s].lower()}={report.count(s)}"
            for s in (Severity.ERROR, Severity.WARNING, Severity.INFO, Severity.DATA_QUALITY)
        )
    )

    console.print(Panel(body, title=title, expand=False))


def _render_body(console: Console, report: ValidationReport) -> None:
    """Per-severity sections, each with a table grouped by source table."""
    if not report.issues:
        console.print("[dim]No issues recorded.[/dim]")
        return

    # Stable sort by (severity_rank, "" if table is None else table) keeps
    # the canonical severity order AND groups by table within each section.
    # Sort is stable, so original insertion order survives within a group.
    for severity in (Severity.ERROR, Severity.WARNING, Severity.INFO, Severity.DATA_QUALITY):
        group = report.by_severity(severity)
        if not group:
            continue
        _render_severity_group(console, severity, group)


def _render_severity_group(console: Console, severity: Severity, issues: list[Issue]) -> None:
    """Render the table of issues for one severity level."""
    style = _SEVERITY_STYLE[severity]
    label = _SEVERITY_LABEL[severity]

    table = Table(
        title=f"[{style}]{label}[/] ({len(issues)})",
        show_header=True,
        header_style="bold",
        expand=False,
        title_justify="left",
    )
    table.add_column("Code", no_wrap=True)
    table.add_column("Location", no_wrap=True)
    table.add_column("Message", overflow="fold")

    # Sort by (table-name, row) so issues in the same file cluster together.
    for issue in sorted(issues, key=_issue_sort_key):
        table.add_row(
            Text(issue.code, style=style),
            _format_location(issue),
            _format_message(issue),
        )

    console.print(table)


def _issue_sort_key(issue: Issue) -> tuple[str, int, int]:
    """Sort key: table (blank first), then row, then severity rank.

    Cross-cutting issues (``table is None``) bubble to the top of their
    severity group because they often explain the rest — e.g. a missing
    table makes every per-row error in that table redundant.
    """
    return (
        issue.table or "",
        issue.row if issue.row is not None else -1,
        severity_rank(issue.severity),
    )


def _format_location(issue: Issue) -> Text:
    """Render the ``table:column[row]`` location prefix.

    Returns ``-`` for cross-cutting issues with no table.
    """
    if issue.table is None:
        return Text("—", style="dim")
    parts = [issue.table]
    if issue.column is not None:
        parts.append(f":{issue.column}")
    if issue.row is not None:
        parts.append(f"[{issue.row}]")
    return Text("".join(parts))


def _format_message(issue: Issue) -> Text:
    """Render the message, with the fix hint on a second line when present."""
    out = Text(issue.message)
    if issue.fix_hint:
        out.append("\n→ ", style="dim")
        out.append(issue.fix_hint, style="italic dim")
    return out


def _render_footer(console: Console, report: ValidationReport) -> None:
    """Footer: totals + the is_clean verdict."""
    verdict = "clean" if report.is_clean else "issues found"
    verdict_style = "green" if report.is_clean else "red"
    total = report.count()

    line = Text()
    line.append("Total: ", style="dim")
    line.append(f"{total} issue{'s' if total != 1 else ''}  ")
    line.append("verdict: ", style="dim")
    line.append(verdict, style=f"bold {verdict_style}")
    line.append(f"  (is_clean={report.is_clean})", style="dim")

    console.print(line)


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------


def render_json(report: ValidationReport, *, indent: int = 2) -> str:
    """Render the report as a JSON string with a stable schema.

    The schema (frozen as ``report_version="1"``):

    .. code-block:: json

        {
            "report_version": "1",
            "spec_version": "0.97",
            "source": "leavenworth.gmns",
            "created_at": "2026-05-18T12:34:56.789012",
            "metadata": {},
            "summary": {
                "error": 1, "warning": 0, "info": 0,
                "data_quality": 0, "is_clean": false
            },
            "issues": [
                {
                    "severity": "error",
                    "category": "schema",
                    "code": "schema.required",
                    "message": "link.from_node_id row 0: value is null",
                    "table": "link",
                    "column": "from_node_id",
                    "row": 0,
                    "fix_hint": "Provide a value for from_node_id.",
                    "extra": {}
                }
            ]
        }

    Args:
        report: The report to serialise.
        indent: ``json.dumps`` indent setting (default 2).

    Returns:
        A JSON string. Free of ANSI codes; safe to write to disk or
        return from an HTTP endpoint.

    Examples:
        >>> import json
        >>> from datagrove.validation import ValidationReport
        >>> r = ValidationReport(source="empty.gmns")
        >>> json.loads(render_json(r))["report_version"]
        '1'
    """
    return report.to_json(indent=indent)


# The HTML renderer (interactive single-file with Jinja2 + DataTables +
# Vega-Lite) lives here too — but it's task 2.2 / issue #61 and is out
# of scope for this commit. When implemented it will follow the same
# `render_html(report: ValidationReport, *, ...) -> str` signature.
# Until then, callers that need HTML should serialise via render_json
# and post-process; that path is the same one the HTML renderer will
# read from internally.
