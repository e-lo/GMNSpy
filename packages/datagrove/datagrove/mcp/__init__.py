"""MCP server primitives for exposing data packages to AI agents (task 4.11).

Stateless tool surface — each tool takes a ``source`` path/URL and
loads the package fresh per call. See :func:`build_server` for the
generic tools (``describe_package``, ``validate_package``,
``list_tables``). Domain packages (e.g. :mod:`gmnspy.mcp`) layer
network-aware tools on top by passing the same :class:`FastMCP`
instance through their own ``build_server``.

This module imports ``mcp`` lazily so ``import datagrove`` doesn't
fail without the optional dependency installed.
"""

from .server import build_server

__all__ = ["build_server"]
