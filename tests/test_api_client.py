"""Tests for the Switcher API client."""

from __future__ import annotations

import asyncio
import json
import ssl
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from switcher_mcp_server.api_client import CERT_PATH_ENV, SwitcherApiClient, SwitcherApiError, _build_verify
from switcher_mcp_server.oauth_client import SwitcherAuthorizationError, SwitcherAuthorizationRequiredError


async def _static_token_provider() -> str:
    return 'access-token'


def test_list_domains_returns_json_payload(httpx_mock) -> None:
    """Owned domains should be returned as parsed JSON."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    httpx_mock.add_response(
        method='GET',
        url='http://127.0.0.1:3000/domain',
        json=[{'_id': 'domain-1', 'name': 'Main Domain'}],
    )

    try:
        domains = asyncio.run(client.list_domains())
        assert domains == [{'_id': 'domain-1', 'name': 'Main Domain'}]
    finally:
        asyncio.run(client.aclose())


def test_list_domain_collaborations_returns_json_payload(httpx_mock) -> None:
    """Collaborative domains should be returned as parsed JSON."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    httpx_mock.add_response(
        method='GET',
        url='http://127.0.0.1:3000/domain/collaboration',
        json=[{'_id': 'domain-2', 'name': 'Shared Domain'}],
    )

    try:
        domains = asyncio.run(client.list_domain_collaborations())
        assert domains == [{'_id': 'domain-2', 'name': 'Shared Domain'}]
    finally:
        asyncio.run(client.aclose())


def test_list_environments_passes_domain_id_query_parameter(httpx_mock) -> None:
    """Environment listing should include the selected domain id."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    httpx_mock.add_response(
        method='GET',
        url='http://127.0.0.1:3000/environment?domain=domain-1',
        json=[{'_id': 'env-1', 'name': 'default'}],
    )

    try:
        environments = asyncio.run(client.list_environments('domain-1'))
        assert environments == [{'_id': 'env-1', 'name': 'default'}]
    finally:
        asyncio.run(client.aclose())


def test_get_config_by_key_includes_domain_and_environment_query(httpx_mock) -> None:
    """Config retrieval should pass the domain and optional environment query parameters."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    httpx_mock.add_response(
        method='GET',
        url='http://127.0.0.1:3000/config/key/sample-flag?domain=Main%20Domain&environment=production',
        json={'key': 'sample-flag', 'enabled': True},
    )

    try:
        config = asyncio.run(client.get_config_by_key('sample-flag', 'Main Domain', 'production'))
        assert config == {'key': 'sample-flag', 'enabled': True}
    finally:
        asyncio.run(client.aclose())


