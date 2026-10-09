"""Tests for the Switcher OAuth client."""

from __future__ import annotations

import asyncio
import json
import queue
import shutil
import socket
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest

from switcher_mcp_server import oauth_client as oauth_module
from switcher_mcp_server.oauth_client import (
    DEFAULT_SWITCHER_API_URL,
    SwitcherAuthorizationError,
    SwitcherAuthorizationRequiredError,
    SwitcherOAuthClient,
    SwitcherOAuthError,
    StoredCredentials,
)

TEST_ARTIFACTS_DIR = Path(__file__).resolve().parent / '_artifacts'


def _create_credentials_path() -> Path:
    test_directory = TEST_ARTIFACTS_DIR / f'oauth-{uuid4().hex}'
    test_directory.mkdir(parents=True, exist_ok=False)
    return test_directory / 'credentials.json'


def _cleanup_credentials_path(credentials_path: Path) -> None:
    shutil.rmtree(credentials_path.parent, ignore_errors=True)


def _mock_metadata(httpx_mock) -> None:
    httpx_mock.add_response(
        method='GET',
        url=f'{DEFAULT_SWITCHER_API_URL}/.well-known/oauth-authorization-server',
        json={
            'issuer': DEFAULT_SWITCHER_API_URL,
            'authorization_endpoint': f'{DEFAULT_SWITCHER_API_URL}/oauth/authorize',
            'token_endpoint': f'{DEFAULT_SWITCHER_API_URL}/oauth/token',
            'registration_endpoint': f'{DEFAULT_SWITCHER_API_URL}/oauth/register',
            'scopes_supported': ['config:read'],
            'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code', 'refresh_token'],
            'code_challenge_methods_supported': ['S256'],
            'token_endpoint_auth_methods_supported': ['none'],
        },
    )


def test_generate_pkce_pair_uses_s256_relationship() -> None:
    """Generated PKCE values should follow the S256 challenge specification."""

    code_verifier, code_challenge = SwitcherOAuthClient.generate_pkce_pair()

    assert 43 <= len(code_verifier) <= 128
    assert code_challenge == SwitcherOAuthClient.build_code_challenge(code_verifier)


