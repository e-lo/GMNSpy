"""OPTIONAL EXTRA — GMNS MCP server for AI-agent access (task 4.11).

Install: ``pip install gmnspy[mcp]``. Run via ``gmnspy mcp serve``
(CLI command added in this PR) which starts the FastMCP server on the
stdio transport — point Claude Desktop or Claude Code at the binary
via their MCP config.

Tools (all stateless, take a ``source`` path/URL per call):

* Generic (inherited from :mod:`datagrove.mcp`): ``describe_package``,
  ``validate_package``, ``list_tables``.
* GMNS-aware (added here): ``describe_network``, ``quality_check``,
  ``connected_components``, ``scope_from_nodes``.

Stateful tools — ``edit_session`` with rollback — deferred to a
follow-up; the rollback semantics in tool form need careful design.
"""

try:
    import mcp  # noqa: F401
except ImportError as e:  # pragma: no cover - defensive
    raise ImportError("gmnspy.mcp requires the [mcp] extra: pip install 'gmnspy[mcp]'") from e

from .server import build_server

__all__ = ["build_server"]
