"""Headless OAuth bootstrap for the manual e2e validation flow.

Emulates the interactive OAuth 2.1 + PKCE authorization code flow that
switcher-mcp-server normally runs via a real browser against
switcher-management's consent screen, but without a browser: it authenticates
with the configured account's session JWT and hits switcher-api's
``/oauth/authorize`` with ``consent=true`` directly (the same technique used
by ``scripts/e2e_validate.py``). This exercises the exact same
``/oauth/register`` -> ``/oauth/authorize`` -> ``/oauth/token`` endpoints as
production; only the human consent click is skipped so this can run
unattended.

The resulting token pair is persisted to an isolated credentials file (never
the real ``~/.switcher-mcp/credentials.json``) so the switcher_mcp_server
subprocess spawned by ``mcp_runner.py`` picks it up already authorized.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from config import E2EConfig

_BOOTSTRAP_REDIRECT_URI = 'http://127.0.0.1:54999/callback'
_SCOPE = 'config:read'


class OAuthBootstrapError(RuntimeError):
    """Raised when the headless OAuth bootstrap flow fails."""


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier/code_challenge pair (S256)."""

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


def bootstrap_credentials(config: E2EConfig) -> Path:
    """Run the headless OAuth flow and persist credentials for the configured account.

    Returns the path to the written credentials file.
    """

    with httpx.Client(base_url=config.switcher_api_url, timeout=10.0) as client:
        login_response = client.post(
            '/admin/login',
            json={'email': config.account_email, 'password': config.account_password},
        )
        if login_response.is_error:
            raise OAuthBootstrapError(
                f'Failed to log in as {config.account_email}: '
                f'HTTP {login_response.status_code} {login_response.text}'
            )
        session_jwt = login_response.json()['jwt']['token']
        auth_header = {'Authorization': f'Bearer {session_jwt}'}

        register_response = client.post(
            '/oauth/register',
            json={
                'client_name': 'switcher-mcp-server e2e',
                'redirect_uris': [_BOOTSTRAP_REDIRECT_URI],
            },
        )
        if register_response.is_error:
            raise OAuthBootstrapError(
                f'OAuth client registration failed: '
                f'HTTP {register_response.status_code} {register_response.text}'
            )
        registration = register_response.json()
        client_id = registration['client_id']
        redirect_uri = registration['redirect_uris'][0]

        code_verifier, code_challenge = _generate_pkce_pair()
        state = secrets.token_hex(8)

        authorize_response = client.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'scope': _SCOPE,
                'state': state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256',
                'consent': 'true',
            },
            headers=auth_header,
            follow_redirects=False,
        )
        if authorize_response.status_code != 302:
            raise OAuthBootstrapError(
                f'Expected an authorize redirect, got HTTP {authorize_response.status_code}: '
                f'{authorize_response.text}'
            )
        redirect_target = authorize_response.headers['location']
        query = parse_qs(urlparse(redirect_target).query)
        if query.get('state') != [state]:
            raise OAuthBootstrapError(f'OAuth state mismatch: {query}')
        code = query['code'][0]

        token_response = client.post(
            '/oauth/token',
            json={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
                'client_id': client_id,
                'code_verifier': code_verifier,
            },
        )
        if token_response.is_error:
            raise OAuthBootstrapError(
                f'Token exchange failed: HTTP {token_response.status_code} {token_response.text}'
            )
        token = token_response.json()

    expires_at = datetime.now(UTC) + timedelta(seconds=float(token['expires_in']))
    credentials_payload = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'access_token': token['access_token'],
        'refresh_token': token['refresh_token'],
        'expires_at': expires_at.isoformat(),
    }

    config.credentials_path.parent.mkdir(parents=True, exist_ok=True)
    config.credentials_path.write_text(json.dumps(credentials_payload, indent=2), encoding='utf-8')

    return config.credentials_path
