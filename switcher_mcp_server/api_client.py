"""Async API client for Switcher MCP tools."""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, cast

import httpx

from switcher_mcp_server.oauth_client import (
    DEFAULT_SWITCHER_API_URL,
    SwitcherAuthorizationError,
    SwitcherAuthorizationRequiredError,
    SwitcherOAuthClient,
)


class SwitcherApiError(RuntimeError):
    """Raised when a Switcher API request fails."""

    def __init__(self, message: str, *, status_code: int | None = None, response_body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class SwitcherApiClient:
    """Authenticated async wrapper around the Switcher API context endpoints."""

    def __init__(
        self,
        *,
        token_provider: Callable[[], Awaitable[str]] | None = None,
        oauth_client: SwitcherOAuthClient | None = None,
        base_url: str | None = None,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        owns_oauth_client = token_provider is None and oauth_client is None
        if owns_oauth_client:
            oauth_client = SwitcherOAuthClient(base_url=base_url)

        self._oauth_client = oauth_client
        self._owns_oauth_client = owns_oauth_client
        if token_provider is None:
            token_provider = cast(SwitcherOAuthClient, oauth_client).get_valid_access_token

        self._token_provider = token_provider
        self._base_url = (base_url or os.getenv('SWITCHER_API_URL', DEFAULT_SWITCHER_API_URL)).rstrip('/')
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def aclose(self) -> None:
        """Close the owned HTTP resources."""

        if self._owns_http_client:
            await self._http_client.aclose()

        if self._owns_oauth_client and self._oauth_client is not None:
            await self._oauth_client.aclose()

    async def list_domains(self) -> list[dict[str, Any]]:
        """List domains directly owned by the authenticated user."""

        return await self._request_json('GET', '/domain')

    async def list_domain_collaborations(self) -> list[dict[str, Any]]:
        """List domains accessible through team collaboration."""

        return await self._request_json('GET', '/domain/collaboration')

    async def list_environments(self, domain_id: str) -> list[dict[str, Any]]:
        """List environments for the given Switcher domain identifier."""

        return await self._request_json('GET', '/environment', params={'domain': domain_id})

    async def get_config_by_key(
        self,
        key: str,
        domain_name: str,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a Switcher configuration document by key and domain context."""

        params: dict[str, str] = {'domain': domain_name}
        if environment:
            params['environment'] = environment

        return await self._request_json('GET', f'/config/key/{key}', params=params)

    async def _get_token_with_recovery(self) -> str:
        """Fetch a token, transparently running the browser authorization flow if needed."""

        try:
            return await self._token_provider()
        except SwitcherAuthorizationRequiredError:
            if self._oauth_client is None:
                raise  # no oauth client to recover with (e.g. tests using a bare token_provider)

            try:
                return await self._oauth_client.authorize_if_needed()
            except SwitcherAuthorizationError as error:
                raise SwitcherApiError(
                    f'Switcher authorization was not completed: {error}. '
                    'Retry the tool call to reopen the consent screen.'
                ) from error

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        access_token = await self._get_token_with_recovery()
        response = await self._http_client.request(
            method,
            path,
            params=params,
            headers={'Authorization': f'Bearer {access_token}'},
        )

        if response.status_code == 401 and self._oauth_client is not None:
            # The cached access token looked valid locally (not yet expired) but the API
            # rejected it, which typically means consent was revoked server-side. Invalidate
            # the cached token so the next attempt is forced to refresh or re-run the
            # interactive consent flow, then retry the request once.
            self._oauth_client.invalidate_access_token()
            access_token = await self._get_token_with_recovery()
            response = await self._http_client.request(
                method,
                path,
                params=params,
                headers={'Authorization': f'Bearer {access_token}'},
            )

        if response.is_error:
            response_body = response.text.strip() or '<empty response body>'
            message = (
                f'Switcher API request failed for {method} {path}: '
                f'HTTP {response.status_code} returned {response_body}'
            )
            raise SwitcherApiError(
                message,
                status_code=response.status_code,
                response_body=response_body,
            )

        try:
            return response.json()
        except ValueError as error:
            raise SwitcherApiError(
                f'Switcher API response for {method} {path} was not valid JSON.',
                status_code=response.status_code,
                response_body=response.text,
            ) from error