def test_credentials_round_trip_persists_expected_values() -> None:
    """Credentials should survive a save/load cycle."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)
    reloaded_client: SwitcherOAuthClient | None = None
    expected_expiry = datetime.now(UTC) + timedelta(minutes=5)

    try:
        client.save_credentials(
            StoredCredentials(
                client_id='client-123',
                redirect_uri='http://127.0.0.1:4100/callback',
                access_token='access-token',
                refresh_token='refresh-token',
                expires_at=expected_expiry,
            )
        )

        reloaded_client = SwitcherOAuthClient(credentials_path=credentials_path)
        loaded_credentials = reloaded_client.load_credentials()

        assert loaded_credentials.client_id == 'client-123'
        assert loaded_credentials.redirect_uri == 'http://127.0.0.1:4100/callback'
        assert loaded_credentials.access_token == 'access-token'
        assert loaded_credentials.refresh_token == 'refresh-token'
        assert loaded_credentials.expires_at == expected_expiry
    finally:
        asyncio.run(client.aclose())
        if reloaded_client is not None:
            asyncio.run(reloaded_client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_register_posts_expected_dynamic_client_payload(httpx_mock) -> None:
    """Client registration should send the expected request shape and persist its response."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)
    captured_requests: list[dict[str, object]] = []

    _mock_metadata(httpx_mock)

    def registration_callback(request):
        captured_requests.append(
            {
                'content_type': request.headers['Content-Type'],
                'payload': json.loads(request.content.decode('utf-8')),
            }
        )
        return httpx.Response(
            status_code=201,
            json={
                'client_id': 'registered-client',
                'client_id_issued_at': 1234567890,
                'client_name': 'Switcher MCP Server',
                'redirect_uris': ['http://127.0.0.1:4100/callback'],
                'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'],
                'token_endpoint_auth_method': 'none',
                'scope': 'config:read',
            },
        )

    httpx_mock.add_callback(
        registration_callback,
        method='POST',
        url=f'{DEFAULT_SWITCHER_API_URL}/oauth/register',
    )

    try:
        registered_client_id = asyncio.run(client.register())
        persisted_credentials = client.load_credentials()

        assert registered_client_id == 'registered-client'
        assert captured_requests == [
            {
                'content_type': 'application/json',
                'payload': {
                    'client_name': 'Switcher MCP Server',
                    'redirect_uris': [persisted_credentials.redirect_uri],
                },
            }
        ]
        assert persisted_credentials.client_id == 'registered-client'
        assert persisted_credentials.redirect_uri is not None
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_build_authorization_url_contains_required_oauth_parameters(httpx_mock) -> None:
    """Authorization URL builder should include the RFC-required PKCE parameters."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)

    _mock_metadata(httpx_mock)
    httpx_mock.add_response(
        method='POST',
        url=f'{DEFAULT_SWITCHER_API_URL}/oauth/register',
        status_code=201,
        json={
            'client_id': 'registered-client',
            'client_id_issued_at': 1234567890,
            'client_name': 'Switcher MCP Server',
            'redirect_uris': ['http://127.0.0.1:5555/callback'],
            'grant_types': ['authorization_code', 'refresh_token'],
            'response_types': ['code'],
            'token_endpoint_auth_method': 'none',
            'scope': 'config:read',
        },
    )

    try:
        authorization_url = asyncio.run(
            client.build_authorization_url(
                redirect_uri='http://127.0.0.1:5555/callback',
                state='expected-state',
                code_challenge='expected-challenge',
            )
        )
        parsed_url = urlparse(authorization_url)
        query = parse_qs(parsed_url.query)

        assert parsed_url.scheme == 'http'
        assert parsed_url.netloc == 'localhost:3000'
        assert parsed_url.path == '/oauth/authorize'
        assert query['response_type'] == ['code']
        assert query['client_id'] == ['registered-client']
        assert query['redirect_uri'] == ['http://127.0.0.1:5555/callback']
        assert query['scope'] == ['config:read']
        assert query['state'] == ['expected-state']
        assert query['code_challenge'] == ['expected-challenge']
        assert query['code_challenge_method'] == ['S256']
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_finalize_authorization_callback_validates_state_and_exchanges_code(httpx_mock) -> None:
    """Callback finalization should validate state and persist the exchanged token pair."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)
    client.save_credentials(
        StoredCredentials(
            client_id='registered-client',
            redirect_uri='http://127.0.0.1:5555/callback',
        )
    )

    _mock_metadata(httpx_mock)
    httpx_mock.add_response(
        method='POST',
        url=f'{DEFAULT_SWITCHER_API_URL}/oauth/token',
        json={
            'access_token': 'fresh-access-token',
            'token_type': 'Bearer',
            'expires_in': 3600,
            'refresh_token': 'fresh-refresh-token',
            'scope': 'config:read',
        },
    )

    try:
        updated_credentials = asyncio.run(
            client.finalize_authorization_callback(
                callback_parameters={'code': 'auth-code', 'state': 'expected-state'},
                expected_state='expected-state',
                redirect_uri='http://127.0.0.1:5555/callback',
                code_verifier='verifier-value',
            )
        )

        assert updated_credentials.access_token == 'fresh-access-token'
        assert updated_credentials.refresh_token == 'fresh-refresh-token'
        assert updated_credentials.expires_at is not None
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_finalize_authorization_callback_rejects_invalid_state() -> None:
    """Callback finalization should reject mismatched OAuth state values."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)

    try:
        with pytest.raises(SwitcherAuthorizationError, match='state did not match'):
            asyncio.run(
                client.finalize_authorization_callback(
                    callback_parameters={'code': 'auth-code', 'state': 'wrong-state'},
                    expected_state='expected-state',
                    redirect_uri='http://127.0.0.1:5555/callback',
                    code_verifier='verifier-value',
                    client_id='registered-client',
                )
            )
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_get_valid_access_token_uses_refresh_when_token_is_expired(httpx_mock) -> None:
    """Expired access tokens should trigger a refresh-token exchange."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)
    client.save_credentials(
        StoredCredentials(
            client_id='registered-client',
            redirect_uri='http://127.0.0.1:5555/callback',
            access_token='expired-access-token',
            refresh_token='refresh-token',
            expires_at=datetime.now(UTC) - timedelta(seconds=5),
        )
    )

    _mock_metadata(httpx_mock)
    httpx_mock.add_response(
        method='POST',
        url=f'{DEFAULT_SWITCHER_API_URL}/oauth/token',
        json={
            'access_token': 'new-access-token',
            'token_type': 'Bearer',
            'expires_in': 1800,
            'refresh_token': 'rotated-refresh-token',
            'scope': 'config:read',
        },
    )

    try:
        access_token = asyncio.run(client.get_valid_access_token())
        persisted_credentials = client.load_credentials()

        assert access_token == 'new-access-token'
        assert persisted_credentials.refresh_token == 'rotated-refresh-token'
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_get_valid_access_token_requires_fresh_authorization_when_refresh_fails(httpx_mock) -> None:
    """Refresh failures should instruct callers to run authorize() again."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)
    client.save_credentials(
        StoredCredentials(
            client_id='registered-client',
            redirect_uri='http://127.0.0.1:5555/callback',
            access_token='expired-access-token',
            refresh_token='refresh-token',
            expires_at=datetime.now(UTC) - timedelta(seconds=5),
        )
    )

    _mock_metadata(httpx_mock)
    httpx_mock.add_response(
        method='POST',
        url=f'{DEFAULT_SWITCHER_API_URL}/oauth/token',
        status_code=400,
        json={'error': 'invalid_grant'},
    )

    try:
        with pytest.raises(SwitcherAuthorizationRequiredError, match='Run authorize\\(\\)'):
            asyncio.run(client.get_valid_access_token())
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_invalidate_access_token_clears_token_but_keeps_refresh_token() -> None:
    """Invalidating the cached token should force the next refresh/authorize attempt."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)
    client.save_credentials(
        StoredCredentials(
            client_id='registered-client',
            redirect_uri='http://127.0.0.1:5555/callback',
            access_token='revoked-access-token',
            refresh_token='refresh-token',
            expires_at=datetime.now(UTC) + timedelta(seconds=3600),
        )
    )

    try:
        client.invalidate_access_token()
        persisted_credentials = client.load_credentials()

        assert persisted_credentials.access_token is None
        assert persisted_credentials.expires_at is None
        assert persisted_credentials.refresh_token == 'refresh-token'
        assert persisted_credentials.client_id == 'registered-client'
        assert not persisted_credentials.access_token_is_valid()
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_authorize_if_needed_returns_cached_token_without_opening_browser(monkeypatch) -> None:
    """A valid cached access token should be returned without running authorize()."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)
    client.save_credentials(
        StoredCredentials(
            client_id='registered-client',
            redirect_uri='http://127.0.0.1:5555/callback',
            access_token='cached-access-token',
            refresh_token='refresh-token',
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )

    authorize_mock = AsyncMock(side_effect=AssertionError('authorize() should not be called'))
    monkeypatch.setattr(client, 'authorize', authorize_mock)

    try:
        access_token = asyncio.run(client.authorize_if_needed())

        assert access_token == 'cached-access-token'
        authorize_mock.assert_not_called()
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_authorize_if_needed_runs_browser_flow_when_no_token_available(monkeypatch) -> None:
    """With no usable cached/refresh token, authorize() should run the browser flow."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)

    authorize_mock = AsyncMock(return_value='fresh-access-token')
    monkeypatch.setattr(client, 'authorize', authorize_mock)

    try:
        access_token = asyncio.run(client.authorize_if_needed())

        assert access_token == 'fresh-access-token'
        authorize_mock.assert_awaited_once()
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def test_authorize_if_needed_triggers_single_authorize_for_concurrent_callers(monkeypatch) -> None:
    """Concurrent callers should only trigger a single authorize() invocation."""

    credentials_path = _create_credentials_path()
    client = SwitcherOAuthClient(credentials_path=credentials_path)

    async def _slow_authorize(timeout_seconds: int = 300) -> str:
        await asyncio.sleep(0.05)
        client.save_credentials(
            StoredCredentials(
                client_id='registered-client',
                redirect_uri='http://127.0.0.1:5555/callback',
                access_token='fresh-access-token',
                refresh_token='refresh-token',
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
        )
        return 'fresh-access-token'

    authorize_mock = AsyncMock(side_effect=_slow_authorize)
    monkeypatch.setattr(client, 'authorize', authorize_mock)

    async def _run_concurrent_callers() -> list[str]:
        return await asyncio.gather(
            client.authorize_if_needed(),
            client.authorize_if_needed(),
        )

    try:
        results = asyncio.run(_run_concurrent_callers())

        assert results == ['fresh-access-token', 'fresh-access-token']
        authorize_mock.assert_awaited_once()
    finally:
        asyncio.run(client.aclose())
        _cleanup_credentials_path(credentials_path)


def _token_response(access: str = 'new-access', refresh: str = 'new-refresh') -> dict[str, object]:
    return {'access_token': access, 'token_type': 'Bearer', 'expires_in': 600, 'refresh_token': refresh}


def test_configuration_comes_from_environment(monkeypatch, tmp_path) -> None:
    """Base URL and credentials path should honor environment variables."""

    credentials_path = tmp_path / 'env-credentials.json'
    monkeypatch.setenv('SWITCHER_API_URL', 'http://switcher.test/')
    monkeypatch.setenv('SWITCHER_MCP_CREDENTIALS_PATH', str(credentials_path))
    client = SwitcherOAuthClient()

    assert client.base_url == 'http://switcher.test'
    assert client.credentials_path == credentials_path
    asyncio.run(client.aclose())


def test_credentials_path_defaults_to_home_directory(monkeypatch) -> None:
    """Without overrides the credentials live under the user's home directory."""

    monkeypatch.delenv('SWITCHER_MCP_CREDENTIALS_PATH', raising=False)
    client = SwitcherOAuthClient()

    assert client.credentials_path == Path.home() / '.switcher-mcp' / 'credentials.json'
    asyncio.run(client.aclose())


def test_aclose_keeps_injected_http_client_open() -> None:
    """Injected HTTP clients are owned by the caller."""

    http_client = httpx.AsyncClient()
    client = SwitcherOAuthClient(http_client=http_client)

    asyncio.run(client.aclose())

    assert not http_client.is_closed
    asyncio.run(http_client.aclose())


def test_load_credentials_handles_missing_invalid_and_naive_files(tmp_path) -> None:
    """Loading covers a missing file, malformed JSON, and timezone-naive expiry values."""

    credentials_path = tmp_path / 'credentials.json'
    client = SwitcherOAuthClient(credentials_path=credentials_path)

    assert client.load_credentials() == StoredCredentials()

    broken_client = SwitcherOAuthClient(credentials_path=credentials_path)
    credentials_path.write_text('{not json', encoding='utf-8')
    with pytest.raises(SwitcherOAuthError, match='not valid JSON'):
        broken_client.load_credentials()

    credentials_path.write_text(
        json.dumps({'client_id': 'c', 'access_token': 'a', 'expires_at': '2030-01-01T00:00:00'}),
        encoding='utf-8',
    )
    naive_client = SwitcherOAuthClient(credentials_path=credentials_path)
    loaded = naive_client.load_credentials()

    assert loaded.expires_at == datetime(2030, 1, 1, tzinfo=UTC)
    assert loaded.refresh_token is None
    assert naive_client.load_credentials() is loaded
    assert not loaded.has_registration()

    for oauth_client in (client, broken_client, naive_client):
        asyncio.run(oauth_client.aclose())


def test_register_reuses_existing_registration(tmp_path) -> None:
    """A stored registration must short-circuit without any HTTP call."""

    client = SwitcherOAuthClient(credentials_path=tmp_path / 'credentials.json')
    client.save_credentials(StoredCredentials(client_id='existing', redirect_uri='http://127.0.0.1:1/callback'))

    assert asyncio.run(client.register()) == 'existing'
    asyncio.run(client.aclose())


def test_refresh_requires_a_refresh_token(tmp_path) -> None:
    """Refreshing without stored refresh credentials should require a new sign-in."""

    client = SwitcherOAuthClient(credentials_path=tmp_path / 'credentials.json')

    with pytest.raises(SwitcherAuthorizationRequiredError, match='No refresh token'):
        asyncio.run(client.refresh())
    asyncio.run(client.aclose())


@pytest.mark.parametrize(
    ('parameters', 'message'),
    [
        ({'state': 's', 'error': 'access_denied'}, 'authorization failed: access_denied'),
        ({'state': 's'}, 'did not include an authorization code'),
        ({'state': 's', 'code': 'c'}, 'registration is missing'),
    ],
)
def test_finalize_authorization_callback_rejects_invalid_callbacks(tmp_path, parameters, message) -> None:
    """Error responses, missing codes and missing registrations should be rejected."""

    client = SwitcherOAuthClient(credentials_path=tmp_path / 'credentials.json')

    with pytest.raises(SwitcherAuthorizationError, match=message):
        asyncio.run(
            client.finalize_authorization_callback(
                callback_parameters=parameters,
                expected_state='s',
                redirect_uri='http://127.0.0.1:1/callback',
                code_verifier='v',
            )
        )
    asyncio.run(client.aclose())


def test_discovery_failure_raises_oauth_error(httpx_mock, tmp_path) -> None:
    """HTTP failures during discovery should include status and body details."""

    client = SwitcherOAuthClient(credentials_path=tmp_path / 'credentials.json')
    httpx_mock.add_response(
        method='GET',
        url=f'{DEFAULT_SWITCHER_API_URL}/.well-known/oauth-authorization-server',
        status_code=500,
    )

    with pytest.raises(SwitcherOAuthError, match='HTTP 500 returned <empty response body>'):
        asyncio.run(client.discover_metadata())
    asyncio.run(client.aclose())


def test_refresh_persists_rotated_tokens(httpx_mock, tmp_path) -> None:
    """A successful refresh should persist the new token pair."""

    client = SwitcherOAuthClient(credentials_path=tmp_path / 'credentials.json')
    client.save_credentials(StoredCredentials(client_id='c', redirect_uri='r', refresh_token='old'))
    _mock_metadata(httpx_mock)
    httpx_mock.add_response(method='POST', url=f'{DEFAULT_SWITCHER_API_URL}/oauth/token', json=_token_response())

    refreshed = asyncio.run(client.refresh())

    assert refreshed.access_token == 'new-access'
    assert client.load_credentials().refresh_token == 'new-refresh'
    asyncio.run(client.aclose())


@pytest.mark.parametrize('os_name', ['posix', 'nt'])
def test_restrictive_permissions_are_best_effort(monkeypatch, tmp_path, os_name) -> None:
    """POSIX hosts get chmod 600 (failures ignored); Windows is skipped."""

    chmod_calls: list[int] = []

    def fake_chmod(_path, mode) -> None:
        chmod_calls.append(mode)
        raise OSError('denied')

    monkeypatch.setattr(oauth_module.os, 'name', os_name)
    monkeypatch.setattr(oauth_module.os, 'chmod', fake_chmod)

    SwitcherOAuthClient._apply_restrictive_permissions(tmp_path)  # pylint: disable=protected-access

    assert chmod_calls == ([0o600] if os_name == 'posix' else [])


def _serve_callback(callback_path: str, response_queue: queue.Queue):
    server = oauth_module._OAuthCallbackServer(  # pylint: disable=protected-access
        ('127.0.0.1', 0),
        oauth_module._OAuthCallbackRequestHandler,  # pylint: disable=protected-access
        callback_path=callback_path,
        response_queue=response_queue,
    )
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
    thread.start()
    return server, thread


def test_callback_server_captures_query_ignores_other_paths_and_duplicates() -> None:
    """The loopback handler queues the first callback, 404s other paths and tolerates repeats."""

    response_queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=1)
    server, thread = _serve_callback('/callback', response_queue)
    base = f'http://127.0.0.1:{server.server_address[1]}'

    try:
        with pytest.raises(urllib.error.HTTPError) as not_found:
            urllib.request.urlopen(f'{base}/other', timeout=5)  # noqa: S310
        assert not_found.value.code == 404
        assert response_queue.empty()

        with urllib.request.urlopen(f'{base}/callback?code=abc&state=xyz', timeout=5) as response:  # noqa: S310
            assert response.status == 200
        with urllib.request.urlopen(f'{base}/callback?code=second&state=xyz', timeout=5) as response:  # noqa: S310
            assert response.status == 200

        assert response_queue.get_nowait() == {'code': 'abc', 'state': 'xyz'}
        assert response_queue.empty()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def test_authorize_runs_full_browser_flow(httpx_mock, monkeypatch, tmp_path) -> None:
    """authorize() registers, opens the browser, receives the loopback redirect and stores tokens."""

    client = SwitcherOAuthClient(credentials_path=tmp_path / 'credentials.json')
    _mock_metadata(httpx_mock)
    httpx_mock.add_response(
        method='POST', url=f'{DEFAULT_SWITCHER_API_URL}/oauth/register', status_code=201, json={'client_id': 'cid'}
    )
    token_requests: list[dict[str, str]] = []

    def token_callback(request):
        token_requests.append(json.loads(request.content))
        return httpx.Response(200, json=_token_response('browser-access', 'browser-refresh'))

    httpx_mock.add_callback(token_callback, method='POST', url=f'{DEFAULT_SWITCHER_API_URL}/oauth/token')

    def fake_browser(url: str) -> bool:
        query = parse_qs(urlparse(url).query)
        callback = f"{query['redirect_uri'][0]}?code=the-code&state={query['state'][0]}"
        urllib.request.urlopen(callback, timeout=5).close()  # noqa: S310
        return True

    monkeypatch.setattr(oauth_module.webbrowser, 'open', fake_browser)

    assert asyncio.run(client.authorize(timeout_seconds=10)) == 'browser-access'
    assert token_requests[0]['code'] == 'the-code'
    assert token_requests[0]['client_id'] == 'cid'
    assert client.load_credentials().refresh_token == 'browser-refresh'
    asyncio.run(client.aclose())


