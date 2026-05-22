"""Generic datagrove MCP server (task 4.11).

Exposes stateless tools over the Model Context Protocol so an AI
agent (Claude Desktop, Claude Code, ...) can describe + validate any
Frictionless data package by path / URL — without the agent having to
know Python.

Tools shipped here are **stateless**: each call takes a ``source``
path/URL and loads the package fresh. No server-side session, no
caching, no cross-call mutation. Stateful surfaces (editing sessions
with rollback, indexed scope ops) would need a different design and
are deliberately deferred to follow-up issues.

Use via :func:`build_server` which returns a configured
:class:`mcp.server.fastmcp.FastMCP`. The companion CLI command
``datagrove mcp serve`` (not in this PR; defer to follow-up) hooks
this into the stdio transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from datagrove.dataset import Package

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.server.fastmcp import FastMCP


__all__ = ["build_server"]


def build_server(name: str = "datagrove") -> FastMCP:
    """Return a configured :class:`FastMCP` exposing generic datagrove tools.

    The returned server is ready to ``run(transport="stdio")``. Tools:

    * ``describe_package(source)`` — package metadata: table list +
      row counts + engine name.
    * ``validate_package(source)`` — full validation; returns the
      :class:`~datagrove.reports.ValidationReport` as a JSON dict.
    * ``list_tables(source)`` — short list of table names (cheap, no
      row counts).

    Args:
        name: MCP server display name. Default ``"datagrove"``.

    Returns:
        A :class:`FastMCP` instance with the tools registered. Caller
        invokes ``.run(transport="stdio")`` from the CLI entry point.

    Examples:
        >>> import pytest
        >>> pytest.importorskip("mcp")
        <module ...>
        >>> server = build_server()
        >>> # The server object is ready; ``server.run(...)`` would block
        >>> # on stdio. Tests exercise the tools via the lower-level
        >>> # registry instead.
        >>> isinstance(server.name, str)
        True
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(name=name, instructions=_INSTRUCTIONS)

    @server.tool(name="describe_package", description=_DESCRIBE_DOC)
    def describe_package(source: str) -> dict[str, Any]:
        """Return metadata about the package at ``source``."""
        pkg = Package.from_source(source)
        tables = []
        for tname, table in pkg.tables.items():
            try:
                tables.append({"name": tname, "rows": table.count(), "columns": table.columns()})
            except Exception:  # pragma: no cover - per-table resilience
                tables.append({"name": tname, "rows": None, "columns": None})
        return {
            "source": source,
            "name": pkg.spec.name,
            "engine": type(pkg.engine).__name__,
            "table_count": len(pkg.tables),
            "tables": tables,
        }

    @server.tool(name="validate_package", description=_VALIDATE_DOC)
    def validate_package(source: str) -> dict[str, Any]:
        """Run full validation; return issues as a JSON-safe dict."""
        pkg = Package.from_source(source)
        report = pkg.validate()
        return _report_to_dict(report)

    @server.tool(name="list_tables", description=_LIST_DOC)
    def list_tables(source: str) -> list[str]:
        """Return the table names in the package at ``source`` (cheap, no row counts)."""
        pkg = Package.from_source(source)
        return sorted(pkg.tables.keys())

    return server


def _report_to_dict(report: Any) -> dict[str, Any]:
    """Flatten a :class:`ValidationReport` to a JSON-safe dict for the MCP wire."""
    issues = []
    for issue in report.issues:
        issues.append(
            {
                "severity": getattr(getattr(issue, "severity", None), "value", None),
                "category": getattr(getattr(issue, "category", None), "value", None),
                "code": getattr(issue, "code", None),
                "message": getattr(issue, "message", None),
                "table": getattr(issue, "table", None),
                "column": getattr(issue, "column", None),
                "row": getattr(issue, "row", None),
                "fix_hint": getattr(issue, "fix_hint", None),
            }
        )
    return {"issues": issues, "spec_version": getattr(report, "spec_version", None)}


_INSTRUCTIONS = """\
datagrove MCP server — stateless tools for any Frictionless data package.

Every tool takes a ``source`` (filesystem path or URL to a package
directory / datapackage.json file). Packages are loaded fresh per
call; there is no session or cache.

Use ``describe_package`` for a quick overview, ``list_tables`` for a
cheap name list, and ``validate_package`` to run the full schema +
FK + structural checks and get back a JSON-shaped report.
"""

_DESCRIBE_DOC = """\
Return metadata about the data package at ``source``. Output includes
the package name, engine, table count, and per-table {name, rows,
columns} entries.
"""

_VALIDATE_DOC = """\
Run full validation (structural + schema + foreign-key + sync-state)
on the package at ``source``. Returns ``{issues: [...], spec_version}``
where each issue is a dict with severity, category, code, message,
table, column, row, fix_hint.
"""

_LIST_DOC = """\
Return the table names (sorted) in the package at ``source``. Cheap —
does not compute row counts; use ``describe_package`` for those.
"""
