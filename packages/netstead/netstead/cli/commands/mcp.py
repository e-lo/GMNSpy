"""``netstead mcp`` — stateless MCP server over stdio (issue #94)."""

from __future__ import annotations

import typer

from .._extras import require_extra

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the ``mcp`` sub-app on ``app``."""
    mcp_app = typer.Typer(no_args_is_help=True, help="Run the netstead MCP server for AI-agent access.")
    app.add_typer(mcp_app, name="mcp")

    @mcp_app.command(name="serve")
    def mcp_serve(
        name: str = typer.Option("netstead", "--name", help="MCP server display name."),
    ) -> None:
        """Start the netstead MCP server on stdio (for Claude Desktop / Claude Code).

        Configure your MCP client to launch ``netstead mcp serve`` as a
        subprocess (typical example:

        .. code-block:: json

            {"mcpServers": {"netstead": {"command": "netstead", "args": ["mcp", "serve"]}}}

        ). Tools exposed: ``describe_network``, ``validate_package``,
        ``quality_check``, ``connected_components``, ``scope_from_nodes``,
        plus the generic corral tools.
        """
        netstead_mcp = require_extra("netstead.mcp", "mcp")

        server = netstead_mcp.build_server(name=name)
        # FastMCP.run() defaults to stdio when called with no transport;
        # stdio is what MCP-host applications expect (Claude Desktop,
        # Claude Code, etc.).
        server.run()
