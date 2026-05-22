"""GMNS-aware MCP server (task 4.11) — composes on :mod:`datagrove.mcp`.

Adds network-aware tools on top of datagrove's generic
describe/validate/list tools:

* ``describe_network(source)`` — GMNS metadata (spec_version + named
  link/node counts), richer than the generic describe_package.
* ``quality_check(source)`` — runs the :mod:`gmnspy.quality` rule
  pack; returns the report as a JSON dict.
* ``connected_components(source)`` — returns the component count +
  sizes (uses :mod:`gmnspy.semantics.connectivity`; requires the
  ``[clean]`` extra for igraph).
* ``scope_from_nodes(source, node_ids, path_between)`` — applies a
  network-aware scope and returns the resulting (node_ids, link_ids)
  sets as lists.

All tools are stateless — each call loads the network fresh. Stateful
surfaces (editing sessions with rollback) deferred to follow-ups.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gmnspy import Network
from gmnspy.quality import register_all

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.server.fastmcp import FastMCP


__all__ = ["build_server"]


def build_server(name: str = "gmnspy") -> FastMCP:
    """Return a :class:`FastMCP` exposing GMNS-aware + generic datagrove tools.

    Wraps :func:`datagrove.mcp.build_server` (so the generic tools are
    available) then adds the network-aware tools. Caller invokes
    ``.run(transport="stdio")`` from a CLI entry point.

    Args:
        name: Display name for the MCP server. Default ``"gmnspy"``.

    Returns:
        A configured :class:`FastMCP` ready to serve.

    Examples:
        >>> import pytest
        >>> pytest.importorskip("mcp")
        <module ...>
        >>> server = build_server()
        >>> isinstance(server.name, str)
        True
    """
    from datagrove.mcp import build_server as build_generic
    from datagrove.quality import run_quality

    server = build_generic(name=name)

    # Register the GMNS rule pack so quality_check has rules to run.
    register_all()

    @server.tool(name="describe_network", description=_DESCRIBE_NET_DOC)
    def describe_network(source: str) -> dict:
        """Return GMNS metadata for the network at ``source``."""
        net = Network.from_source(source)
        return {
            "source": source,
            "name": net.spec.name,
            "spec_version": net.spec_version,
            "engine": type(net.engine).__name__,
            "links": _safe_count(net, "link"),
            "nodes": _safe_count(net, "node"),
            "table_count": len(net.tables),
            "tables": sorted(net.tables.keys()),
        }

    @server.tool(name="quality_check", description=_QUALITY_DOC)
    def quality_check(source: str) -> dict:
        """Run the GMNS data-quality rule pack against the network at ``source``."""
        net = Network.from_source(source)
        report = run_quality(net)
        return _report_to_dict(report)

    @server.tool(name="connected_components", description=_COMPONENTS_DOC)
    def connected_components_tool(source: str) -> dict:
        """Return weakly-connected component count + sizes for the network at ``source``."""
        from gmnspy.semantics import connected_components

        net = Network.from_source(source)
        comps = connected_components(net)
        sizes = sorted((len(c) for c in comps), reverse=True)
        return {"source": source, "component_count": len(comps), "sizes": sizes}

    @server.tool(name="scope_from_nodes", description=_SCOPE_DOC)
    def scope_from_nodes_tool(source: str, node_ids: list[int], path_between: bool = True) -> dict:
        """Build a network scope from seed ``node_ids`` and return its (links, nodes) sets."""
        from gmnspy.scope import from_nodes

        net = Network.from_source(source)
        scope = from_nodes(net, node_ids, path_between=path_between)
        return {
            "source": source,
            "seed_node_ids": list(node_ids),
            "path_between": path_between,
            "result_node_count": len(scope.node_ids),
            "result_link_count": len(scope.link_ids),
            "node_ids": sorted(scope.node_ids),
            "link_ids": sorted(scope.link_ids),
        }

    return server


def _safe_count(net: Network, table_name: str) -> int | None:
    """Return ``net.tables[table_name].count()`` or ``None``."""
    table = net.tables.get(table_name)
    if table is None:
        return None
    try:
        return table.count()
    except Exception:  # pragma: no cover
        return None


def _report_to_dict(report) -> dict:
    """Flatten a :class:`ValidationReport` to a JSON-safe dict (duplicate of datagrove.mcp helper).

    Intentional duplication — coupling the gmnspy MCP tools to a
    private helper in datagrove.mcp would be tighter than the benefit.
    The helper is 10 lines.
    """
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


_DESCRIBE_NET_DOC = """\
Return GMNS metadata about the network at ``source``: spec_version,
link count, node count, engine name, full table list. Richer than the
generic ``describe_package`` — surfaces the GMNS-specific fields an
agent typically wants up front.
"""

_QUALITY_DOC = """\
Run the GMNS data-quality rule pack against the network at ``source``.
Returns ``{issues: [...], spec_version}`` — each issue is a dict with
severity (WARNING / INFO), category (always ``data_quality``), code
(e.g. ``quality.high_speed_residential``), message, table, column,
row, fix_hint.
"""

_COMPONENTS_DOC = """\
Return the count + sizes of weakly-connected components in the GMNS
network at ``source``. ``component_count == 1`` means the network is
fully connected; ``sizes`` is the descending list of node-counts per
component. Requires the ``[clean]`` extra (igraph).
"""

_SCOPE_DOC = """\
Build a network scope from a list of seed ``node_ids`` and return the
resulting set of nodes + links. ``path_between=True`` (default)
expands the scope to include shortest-path nodes between every pair of
seeds; ``path_between=False`` keeps just the seeds + their incident
links. Returns ``{result_node_count, result_link_count, node_ids,
link_ids}``.
"""
