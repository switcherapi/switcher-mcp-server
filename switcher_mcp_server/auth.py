"""Resource-server authentication for the streamable HTTP transport.

In HTTP mode the MCP client performs the OAuth flow (discovery, dynamic client registration, browser
consent) on the user's side against switcher-api and sends the resulting access token as a Bearer token.
The server only advertises protected-resource metadata and forwards that token to switcher-api.
"""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlparse

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from switcher_mcp_server.oauth_client import DEFAULT_SCOPE, DEFAULT_SWITCHER_API_URL
from switcher_mcp_server.tools import shared

LOGGER = logging.getLogger(__name__)

PUBLIC_URL_ENV = 'SWITCHER_MCP_PUBLIC_URL'
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}


class PassthroughTokenVerifier:  # pylint: disable=too-few-public-methods
    """Accepts any non-empty bearer token; switcher-api is the authority that validates it and its scopes."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """Wrap the raw token so tools can forward it to switcher-api."""

        if not token:
            return None

        await asyncio.sleep(0)

        # The SDK enforces required_scopes locally, so the scope the server advertises is assumed here;
        # switcher-api enforces the scopes actually granted to the token.
        return AccessToken(token=token, client_id='switcher-mcp-client', scopes=[DEFAULT_SCOPE])


def resolve_public_url(host: str, port: int, public_url: str | None = None) -> str:
    """Resolve the externally reachable MCP resource URL used as the resource identifier."""

    configured = public_url or os.getenv(PUBLIC_URL_ENV)
    if configured:
        return configured.rstrip('/')

    advertised_host = '127.0.0.1' if host in ('0.0.0.0', '::') else host
    return f'http://{advertised_host}:{port}'  # NOSONAR - loopback-only local dev URL


def build_auth_settings(public_url: str, api_url: str | None = None) -> AuthSettings:
    """Build the AuthSettings pointing clients at switcher-api's authorization server."""

    issuer = (api_url or os.getenv('SWITCHER_API_URL', DEFAULT_SWITCHER_API_URL)).rstrip('/')
    return AuthSettings(
        issuer_url=issuer,  # type: ignore[arg-type]
        resource_server_url=public_url,  # type: ignore[arg-type]
        required_scopes=[DEFAULT_SCOPE],
    )


def configure_http_auth(server: MCPServer, host: str, port: int, public_url: str | None = None) -> str:
    """Enable bearer-token protection and protected-resource metadata on the shared server."""

    resource_url = resolve_public_url(host, port, public_url)
    parsed = urlparse(resource_url)
    if parsed.scheme == 'http' and parsed.hostname not in LOOPBACK_HOSTS:
        LOGGER.warning(
            'Serving MCP authorization over plain HTTP at %s: bearer tokens travel unencrypted. '
            'Use HTTPS outside development environments.',
            resource_url,
        )

    server.settings.auth = build_auth_settings(resource_url)
    # MCPServer only accepts auth at construction time, but the shared instance is created at import
    # time before the transport is known, so it is enabled here for the HTTP transport only.
    server._token_verifier = PassthroughTokenVerifier()  # pylint: disable=protected-access
    shared.enable_request_token_auth()
    return resource_url
