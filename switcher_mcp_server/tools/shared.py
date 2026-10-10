"""Shared MCP server instance and API client used by all registered tools."""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token

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
_REQUEST_TOKEN_AUTH = False


def enable_request_token_auth() -> None:
    """Switch the API client to forward the caller's bearer token (streamable HTTP mode)."""

    global _REQUEST_TOKEN_AUTH, _API_CLIENT  # pylint: disable=global-statement
    _REQUEST_TOKEN_AUTH = True
    _API_CLIENT = None


def _get_request_token() -> str | None:
    """Return the bearer token of the current MCP request, if any."""

    access_token = get_access_token()
    return access_token.token if access_token else None


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
    if _REQUEST_TOKEN_AUTH:
        _API_CLIENT = SwitcherApiClient(
            base_url=oauth_client.base_url,
            request_token_getter=_get_request_token,
        )
        return _API_CLIENT

    _API_CLIENT = SwitcherApiClient(
        oauth_client=oauth_client,
        base_url=oauth_client.base_url,
    )
    return _API_CLIENT