def test_api_client_raises_switcher_api_error_for_non_success_responses(httpx_mock) -> None:
    """Non-2xx responses should raise a descriptive API error."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    httpx_mock.add_response(
        method='GET',
        url='http://127.0.0.1:3000/domain',
        status_code=401,
        json={'error': 'unauthorized'},
    )

    try:
        with pytest.raises(SwitcherApiError, match='HTTP 401'):
            asyncio.run(client.list_domains())
    finally:
        asyncio.run(client.aclose())


def test_api_client_without_oauth_client_propagates_authorization_required(httpx_mock) -> None:
    """A bare token_provider with no oauth_client must keep failing fast on missing auth."""

    token_provider = AsyncMock(side_effect=SwitcherAuthorizationRequiredError('no token'))
    client = SwitcherApiClient(token_provider=token_provider)

    try:
        with pytest.raises(SwitcherAuthorizationRequiredError):
            asyncio.run(client.list_domains())
    finally:
        asyncio.run(client.aclose())


def test_api_client_recovers_via_oauth_client_authorize_if_needed(httpx_mock) -> None:
    """When the token provider needs fresh auth, the client should run authorize_if_needed() and retry."""

    token_provider = AsyncMock(side_effect=SwitcherAuthorizationRequiredError('no token'))
    oauth_client = AsyncMock()
    oauth_client.authorize_if_needed = AsyncMock(return_value='recovered-access-token')

    client = SwitcherApiClient(token_provider=token_provider, oauth_client=oauth_client)
    httpx_mock.add_response(
        method='GET',
        url='http://127.0.0.1:3000/domain',
        json=[{'_id': 'domain-1', 'name': 'Main Domain'}],
    )

    try:
        domains = asyncio.run(client.list_domains())

        assert domains == [{'_id': 'domain-1', 'name': 'Main Domain'}]
        oauth_client.authorize_if_needed.assert_awaited_once()
    finally:
        asyncio.run(client.aclose())


def test_api_client_retries_once_after_401_by_invalidating_cached_token(httpx_mock) -> None:
    """A 401 from the API (e.g. revoked consent) should invalidate the token and retry once."""

    token_provider = AsyncMock(side_effect=['stale-access-token', 'fresh-access-token'])
    oauth_client = AsyncMock()
    oauth_client.invalidate_access_token = lambda: None

    client = SwitcherApiClient(token_provider=token_provider, oauth_client=oauth_client)
    httpx_mock.add_response(method='GET', url='http://127.0.0.1:3000/domain', status_code=401)
    httpx_mock.add_response(
        method='GET',
        url='http://127.0.0.1:3000/domain',
        json=[{'_id': 'domain-1', 'name': 'Main Domain'}],
    )

    try:
        domains = asyncio.run(client.list_domains())

        assert domains == [{'_id': 'domain-1', 'name': 'Main Domain'}]
        assert token_provider.await_count == 2
    finally:
        asyncio.run(client.aclose())


def test_api_client_does_not_retry_401_when_second_attempt_also_fails(httpx_mock) -> None:
    """If consent is still missing after re-auth, the second 401 should surface as an error."""

    token_provider = AsyncMock(side_effect=['stale-access-token', 'still-invalid-token'])
    oauth_client = AsyncMock()
    oauth_client.invalidate_access_token = lambda: None

    client = SwitcherApiClient(token_provider=token_provider, oauth_client=oauth_client)
    httpx_mock.add_response(method='GET', url='http://127.0.0.1:3000/domain', status_code=401)
    httpx_mock.add_response(method='GET', url='http://127.0.0.1:3000/domain', status_code=401)

    try:
        with pytest.raises(SwitcherApiError, match='HTTP 401'):
            asyncio.run(client.list_domains())
        assert token_provider.await_count == 2
    finally:
        asyncio.run(client.aclose())


def test_api_client_wraps_authorization_timeout_as_api_error(httpx_mock) -> None:
    """A failed/timed-out interactive authorization should surface as a SwitcherApiError."""

    token_provider = AsyncMock(side_effect=SwitcherAuthorizationRequiredError('no token'))
    oauth_client = AsyncMock()
    oauth_client.authorize_if_needed = AsyncMock(side_effect=SwitcherAuthorizationError('timed out'))

    client = SwitcherApiClient(token_provider=token_provider, oauth_client=oauth_client)

    try:
        with pytest.raises(SwitcherApiError, match='Switcher authorization was not completed'):
            asyncio.run(client.list_domains())
    finally:
        asyncio.run(client.aclose())


def _write_valid_credentials(path) -> None:
    path.write_text(
        json.dumps(
            {
                'client_id': 'client-1',
                'redirect_uri': 'http://127.0.0.1:5555/callback',
                'access_token': 'stored-token',
                'refresh_token': 'refresh-token',
                'expires_at': (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        ),
        encoding='utf-8',
    )


def test_api_client_defaults_to_owned_oauth_client_and_closes_it(httpx_mock, monkeypatch, tmp_path) -> None:
    """Without injected auth, the client builds its own OAuth client using stored credentials."""

    credentials_path = tmp_path / 'credentials.json'
    _write_valid_credentials(credentials_path)
    monkeypatch.setenv('SWITCHER_MCP_CREDENTIALS_PATH', str(credentials_path))
    monkeypatch.setenv('SWITCHER_API_URL', 'http://switcher.test/')
    httpx_mock.add_response(
        method='GET',
        url='http://switcher.test/domain',
        match_headers={'Authorization': 'Bearer stored-token'},
        json=[],
    )

    client = SwitcherApiClient()
    try:
        assert asyncio.run(client.list_domains()) == []
    finally:
        asyncio.run(client.aclose())


def test_api_client_does_not_close_injected_http_client(httpx_mock) -> None:
    """Injected HTTP clients stay open after aclose()."""

    http_client = httpx.AsyncClient(base_url='http://127.0.0.1:3000')
    client = SwitcherApiClient(token_provider=_static_token_provider, http_client=http_client)
    httpx_mock.add_response(method='GET', url='http://127.0.0.1:3000/config/key/flag?domain=Main', json={})

    try:
        asyncio.run(client.get_config_by_key('flag', 'Main'))
        asyncio.run(client.aclose())
        assert not http_client.is_closed
    finally:
        asyncio.run(http_client.aclose())


def test_api_client_raises_when_response_is_not_json(httpx_mock) -> None:
    """Successful responses with a non-JSON body should raise a descriptive API error."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    httpx_mock.add_response(method='GET', url='http://127.0.0.1:3000/domain', content=b'<html>')

    try:
        with pytest.raises(SwitcherApiError, match='not valid JSON') as error_info:
            asyncio.run(client.list_domains())
        assert error_info.value.status_code == 200
    finally:
        asyncio.run(client.aclose())


