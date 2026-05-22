"""Tests for the generic datagrove MCP server (task 4.11 / issue #94).

We don't spin up the stdio transport — instead we introspect the
:class:`FastMCP` instance's registered tools and call them directly
through the same code path the protocol layer would. This keeps the
tests fast + transport-agnostic.
"""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

import asyncio

from datagrove.mcp import build_server
from gmnspy.fixtures import leavenworth


def _call_tool(server, name: str, **kwargs):
    """Run the registered FastMCP tool ``name`` against ``kwargs`` and return its result.

    FastMCP tools are async; we wrap with ``asyncio.run`` so individual
    tests stay sync. The internal ``_tool_manager.call_tool`` is the
    public way to dispatch by name across SDK versions we've used.
    """
    return asyncio.run(server._tool_manager.call_tool(name, kwargs))


# ---------------------------------------------------------------------------
# Server construction
# ---------------------------------------------------------------------------


def test_build_server_returns_fastmcp_with_expected_tools():
    """Server has the 3 generic tools registered."""
    server = build_server()
    tools = {t.name for t in server._tool_manager.list_tools()}
    assert {"describe_package", "validate_package", "list_tables"} <= tools


def test_build_server_uses_configured_name():
    """Custom name is propagated to the FastMCP instance."""
    assert build_server(name="my-grove").name == "my-grove"


# ---------------------------------------------------------------------------
# describe_package
# ---------------------------------------------------------------------------


def test_describe_package_returns_metadata():
    """describe_package returns table list + row counts on Leavenworth.

    Diagnostic note: directory-of-csv-files load relies on
    :class:`Package.from_source` autosynth + the directory walk.
    When the fixture path is relative to cwd, other tests changing
    cwd can hide the files; we resolve to an absolute path before
    handing it to the tool to remove that source of flakiness.
    """
    server = build_server()
    source = str(leavenworth.csv_dir().resolve())
    result = _call_tool(server, "describe_package", source=source)
    assert result["table_count"] >= 1, f"got table_count={result['table_count']} for source={source}"
    assert any(t["name"] == "link" for t in result["tables"])


# ---------------------------------------------------------------------------
# validate_package
# ---------------------------------------------------------------------------


def test_validate_package_returns_issues_document():
    """validate_package returns a dict with an ``issues`` list."""
    server = build_server()
    result = _call_tool(server, "validate_package", source=str(leavenworth.csv_dir().resolve()))
    assert "issues" in result
    assert isinstance(result["issues"], list)


# ---------------------------------------------------------------------------
# list_tables
# ---------------------------------------------------------------------------


def test_list_tables_returns_sorted_names():
    """list_tables returns a sorted list of table names."""
    server = build_server()
    source = str(leavenworth.csv_dir().resolve())
    result = _call_tool(server, "list_tables", source=source)
    assert isinstance(result, list)
    assert result == sorted(result)
    assert "link" in result and "node" in result, f"got tables={result} for source={source}"
