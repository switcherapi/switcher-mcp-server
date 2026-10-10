"""Shared MCP server instance and API client used by all registered tools."""

from __future__ import annotations

from mcp.server import MCPServer

from switcher_mcp_server import __version__
from switcher_mcp_server.api_client import SwitcherApiClient
from switcher_mcp_server.oauth_client import SwitcherOAuthClient

mcp = MCPServer(
    name='switcher-mcp-server',
    title='Switcher MCP Server',
    description='Switcher MCP context tools.',
    version=__version__,
)

_API_CLIENT: SwitcherApiClient | None = None


def get_mcp_server() -> MCPServer[None]:
    """Return the shared MCP server instance for tool registration."""

    return mcp


def get_api_client() -> SwitcherApiClient:
    """Resolve the shared API client used by all registered tool handlers."""

    return _get_api_client()


def _get_api_client() -> SwitcherApiClient:
    """Resolve the API client used by tool handlers."""

    global _API_CLIENT  # pylint: disable=global-statement
    if _API_CLIENT is not None:
        return _API_CLIENT

    oauth_client = SwitcherOAuthClient()
    _API_CLIENT = SwitcherApiClient(
        oauth_client=oauth_client,
        base_url=oauth_client.base_url,
    )
    return _API_CLIENT
