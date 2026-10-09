"""OAuth client utilities for Switcher MCP integrations."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import queue
import secrets
import socket
import threading
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Mapping, cast
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

DEFAULT_SWITCHER_API_URL = 'http://localhost:3000'
DEFAULT_SCOPE = 'config:read'
DEFAULT_CLIENT_NAME = 'Switcher MCP Server'
DEFAULT_AUTHORIZATION_TIMEOUT_SECONDS = 300
DISCOVERY_PATH = '/.well-known/oauth-authorization-server'
CALLBACK_PATH = '/callback'


class SwitcherOAuthError(RuntimeError):
    """Raised when the Switcher OAuth flow fails."""


class SwitcherAuthorizationError(SwitcherOAuthError):
    """Raised when interactive authorization cannot be completed."""


class SwitcherAuthorizationRequiredError(SwitcherOAuthError):
    """Raised when a fresh browser authorization is required."""


@dataclass(slots=True)
# pylint: disable=too-many-instance-attributes
class AuthorizationServerMetadata:
    """OpenID-style authorization server metadata exposed by Switcher API."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    scopes_supported: list[str]
    response_types_supported: list[str]
    grant_types_supported: list[str]
    code_challenge_methods_supported: list[str]
    token_endpoint_auth_methods_supported: list[str]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> 'AuthorizationServerMetadata':
        """Build metadata from a discovery response."""

        return cls(
            issuer=str(payload['issuer']),
            authorization_endpoint=str(payload['authorization_endpoint']),
            token_endpoint=str(payload['token_endpoint']),
            registration_endpoint=str(payload['registration_endpoint']),
            scopes_supported=[str(item) for item in payload.get('scopes_supported', [])],
            response_types_supported=[str(item) for item in payload.get('response_types_supported', [])],
            grant_types_supported=[str(item) for item in payload.get('grant_types_supported', [])],
            code_challenge_methods_supported=[
                str(item) for item in payload.get('code_challenge_methods_supported', [])
            ],
            token_endpoint_auth_methods_supported=[
                str(item) for item in payload.get('token_endpoint_auth_methods_supported', [])
            ],
        )


