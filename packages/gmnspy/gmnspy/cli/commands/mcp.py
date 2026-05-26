"""``gmnspy mcp`` — stateless MCP server over stdio (issue #94)."""

from __future__ import annotations

import typer

from .._extras import require_extra

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the ``mcp`` sub-app on ``app``."""
    mcp_app = typer.Typer(no_args_is_help=True, help="Run the gmnspy MCP server for AI-agent access.")
    app.add_typer(mcp_app, name="mcp")

    @mcp_app.command(name="serve")
    def mcp_serve(
        name: str = typer.Option("gmnspy", "--name", help="MCP server display name."),
    ) -> None:
        """Start the gmnspy MCP server on stdio (for Claude Desktop / Claude Code).

        Configure your MCP client to launch ``gmnspy mcp serve`` as a
        subprocess (typical example:

        .. code-block:: json

            {"mcpServers": {"gmnspy": {"command": "gmnspy", "args": ["mcp", "serve"]}}}

        ). Tools exposed: ``describe_network``, ``validate_package``,
        ``quality_check``, ``connected_components``, ``scope_from_nodes``,
        plus the generic datagrove tools.
        """
        gmnspy_mcp = require_extra("gmnspy.mcp", "mcp")

        server = gmnspy_mcp.build_server(name=name)
        # FastMCP.run() defaults to stdio when called with no transport;
        # stdio is what MCP-host applications expect (Claude Desktop,
        # Claude Code, etc.).
        server.run()