def test_authorize_times_out_without_callback(httpx_mock, monkeypatch, tmp_path) -> None:
    """A browser that never redirects should surface a timeout error and release the port."""

    port = _free_port()
    client = SwitcherOAuthClient(credentials_path=tmp_path / 'credentials.json')
    client.save_credentials(StoredCredentials(client_id='cid', redirect_uri=f'http://127.0.0.1:{port}/callback'))
    _mock_metadata(httpx_mock)
    monkeypatch.setattr(oauth_module.webbrowser, 'open', lambda _url: True)

    with pytest.raises(SwitcherAuthorizationError, match='Timed out'):
        asyncio.run(client.authorize(timeout_seconds=0))
    asyncio.run(client.aclose())


def test_authorize_reports_callback_bind_failure(httpx_mock, monkeypatch, tmp_path) -> None:
    """A loopback port that cannot be bound should produce a clear error."""

    client = SwitcherOAuthClient(credentials_path=tmp_path / 'credentials.json')
    client.save_credentials(StoredCredentials(client_id='cid', redirect_uri='http://127.0.0.1:5555/callback'))
    _mock_metadata(httpx_mock)

    def failing_server(*_args, **_kwargs):
        raise OSError('in use')

    monkeypatch.setattr(oauth_module, '_OAuthCallbackServer', failing_server)

    with pytest.raises(SwitcherAuthorizationError, match='Unable to bind'):
        asyncio.run(client.authorize())
    asyncio.run(client.aclose())


@pytest.mark.parametrize('redirect_uri', ['http://localhost:5555/callback', 'http://127.0.0.1/callback'])
def test_authorize_rejects_non_loopback_or_portless_redirects(httpx_mock, tmp_path, redirect_uri) -> None:
    """Only explicit-port 127.0.0.1 redirect URIs are accepted."""

    client = SwitcherOAuthClient(credentials_path=tmp_path / 'credentials.json')
    client.save_credentials(StoredCredentials(client_id='cid', redirect_uri=redirect_uri))
    _mock_metadata(httpx_mock)

    with pytest.raises(SwitcherAuthorizationError, match='127.0.0.1 loopback'):
        asyncio.run(client.authorize())
    asyncio.run(client.aclose())


def test_credentials_without_expiry_are_not_valid() -> None:
    """Credentials persisted without an expiry never count as a usable access token."""

    credentials = StoredCredentials.from_dict({'client_id': 'c', 'access_token': 'a'})

    assert credentials.expires_at is None
    assert not credentials.access_token_is_valid()
