"""Output helpers for CLI commands — rich console + structured JSON.

Every CLI command renders through one of these helpers so the
``--json`` contract is uniform: when ``json_out`` is True, we emit
exactly one JSON document on stdout (no log noise, no progress bars);
otherwise we render a rich panel/table to stderr-aware
:class:`~rich.console.Console`.

Why split rendering from the command body: agents calling the CLI via
``--json`` parse a single document. Rules dropping log noise into the
JSON stream would break them. Centralising the formatter here keeps
the contract obvious — and Phase 4 task 4.7's approval prompts use
the same console so prompts surface to a human even when ``--json``
is set on stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

__all__ = ["console", "render_dict", "render_issues", "render_table"]

# A single shared Console so multiple commands look identical and
# auto-detect notebook vs terminal once. ``stderr=True`` keeps prompts
# + progress on stderr so ``--json`` on stdout stays parseable.
console = Console(stderr=True)


def render_dict(data: dict[str, Any], *, json_out: bool, title: str | None = None) -> None:
    """Render a flat dict as a 2-column rich table OR a JSON document.

    ``data`` values must be JSON-serialisable when ``json_out=True``.
    The function emits to stdout for JSON (so it's pipeable) and to
    stderr for rich (so it doesn't collide with --json on stdout).
    """
    if json_out:
        # stdout, no trailing extras — agents parse a single document.
        json.dump(data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    table = Table(title=title, show_header=False)
    table.add_column("key", style="bold cyan")
    table.add_column("value")
    for key, value in data.items():
        table.add_row(str(key), str(value))
    console.print(table)


def render_table(rows: list[dict[str, Any]], *, json_out: bool, title: str | None = None) -> None:
    """Render a list of homogeneous dicts as a rich table OR a JSON array.

    Column order is taken from the first row. Empty input prints an
    informational message in rich mode and ``[]`` in JSON mode.
    """
    if json_out:
        json.dump(rows, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    if not rows:
        console.print(f"[dim]{title or 'rows'}: (none)[/dim]")
        return

    table = Table(title=title)
    for col in rows[0]:
        table.add_column(str(col))
    for row in rows:
        table.add_row(*(str(row.get(c, "")) for c in rows[0]))
    console.print(table)


def render_issues(issues: list[Any], *, json_out: bool, header: str | None = None) -> None:
    """Render a list of :class:`~datagrove.reports.Issue` records.

    JSON mode emits the issues array (each issue via ``__dict__`` /
    dataclass asdict-equivalent — :class:`Issue` is a dataclass so
    ``vars(...)`` works). Rich mode prints a one-line-per-issue table
    grouped by severity for at-a-glance reading.
    """
    if json_out:
        # Each Issue is a frozen dataclass; vars() works on it.
        payload = [_issue_to_payload(i) for i in issues]
        json.dump({"header": header, "issues": payload}, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    if header:
        console.print(f"[bold]{header}[/bold]")
    if not issues:
        console.print("[green]✓ no issues[/green]")
        return
    table = Table()
    for col in ("severity", "code", "table", "row", "message"):
        table.add_column(col)
    for issue in issues:
        table.add_row(
            str(getattr(issue, "severity", "")),
            str(getattr(issue, "code", "")),
            str(getattr(issue, "table", "")),
            str(getattr(issue, "row", "")),
            str(getattr(issue, "message", "")),
        )
    console.print(table)


def _issue_to_payload(issue: Any) -> dict[str, Any]:
    """Flatten an :class:`~datagrove.reports.Issue` to a JSON-safe dict."""
    fields = ("severity", "category", "code", "message", "table", "column", "row", "fix_hint", "extra")
    return {f: _scalar(getattr(issue, f, None)) for f in fields}


def _scalar(value: Any) -> Any:
    """Convert StrEnum / Path / dataclass values into JSON-safe scalars."""
    if value is None:
        return None
    if hasattr(value, "value"):  # StrEnum
        return value.value
    if isinstance(value, dict):
        return {k: _scalar(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scalar(v) for v in value]
    return value
