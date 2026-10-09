"""Tests for Switcher MCP context tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from switcher_mcp_server.tools import context_tools


def test_list_domains_deduplicates_owned_and_collaboration_results(monkeypatch) -> None:
    """Tool output should merge duplicate domain ids across sources."""

    fake_api_client = AsyncMock()
    fake_api_client.list_domains.return_value = [
        {'_id': 'domain-1', 'name': 'Main Domain', 'description': 'Owned'},
    ]
    fake_api_client.list_domain_collaborations.return_value = [
        {'_id': 'domain-1', 'name': 'Main Domain', 'description': 'Owned'},
        {'_id': 'domain-2', 'name': 'Shared Domain', 'description': 'Collaboration'},
    ]

    monkeypatch.setattr(context_tools, '_get_api_client', lambda: fake_api_client)

    domains = asyncio.run(context_tools.list_domains())

    assert domains == [
        {
            'id': 'domain-1',
            'name': 'Main Domain',
            'description': 'Owned',
            'activated': None,
            'sources': ['owned', 'collaboration'],
        },
        {
            'id': 'domain-2',
            'name': 'Shared Domain',
            'description': 'Collaboration',
            'activated': None,
            'sources': ['collaboration'],
        },
    ]


def test_list_domains_can_skip_collaborations(monkeypatch) -> None:
    """Tool should allow returning only directly owned domains."""

    fake_api_client = AsyncMock()
    fake_api_client.list_domains.return_value = [
        {'_id': 'domain-1', 'name': 'Main Domain'},
    ]

    monkeypatch.setattr(context_tools, '_get_api_client', lambda: fake_api_client)

    domains = asyncio.run(context_tools.list_domains(include_collaborations=False))

    assert domains == [
        {
            'id': 'domain-1',
            'name': 'Main Domain',
            'description': None,
            'activated': None,
            'sources': ['owned'],
        }
    ]
    fake_api_client.list_domain_collaborations.assert_not_called()


def test_list_environments_returns_sorted_names(monkeypatch) -> None:
    """Environment tool should return clean sorted names."""

    fake_api_client = AsyncMock()
    fake_api_client.list_environments.return_value = [
        {'_id': 'env-2', 'name': 'staging'},
        {'_id': 'env-1', 'name': 'Default'},
    ]

    monkeypatch.setattr(context_tools, '_get_api_client', lambda: fake_api_client)

    environments = asyncio.run(context_tools.list_environments('domain-1'))

    assert environments == ['Default', 'staging']


def test_tools_are_registered_on_the_shared_mcp_server() -> None:
    """Shared MCP server should expose the context tools."""

    registered_tools = asyncio.run(context_tools.get_mcp_server().list_tools())
    tool_names = {tool.name for tool in registered_tools}

    assert {'list_domains', 'list_environments'}.issubset(tool_names)


def test_shared_api_client_is_built_once_from_environment(monkeypatch, tmp_path) -> None:
    """Tools should lazily build a single API client wired to the configured Switcher URL."""

    monkeypatch.setattr(context_tools, '_API_CLIENT', None)
    monkeypatch.setenv('SWITCHER_API_URL', 'http://switcher.test')
    monkeypatch.setenv('SWITCHER_MCP_CREDENTIALS_PATH', str(tmp_path / 'credentials.json'))

    first = context_tools.get_api_client()
    try:
        assert first is context_tools.get_api_client()
        assert first._base_url == 'http://switcher.test'  # pylint: disable=protected-access
    finally:
        asyncio.run(first.aclose())


def test_list_domains_skips_entries_without_id(monkeypatch) -> None:
    """Malformed domain payloads without an _id are ignored from both sources."""

    fake_api_client = AsyncMock()
    fake_api_client.list_domains.return_value = [{'name': 'No Id'}, {'_id': 'd1', 'name': 'B'}]
    fake_api_client.list_domain_collaborations.return_value = [{'name': 'No Id'}, {'_id': 'd0', 'name': 'a'}]
    monkeypatch.setattr(context_tools, '_get_api_client', lambda: fake_api_client)

    domains = asyncio.run(context_tools.list_domains())

    assert [domain['id'] for domain in domains] == ['d0', 'd1']


def test_list_environments_validates_input_and_skips_unnamed(monkeypatch) -> None:
    """Empty domain ids are rejected and environments without a name are dropped."""

    with pytest.raises(ValueError, match='domain_id is required'):
        asyncio.run(context_tools.list_environments(''))

    fake_api_client = AsyncMock()
    fake_api_client.list_environments.return_value = [{'_id': 'e1'}, {'name': 'prod'}]
    monkeypatch.setattr(context_tools, '_get_api_client', lambda: fake_api_client)

    assert asyncio.run(context_tools.list_environments('d1')) == ['prod']
