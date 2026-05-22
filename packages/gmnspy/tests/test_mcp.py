"""Tests for the GMNS-aware MCP server (task 4.11 / issue #94).

Same pattern as packages/datagrove/tests/mcp/test_mcp.py — introspect
the registered tools and call them directly so we don't need an MCP
stdio peer.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp")
pytest.importorskip("igraph")  # connected_components tool

from gmnspy.fixtures import leavenworth
from gmnspy.mcp import build_server


def _call_tool(server, name: str, **kwargs):
    """Synchronously dispatch a FastMCP tool by name."""
    return asyncio.run(server._tool_manager.call_tool(name, kwargs))


# ---------------------------------------------------------------------------
# Server composition
# ---------------------------------------------------------------------------


def test_gmns_server_inherits_generic_tools():
    """The gmnspy MCP server still exposes the generic datagrove tools."""
    tools = {t.name for t in build_server()._tool_manager.list_tools()}
    assert {"describe_package", "validate_package", "list_tables"} <= tools


def test_gmns_server_adds_network_aware_tools():
    """The GMNS-specific tools are registered on top."""
    tools = {t.name for t in build_server()._tool_manager.list_tools()}
    assert {"describe_network", "quality_check", "connected_components", "scope_from_nodes"} <= tools


# ---------------------------------------------------------------------------
# describe_network
# ---------------------------------------------------------------------------


def test_describe_network_returns_gmns_metadata():
    """describe_network surfaces spec_version + link/node counts."""
    server = build_server()
    r = _call_tool(server, "describe_network", source=str(leavenworth.csv_dir()))
    assert r["spec_version"] == "0.97"
    assert isinstance(r["links"], int) and r["links"] > 0
    assert isinstance(r["nodes"], int) and r["nodes"] > 0


# ---------------------------------------------------------------------------
# quality_check
# ---------------------------------------------------------------------------


def test_quality_check_returns_issues_with_data_quality_category():
    """quality_check emits the GMNS rule pack's issues."""
    server = build_server()
    r = _call_tool(server, "quality_check", source=str(leavenworth.csv_dir()))
    assert "issues" in r
    # Leavenworth fires the high-speed-residential rule.
    codes = {i["code"] for i in r["issues"]}
    assert "quality.high_speed_residential" in codes


# ---------------------------------------------------------------------------
# connected_components
# ---------------------------------------------------------------------------


def test_connected_components_on_leavenworth_is_one():
    """Leavenworth is a single weakly-connected component."""
    server = build_server()
    r = _call_tool(server, "connected_components", source=str(leavenworth.csv_dir()))
    assert r["component_count"] == 1
    assert sum(r["sizes"]) == r["sizes"][0]  # all nodes in one component


# ---------------------------------------------------------------------------
# scope_from_nodes
# ---------------------------------------------------------------------------


def test_scope_from_nodes_returns_id_lists():
    """scope_from_nodes returns subsets of (node_ids, link_ids)."""
    server = build_server()
    r = _call_tool(
        server,
        "scope_from_nodes",
        source=str(leavenworth.csv_dir()),
        node_ids=[1, 2],
        path_between=False,
    )
    assert isinstance(r["node_ids"], list)
    assert 1 in r["node_ids"] and 2 in r["node_ids"]
    assert r["result_link_count"] == len(r["link_ids"])


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_mcp_subcommand_listed_in_gmnspy_help():
    """`gmnspy --help` shows the `mcp` subcommand."""
    from gmnspy.cli.app import app as gmnspy_cli_app
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(gmnspy_cli_app, ["--help"])
    assert result.exit_code == 0
    assert "mcp" in result.stdout


def test_mcp_serve_help_lists_options():
    """`gmnspy mcp serve --help` shows the --name option."""
    from gmnspy.cli.app import app as gmnspy_cli_app
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(gmnspy_cli_app, ["mcp", "serve", "--help"])
    assert result.exit_code == 0
    assert "--name" in result.stdout
