"""GMNS-aware MCP server (task 4.11) — composes on :mod:`datagrove.mcp`.

Adds network-aware tools on top of datagrove's generic
describe/validate/list tools:

* ``describe_network(source)`` — GMNS metadata (spec_version + named
  link/node counts), richer than the generic describe_package.
* ``quality_check(source)`` — runs the :mod:`gmnspy.quality` rule
  pack; returns the report as a JSON dict via
  :meth:`~datagrove.reports.ValidationReport.to_dict`.
* ``connected_components(source)`` — returns the component count +
  sizes (uses :mod:`gmnspy.semantics.connectivity`; requires the
  ``[clean]`` extra for igraph).
* ``scope_from_nodes(source, node_ids, path_between)`` — applies a
  network-aware scope and returns the resulting (node_ids, link_ids)
  sets as lists.

All tools are stateless — each call loads the network fresh. Stateful
surfaces (editing sessions with rollback) deferred to follow-ups; the
:func:`build_server` ``state=`` kwarg is the seam those will plug into.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gmnspy import Network
from gmnspy.quality import register_all

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.server.fastmcp import FastMCP


__all__ = ["build_server"]


def build_server(
    name: str = "gmnspy",
    *,
    state: dict[str, Any] | None = None,
) -> FastMCP:
    """Return a :class:`FastMCP` exposing GMNS-aware + generic datagrove tools.

    Wraps :func:`datagrove.mcp.build_server` (so the generic tools are
    available) then adds the network-aware tools. Caller invokes
    ``.run(transport="stdio")`` from a CLI entry point.

    Args:
        name: Display name for the MCP server. Default ``"gmnspy"``.
        state: Optional shared-state dict forwarded to
            :func:`datagrove.mcp.build_server`. Stateful tools land
            here when the architecture's ``edit_session`` tool grows
            in; see datagrove.mcp.server.build_server for the seam
            contract.

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

    server = build_generic(name=name, state=state)

    # Register the GMNS rule pack so quality_check has rules to run.
    register_all()

    @server.tool(name="describe_network", description=_DESCRIBE_NET_DOC)
    def describe_network(source: str) -> dict[str, Any]:
        """Return GMNS metadata for the network at ``source``."""
        net = Network.from_source(source)
        return {
            "source": source,
            "name": net.spec.name,
            "spec_version": net.spec_version,
            "engine": type(net.engine).__name__,
            "links": net.safe_count("link"),
            "nodes": net.safe_count("node"),
            "table_count": len(net.tables),
            "tables": sorted(net.tables.keys()),
        }

    @server.tool(name="quality_check", description=_QUALITY_DOC)
    def quality_check(source: str) -> dict[str, Any]:
        """Run the GMNS data-quality rule pack against the network at ``source``."""
        net = Network.from_source(source)
        report = run_quality(net)
        return report.to_dict()

    @server.tool(name="connected_components", description=_COMPONENTS_DOC)
    def connected_components_tool(source: str) -> dict[str, Any]:
        """Return weakly-connected component count + sizes for the network at ``source``."""
        from gmnspy.semantics import connected_components

        net = Network.from_source(source)
        comps = connected_components(net)
        sizes = sorted((len(c) for c in comps), reverse=True)
        return {"source": source, "component_count": len(comps), "sizes": sizes}

    @server.tool(name="scope_from_nodes", description=_SCOPE_DOC)
    def scope_from_nodes_tool(source: str, node_ids: list[int], path_between: bool = True) -> dict[str, Any]:
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


_DESCRIBE_NET_DOC = """\
Return GMNS metadata about the network at ``source``: spec_version,
link count, node count, engine name, full table list. Richer than the
generic ``describe_package`` — surfaces the GMNS-specific fields an
agent typically wants up front.
"""

_QUALITY_DOC = """\
Run the GMNS data-quality rule pack against the network at ``source``.
Returns the canonical ValidationReport.to_dict() shape — every issue
includes severity, category, code, message, table, column, row,
fix_hint, extra.
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