@dataclass(slots=True)
class StoredCredentials:
    """Persisted OAuth client and token state for the local MCP server."""

    client_id: str | None = None
    redirect_uri: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize credentials to a JSON-compatible dictionary."""

        return {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'expires_at': self.expires_at.isoformat() if self.expires_at is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> 'StoredCredentials':
        """Deserialize credentials from persisted JSON data."""

        expires_at_raw = payload.get('expires_at')
        expires_at = None

        if expires_at_raw:
            expires_at = datetime.fromisoformat(str(expires_at_raw))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)

        return cls(
            client_id=str(payload['client_id']) if payload.get('client_id') else None,
            redirect_uri=str(payload['redirect_uri']) if payload.get('redirect_uri') else None,
            access_token=str(payload['access_token']) if payload.get('access_token') else None,
            refresh_token=str(payload['refresh_token']) if payload.get('refresh_token') else None,
            expires_at=expires_at,
        )

    def has_registration(self) -> bool:
        """Return whether a client registration already exists."""

        return bool(self.client_id and self.redirect_uri)

    def access_token_is_valid(self, now: datetime | None = None) -> bool:
        """Return whether the persisted access token is still usable."""

        if not self.access_token or self.expires_at is None:
            return False

        reference_time = now or datetime.now(UTC)
        return self.expires_at > reference_time


@dataclass(slots=True)
class _OAuthCallbackServer(HTTPServer):
    """Small loopback server used to capture the OAuth redirect."""

    callback_path: str
    response_queue: queue.Queue[dict[str, str]]

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[BaseHTTPRequestHandler],
        callback_path: str,
        response_queue: queue.Queue[dict[str, str]],
    ) -> None:
        self.callback_path = callback_path
        self.response_queue = response_queue
        super().__init__(server_address, request_handler)


class _OAuthCallbackRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the authorization response query string."""

    @property
    def _callback_server(self) -> _OAuthCallbackServer:
        return cast(_OAuthCallbackServer, self.server)

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Capture the authorization response and hand it to the waiting flow."""

        parsed_url = urlparse(self.path)
        if parsed_url.path != self._callback_server.callback_path:
            self.send_error(404)
            return

        parameters = {key: values[0] for key, values in parse_qs(parsed_url.query).items()}
        try:
            self._callback_server.response_queue.put_nowait(parameters)
        except queue.Full:
            pass

        body = b'<html><body>Switcher authorization received. You can close this window.</body></html>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # pylint: disable=redefined-builtin
        """Silence request logging, which would corrupt the stdio MCP transport."""

# pylint: disable=too-many-instance-attributes
class SwitcherOAuthClient:
    """OAuth 2.1 PKCE client for authenticating against Switcher API."""

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        *,
        base_url: str | None = None,
        client_name: str = DEFAULT_CLIENT_NAME,
        scope: str = DEFAULT_SCOPE,
        credentials_path: Path | None = None,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or os.getenv('SWITCHER_API_URL', DEFAULT_SWITCHER_API_URL)).rstrip('/')
        self._client_name = client_name
        self._scope = scope
        self._credentials_path = (
            credentials_path
            or (
                Path(os.environ['SWITCHER_MCP_CREDENTIALS_PATH'])
                if os.getenv('SWITCHER_MCP_CREDENTIALS_PATH')
                else None
            )
            or Path.home() / '.switcher-mcp' / 'credentials.json'
        )
        self._metadata: AuthorizationServerMetadata | None = None
        self._credentials_cache: StoredCredentials | None = None
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(timeout=timeout)
        self._authorize_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Expose the configured Switcher API base URL."""

        return self._base_url

    @property
    def credentials_path(self) -> Path:
        """Expose the credentials persistence path."""

        return self._credentials_path

    async def aclose(self) -> None:
        """Close the underlying HTTP client when this instance owns it."""

        if self._owns_http_client:
            await self._http_client.aclose()

    async def discover_metadata(self) -> AuthorizationServerMetadata:
        """Fetch and cache the OAuth authorization server metadata."""

        if self._metadata is not None:
            return self._metadata

        response = await self._http_client.get(f'{self._base_url}{DISCOVERY_PATH}')
        self._raise_for_status(response, 'discover OAuth metadata')
        self._metadata = AuthorizationServerMetadata.from_dict(response.json())
        return self._metadata

    def load_credentials(self) -> StoredCredentials:
        """Load persisted credentials from disk."""

        if self._credentials_cache is not None:
            return self._credentials_cache

        if not self._credentials_path.exists():
            self._credentials_cache = StoredCredentials()
            return self._credentials_cache

        try:
            payload = json.loads(self._credentials_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as error:
            raise SwitcherOAuthError(
                f'Credentials file is not valid JSON: {self._credentials_path}'
            ) from error

        self._credentials_cache = StoredCredentials.from_dict(payload)
        return self._credentials_cache

    def save_credentials(self, credentials: StoredCredentials) -> None:
        """Persist credentials to disk."""

        self._credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self._credentials_path.write_text(
            json.dumps(credentials.to_dict(), indent=2),
            encoding='utf-8',
        )
        self._apply_restrictive_permissions(self._credentials_path)
        self._credentials_cache = credentials

    async def register(self) -> str:
        """Register the local client once and persist its client identifier."""

        credentials = self.load_credentials()

        if credentials.has_registration():
            return str(credentials.client_id)

        metadata = await self.discover_metadata()
        redirect_uri = credentials.redirect_uri or self._build_loopback_redirect_uri()

        response = await self._http_client.post(
            metadata.registration_endpoint,
            json={
                'client_name': self._client_name,
                'redirect_uris': [redirect_uri],
            },
        )
        self._raise_for_status(response, 'register OAuth client')

        registration_payload = response.json()
        updated_credentials = StoredCredentials(
            client_id=str(registration_payload['client_id']),
            redirect_uri=redirect_uri,
            access_token=credentials.access_token,
            refresh_token=credentials.refresh_token,
            expires_at=credentials.expires_at,
        )
        self.save_credentials(updated_credentials)
        return updated_credentials.client_id or ''

    async def build_authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
    ) -> str:
        """Build the browser authorization URL for the interactive flow."""

        metadata = await self.discover_metadata()
        query_string = urlencode(
            {
                'response_type': 'code',
                'client_id': await self.register(),
                'redirect_uri': redirect_uri,
                'scope': self._scope,
                'state': state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256',
            }
        )
        return f'{metadata.authorization_endpoint}?{query_string}'

    async def authorize(self, timeout_seconds: int = DEFAULT_AUTHORIZATION_TIMEOUT_SECONDS) -> str:
        """Run the browser-based authorization code flow and persist the token pair."""

        credentials = self.load_credentials()
        if not credentials.has_registration():
            await self.register()
            credentials = self.load_credentials()

        client_id = credentials.client_id or ''
        redirect_uri = str(credentials.redirect_uri)

        code_verifier, code_challenge = self.generate_pkce_pair()
        state = secrets.token_urlsafe(32)
        authorize_url = await self.build_authorization_url(
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
        )

        callback_parameters = await asyncio.to_thread(
            self._open_browser_and_wait_for_callback,
            redirect_uri,
            authorize_url,
            timeout_seconds,
        )

        updated_credentials = await self.finalize_authorization_callback(
            callback_parameters=callback_parameters,
            expected_state=state,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            client_id=client_id,
        )
        return updated_credentials.access_token or ''

    async def finalize_authorization_callback(
        self,
        *,
        callback_parameters: Mapping[str, str],
        expected_state: str,
        redirect_uri: str,
        code_verifier: str,
        client_id: str | None = None,
    ) -> StoredCredentials:
        """Validate an OAuth callback response and exchange its code for tokens."""

        response_state = callback_parameters.get('state')
        if response_state != expected_state:
            raise SwitcherAuthorizationError('OAuth callback state did not match the original authorization request.')

        callback_error = callback_parameters.get('error')
        if callback_error:
            raise SwitcherAuthorizationError(f'OAuth authorization failed: {callback_error}')

        authorization_code = callback_parameters.get('code')
        if not authorization_code:
            raise SwitcherAuthorizationError('OAuth callback did not include an authorization code.')

        active_client_id = client_id or self.load_credentials().client_id
        if not active_client_id:
            raise SwitcherAuthorizationError('OAuth client registration is missing. Run register() first.')

        token_payload = await self._request_token(
            {
                'grant_type': 'authorization_code',
                'code': authorization_code,
                'redirect_uri': redirect_uri,
                'client_id': active_client_id,
                'code_verifier': code_verifier,
            }
        )
        updated_credentials = self._build_updated_credentials(token_payload)
        self.save_credentials(updated_credentials)
        return updated_credentials

    async def refresh(self) -> StoredCredentials:
        """Refresh the current access token using the persisted refresh token."""

        credentials = self.load_credentials()
        if not credentials.client_id or not credentials.refresh_token:
            raise SwitcherAuthorizationRequiredError('No refresh token is available. Run authorize() to sign in.')

        token_payload = await self._request_token(
            {
                'grant_type': 'refresh_token',
                'refresh_token': credentials.refresh_token,
                'client_id': credentials.client_id,
            }
        )
        updated_credentials = self._build_updated_credentials(token_payload)
        self.save_credentials(updated_credentials)
        return updated_credentials

    async def get_valid_access_token(self) -> str:
        """Return a currently valid access token, refreshing it when needed."""

        credentials = self.load_credentials()
        if credentials.access_token_is_valid():
            return credentials.access_token or ''

        if not credentials.refresh_token:
            raise SwitcherAuthorizationRequiredError(
                'No valid access token is stored. Run authorize() to complete a fresh browser sign-in.'
            )

        try:
            refreshed_credentials = await self.refresh()
        except SwitcherOAuthError as error:
            raise SwitcherAuthorizationRequiredError(
                'Stored refresh token could not be used. Run authorize() to complete a fresh browser sign-in.'
            ) from error

        return refreshed_credentials.access_token or ''

    def invalidate_access_token(self) -> None:
        """Discard the cached access token so the next call is forced to refresh or re-authorize.

        This is used after the Switcher API rejects a token with HTTP 401 even though the
        token's locally-tracked expiry hasn't passed yet (e.g. because permission was revoked
        server-side). Clearing the access token (while keeping the refresh token) lets
        `get_valid_access_token` attempt a refresh, and lets `authorize_if_needed` fall back to
        the interactive browser consent flow if the refresh token is no longer accepted either.
        """

        credentials = self.load_credentials()
        updated_credentials = StoredCredentials(
            client_id=credentials.client_id,
            redirect_uri=credentials.redirect_uri,
            access_token=None,
            refresh_token=credentials.refresh_token,
            expires_at=None,
        )
        self.save_credentials(updated_credentials)

    async def authorize_if_needed(self) -> str:
        """Return a valid access token, running the interactive flow at most once concurrently.

        If a valid or refreshable token is already available, it is returned without
        opening a browser. Otherwise the full browser-based `authorize()` flow runs.
        An `asyncio.Lock` ensures concurrent callers don't each try to open a browser
        and spin up competing local callback servers.
        """

        async with self._authorize_lock:
            # Re-check after acquiring the lock in case another task already
            # completed authorization while we were waiting.
            try:
                return await self.get_valid_access_token()
            except SwitcherAuthorizationRequiredError:
                return await self.authorize()

    @staticmethod
    def generate_code_verifier() -> str:
        """Generate a PKCE code verifier suitable for the S256 challenge method."""

        verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode('ascii').rstrip('=')
        return verifier[:128]

    @staticmethod
    def build_code_challenge(code_verifier: str) -> str:
        """Compute the PKCE S256 code challenge for a verifier."""

        digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
        return base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')

    @classmethod
    def generate_pkce_pair(cls) -> tuple[str, str]:
        """Generate a verifier and its matching S256 challenge."""

        code_verifier = cls.generate_code_verifier()
        return code_verifier, cls.build_code_challenge(code_verifier)

    async def _request_token(self, payload: dict[str, str]) -> dict[str, Any]:
        metadata = await self.discover_metadata()
        response = await self._http_client.post(metadata.token_endpoint, json=payload)
        self._raise_for_status(response, 'exchange OAuth token')
        return response.json()

    def _build_updated_credentials(self, token_payload: Mapping[str, Any]) -> StoredCredentials:
        """Merge token data into the currently persisted registration state."""

        credentials = self.load_credentials()
        expires_in = int(token_payload['expires_in'])
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        return StoredCredentials(
            client_id=credentials.client_id,
            redirect_uri=credentials.redirect_uri,
            access_token=str(token_payload['access_token']),
            refresh_token=str(token_payload['refresh_token']),
            expires_at=expires_at,
        )

    def _open_browser_and_wait_for_callback(
        self,
        redirect_uri: str,
        authorize_url: str,
        timeout_seconds: int,
    ) -> dict[str, str]:
        """Start the loopback listener, open the browser, and wait for the OAuth redirect."""

        parsed_redirect = urlparse(redirect_uri)
        host = parsed_redirect.hostname or '127.0.0.1'
        port = parsed_redirect.port
        callback_path = parsed_redirect.path or CALLBACK_PATH
        response_queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=1)

        if host != '127.0.0.1' or port is None:
            raise SwitcherAuthorizationError(
                'The registered redirect URI must use a 127.0.0.1 loopback callback with an explicit port.'
            )

        try:
            server = _OAuthCallbackServer(
                (host, port),
                _OAuthCallbackRequestHandler,
                callback_path=callback_path,
                response_queue=response_queue,
            )
        except OSError as error:
            raise SwitcherAuthorizationError(
                f'Unable to bind the local OAuth callback server on {redirect_uri}.'
            ) from error

        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={'poll_interval': 0.1},
            daemon=True,
        )
        server_thread.start()

        try:
            webbrowser.open(authorize_url)
            try:
                return response_queue.get(timeout=timeout_seconds)
            except queue.Empty as error:
                raise SwitcherAuthorizationError('Timed out waiting for the OAuth browser callback.') from error
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=1)

    def _build_loopback_redirect_uri(self) -> str:
        """Reserve a loopback redirect URI for native-app authorization."""

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(('127.0.0.1', 0))
            port = int(sock.getsockname()[1])

        return f'http://127.0.0.1:{port}{CALLBACK_PATH}'

    @staticmethod
    def _apply_restrictive_permissions(path: Path) -> None:
        """Best-effort file hardening for persisted credentials."""

        if os.name == 'nt':
            return

        try:
            os.chmod(path, 0o600)
        except OSError:
            return

    @staticmethod
    def _raise_for_status(response: httpx.Response, action: str) -> None:
        """Raise a Switcher-specific exception for HTTP errors."""

        if response.is_success:
            return

        response_body = response.text.strip() or '<empty response body>'
        raise SwitcherOAuthError(
            f'Unable to {action}: HTTP {response.status_code} returned {response_body}'
        )
