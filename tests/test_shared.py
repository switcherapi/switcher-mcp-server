"""Tests for the shared MCP server and API client wiring."""

from __future__ import annotations

import asyncio

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from switcher_mcp_server.tools import shared


def test_get_request_token_returns_none_without_authenticated_user() -> None:
    """Outside an authenticated HTTP request (e.g. stdio) there is no caller token."""

    assert shared._get_request_token() is None  # pylint: disable=protected-access


def test_get_request_token_returns_token_of_authenticated_user() -> None:
    """The bearer token of the authenticated request is exposed to the API client."""

    access_token = AccessToken(token='caller-token', client_id='client', scopes=['config:read'])
    context_token = auth_context_var.set(AuthenticatedUser(access_token))
    try:
        assert shared._get_request_token() == 'caller-token'  # pylint: disable=protected-access
    finally:
        auth_context_var.reset(context_token)


def test_request_token_mode_builds_client_that_forwards_caller_token(monkeypatch) -> None:
    """In request-token mode the client has no local OAuth flow and reads the caller's token."""

    monkeypatch.setattr(shared, '_API_CLIENT', None)
    monkeypatch.setattr(shared, '_REQUEST_TOKEN_AUTH', True)
    monkeypatch.setenv('SWITCHER_API_URL', 'http://switcher.test')

    client = shared.get_api_client()
    try:
        assert client is shared.get_api_client()
        assert client._oauth_client is None  # pylint: disable=protected-access
        assert client._request_token_getter is shared._get_request_token  # pylint: disable=protected-access
        assert client._base_url == 'http://switcher.test'  # pylint: disable=protected-access
    finally:
        asyncio.run(client.aclose())


def test_enable_request_token_auth_resets_cached_client(monkeypatch) -> None:
    """Enabling request-token mode must discard a client previously built for stdio."""

    monkeypatch.setattr(shared, '_API_CLIENT', object())
    monkeypatch.setattr(shared, '_REQUEST_TOKEN_AUTH', False)

    shared.enable_request_token_auth()

    assert shared._API_CLIENT is None  # pylint: disable=protected-access
    assert shared._REQUEST_TOKEN_AUTH is True  # pylint: disable=protected-access


def test_shared_api_client_is_built_once_from_environment(monkeypatch, tmp_path) -> None:
    """Tools should lazily build a single API client wired to the configured Switcher URL."""

    monkeypatch.setattr(shared, '_API_CLIENT', None)
    monkeypatch.setenv('SWITCHER_API_URL', 'http://switcher.test')
    monkeypatch.setenv('SWITCHER_MCP_CREDENTIALS_PATH', str(tmp_path / 'credentials.json'))

    first = shared.get_api_client()
    try:
        assert first is shared.get_api_client()
        assert first._base_url == 'http://switcher.test'  # pylint: disable=protected-access
    finally:
        asyncio.run(first.aclose())
