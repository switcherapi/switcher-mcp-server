"""Tests for streamable HTTP resource-server authentication and bearer-token pass-through."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from unittest.mock import MagicMock

import anyio
import httpx
import httpx2
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from switcher_mcp_server import auth
from switcher_mcp_server.api_client import SwitcherApiClient, SwitcherApiError
from switcher_mcp_server.tools import shared


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_verifier_accepts_non_empty_token_and_rejects_empty() -> None:
    """The verifier defers validation to switcher-api but never accepts a blank token."""

    verifier = auth.PassthroughTokenVerifier()

    accepted = asyncio.run(verifier.verify_token('abc'))
    assert accepted is not None
    assert accepted.token == 'abc'
    assert asyncio.run(verifier.verify_token('')) is None


def test_resolve_public_url_prefers_explicit_value(monkeypatch) -> None:
    """An explicit URL wins over the environment and the bind address."""

    monkeypatch.setenv(auth.PUBLIC_URL_ENV, 'https://env.example.com/')
    assert auth.resolve_public_url('0.0.0.0', 8000, 'https://explicit.example.com/') == 'https://explicit.example.com'
    assert auth.resolve_public_url('0.0.0.0', 8000) == 'https://env.example.com'


def test_resolve_public_url_defaults_to_bind_address(monkeypatch) -> None:
    """Without configuration the URL is derived from host and port; wildcard hosts map to loopback."""

    monkeypatch.delenv(auth.PUBLIC_URL_ENV, raising=False)
    assert auth.resolve_public_url('0.0.0.0', 8000) == 'http://127.0.0.1:8000'
    assert auth.resolve_public_url('10.0.0.5', 9000) == 'http://10.0.0.5:9000'


def test_build_auth_settings_points_to_switcher_api() -> None:
    """The authorization server advertised to clients is switcher-api itself."""

    settings = auth.build_auth_settings('http://vm:8000', 'http://api.local:3000/')

    assert str(settings.issuer_url).rstrip('/') == 'http://api.local:3000'
    assert str(settings.resource_server_url).rstrip('/') == 'http://vm:8000'


def test_api_client_forwards_request_token_without_local_oauth(httpx_mock) -> None:
    """In request-token mode the caller's bearer token is sent and no browser flow is attempted."""

    client = SwitcherApiClient(request_token_getter=lambda: 'caller-token')
    httpx_mock.add_response(
        method='GET',
        url='http://localhost:3000/domain',
        json=[],
        match_headers={'Authorization': 'Bearer caller-token'},
    )

    try:
        assert asyncio.run(client.list_domains()) == []
    finally:
        asyncio.run(client.aclose())


def test_api_client_fails_without_request_token() -> None:
    """A missing caller token is reported as a 401 instead of opening a browser."""

    client = SwitcherApiClient(request_token_getter=lambda: None)

    try:
        with pytest.raises(SwitcherApiError) as error:
            asyncio.run(client.list_domains())
        assert error.value.status_code == 401
    finally:
        asyncio.run(client.aclose())


def test_api_client_reports_rejected_request_token(httpx_mock) -> None:
    """A 401 from switcher-api surfaces a re-authorize hint and is not retried."""

    client = SwitcherApiClient(request_token_getter=lambda: 'stale')
    httpx_mock.add_response(method='GET', url='http://localhost:3000/domain', status_code=401, text='denied')

    try:
        with pytest.raises(SwitcherApiError, match='re-authorize') as error:
            asyncio.run(client.list_domains())
        assert error.value.status_code == 401
    finally:
        asyncio.run(client.aclose())


def test_configure_http_auth_enables_verifier_and_request_token_mode(monkeypatch) -> None:
    """Configuring HTTP auth wires settings, the verifier and the request-token API client."""

    monkeypatch.setattr(shared, '_REQUEST_TOKEN_AUTH', False)
    monkeypatch.setattr(shared, '_API_CLIENT', None)
    fake_server = MagicMock()

    url = auth.configure_http_auth(fake_server, '0.0.0.0', 8000, 'http://vm.example:8000')

    assert url == 'http://vm.example:8000'
    assert isinstance(fake_server._token_verifier, auth.PassthroughTokenVerifier)  # pylint: disable=protected-access
    assert fake_server.settings.auth is not None
    assert shared._REQUEST_TOKEN_AUTH is True  # pylint: disable=protected-access


def test_streamable_http_requires_bearer_token_and_serves_metadata(monkeypatch) -> None:
    """A live HTTP server rejects anonymous calls with a 401 challenge and advertises switcher-api."""

    monkeypatch.setattr(shared, '_REQUEST_TOKEN_AUTH', False)
    monkeypatch.setattr(shared, '_API_CLIENT', None)
    server = shared.get_mcp_server()
    monkeypatch.setattr(server.settings, 'auth', None)
    monkeypatch.setattr(server, '_token_verifier', None)

    port = _free_port()
    public_url = f'http://127.0.0.1:{port}'
    auth.configure_http_auth(server, '127.0.0.1', port, public_url)

    config = uvicorn.Config(
        server.streamable_http_app(host='127.0.0.1'), host='127.0.0.1', port=port, log_level='error'
    )
    uvicorn_server = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    time.sleep(1.0)

    try:
        anonymous = httpx.post(f'{public_url}/mcp', json={})
        assert anonymous.status_code == 401
        assert 'resource_metadata' in anonymous.headers['www-authenticate']

        metadata = httpx.get(f'{public_url}/.well-known/oauth-protected-resource').json()
        assert metadata['authorization_servers']
        assert metadata['scopes_supported'] == ['config:read']

        async def _list_with_token() -> set[str]:
            http_client = httpx2.AsyncClient(headers={'Authorization': 'Bearer test-token'})
            async with streamable_http_client(f'{public_url}/mcp', http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return {tool.name for tool in (await session.list_tools()).tools}

        assert 'list_domains' in anyio.run(_list_with_token)
    finally:
        uvicorn_server.should_exit = True
        thread.join(timeout=5)