def test_build_verify_defaults_to_true_without_a_cert(monkeypatch) -> None:
    """With no cert configured (argument or env var), verification uses the default CA bundle."""

    monkeypatch.delenv(CERT_PATH_ENV, raising=False)
    assert _build_verify() is True


def test_build_verify_returns_ssl_context_for_explicit_cert_path(monkeypatch) -> None:
    """An explicit cert path builds an SSLContext pinned to that certificate."""

    monkeypatch.delenv(CERT_PATH_ENV, raising=False)
    seen_certfiles = []

    def fake_load_cert_chain(self, certfile=None, keyfile=None, password=None):  # noqa: ANN001
        seen_certfiles.append(certfile)

    monkeypatch.setattr(ssl.SSLContext, 'load_cert_chain', fake_load_cert_chain)

    context = _build_verify('/etc/certs/ca.crt')

    assert isinstance(context, ssl.SSLContext)
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert seen_certfiles == ['/etc/certs/ca.crt']


def test_build_verify_falls_back_to_env_var_cert_path(monkeypatch) -> None:
    """When no explicit cert path is passed, the env var is used instead."""

    monkeypatch.setenv(CERT_PATH_ENV, '/etc/certs/env.crt')
    seen_certfiles = []
    monkeypatch.setattr(
        ssl.SSLContext,
        'load_cert_chain',
        lambda self, certfile=None, keyfile=None, password=None: seen_certfiles.append(certfile),
    )

    context = _build_verify()

    assert isinstance(context, ssl.SSLContext)
    assert seen_certfiles == ['/etc/certs/env.crt']


def test_api_client_uses_cert_path_to_build_owned_http_client(monkeypatch) -> None:
    """The client builds its own http client with verify derived from the given cert path."""

    captured = {}

    class _FakeAsyncClient:
        def __init__(self, *, base_url, timeout, verify):  # noqa: ANN001
            captured['verify'] = verify
            self.base_url = base_url
            self.timeout = timeout

        async def aclose(self):
            return None

    monkeypatch.setattr(httpx, 'AsyncClient', _FakeAsyncClient)
    monkeypatch.setattr(
        ssl.SSLContext,
        'load_cert_chain',
        lambda self, certfile=None, keyfile=None, password=None: None,
    )

    client = SwitcherApiClient(token_provider=_static_token_provider, cert_path='/etc/certs/ca.crt')
    try:
        assert isinstance(captured['verify'], ssl.SSLContext)
    finally:
        asyncio.run(client.aclose())
