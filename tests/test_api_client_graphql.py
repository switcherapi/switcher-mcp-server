"""Tests for the Switcher API client GraphQL support."""

from __future__ import annotations

import asyncio
import json

import pytest

from switcher_mcp_server.api_client import SwitcherApiClient, SwitcherApiError


async def _static_token_provider() -> str:
    return 'access-token'


def test_graphql_posts_query_and_returns_data(httpx_mock) -> None:
    """GraphQL calls should POST query/variables and return the data payload."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    httpx_mock.add_response(
        method='POST', url='http://127.0.0.1:3000/adm-graphql', json={'data': {'configuration': {'config': []}}}
    )

    try:
        data = asyncio.run(client.graphql('query { x }', {'domain': 'd1'}))
        assert data == {'configuration': {'config': []}}
        request = httpx_mock.get_requests()[0]
        assert json.loads(request.content) == {'query': 'query { x }', 'variables': {'domain': 'd1'}}
        assert request.headers['Authorization'] == 'Bearer access-token'
    finally:
        asyncio.run(client.aclose())


def test_graphql_raises_on_errors_payload(httpx_mock) -> None:
    """HTTP 200 responses carrying GraphQL errors should raise SwitcherApiError."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    httpx_mock.add_response(
        method='POST', url='http://127.0.0.1:3000/adm-graphql', json={'errors': [{'message': 'Boom'}]}
    )

    try:
        with pytest.raises(SwitcherApiError, match='Boom'):
            asyncio.run(client.graphql('query { x }'))
    finally:
        asyncio.run(client.aclose())


def _mock_domains(httpx_mock, owned: list, collaborations: list) -> None:
    httpx_mock.add_response(method='GET', url='http://127.0.0.1:3000/domain', json=owned)
    httpx_mock.add_response(method='GET', url='http://127.0.0.1:3000/domain/collaboration', json=collaborations)


def test_resolve_domain_id_matches_exact_name(httpx_mock) -> None:
    """Domain names should resolve to ids across owned and collaborative domains."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    _mock_domains(
        httpx_mock,
        [{'_id': 'd1', 'name': 'Main'}],
        [{'_id': 'd2', 'name': 'Shared'}, {'_id': 'd1', 'name': 'Main'}],
    )

    try:
        assert asyncio.run(client.resolve_domain_id('Shared')) == 'd2'
    finally:
        asyncio.run(client.aclose())


def test_resolve_domain_id_not_found_and_ambiguous(httpx_mock) -> None:
    """Missing and duplicated domain names should raise clear errors."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    _mock_domains(httpx_mock, [{'_id': 'd1', 'name': 'Dup'}], [{'_id': 'd2', 'name': 'Dup'}])
    _mock_domains(httpx_mock, [{'_id': 'd1', 'name': 'Dup'}], [{'_id': 'd2', 'name': 'Dup'}])

    try:
        with pytest.raises(SwitcherApiError, match='ambiguous'):
            asyncio.run(client.resolve_domain_id('Dup'))
        with pytest.raises(SwitcherApiError, match='not found'):
            asyncio.run(client.resolve_domain_id('Missing'))
    finally:
        asyncio.run(client.aclose())


def test_graphql_raises_when_payload_is_not_an_object(httpx_mock) -> None:
    """A non-object JSON response should raise SwitcherApiError."""

    client = SwitcherApiClient(token_provider=_static_token_provider)
    httpx_mock.add_response(method='POST', url='http://127.0.0.1:3000/adm-graphql', json=['unexpected'])

    try:
        with pytest.raises(SwitcherApiError, match='not a JSON object'):
            asyncio.run(client.graphql('query { x }'))
    finally:
        asyncio.run(client.aclose())


def test_resolve_domain_id_requires_domain_name() -> None:
    """An empty domain name should be rejected before any request is made."""

    client = SwitcherApiClient(token_provider=_static_token_provider)

    try:
        with pytest.raises(ValueError, match='domain is required'):
            asyncio.run(client.resolve_domain_id(''))
    finally:
        asyncio.run(client.aclose())
