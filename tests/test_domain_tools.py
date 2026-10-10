"""Tests for Switcher MCP domain tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from switcher_mcp_server.tools import domain_tools


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

    monkeypatch.setattr(domain_tools, '_get_api_client', lambda: fake_api_client)

    domains = asyncio.run(domain_tools.list_domains())

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

    monkeypatch.setattr(domain_tools, '_get_api_client', lambda: fake_api_client)

    domains = asyncio.run(domain_tools.list_domains(include_collaborations=False))

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


def test_list_domains_skips_entries_without_id(monkeypatch) -> None:
    """Malformed domain payloads without an _id are ignored from both sources."""

    fake_api_client = AsyncMock()
    fake_api_client.list_domains.return_value = [{'name': 'No Id'}, {'_id': 'd1', 'name': 'B'}]
    fake_api_client.list_domain_collaborations.return_value = [{'name': 'No Id'}, {'_id': 'd0', 'name': 'a'}]
    monkeypatch.setattr(domain_tools, '_get_api_client', lambda: fake_api_client)

    domains = asyncio.run(domain_tools.list_domains())

    assert [domain['id'] for domain in domains] == ['d0', 'd1']


def test_tools_are_registered_on_the_shared_mcp_server() -> None:
    """Shared MCP server should expose the list_domains tool."""

    registered_tools = asyncio.run(domain_tools.mcp.list_tools())
    tool_names = {tool.name for tool in registered_tools}

    assert 'list_domains' in tool_names


def test_prompts_are_registered_on_the_shared_mcp_server() -> None:
    """Shared MCP server should expose the switcher_domains prompt."""

    registered_prompts = asyncio.run(domain_tools.mcp.list_prompts())
    prompt_names = {prompt.name for prompt in registered_prompts}

    assert 'switcher_domains' in prompt_names


def _prompt_text(result) -> str:
    """Extract the plain text payload from a GetPromptResult's single message."""

    return result.messages[0].content.text


def test_switcher_domains_prompt_mentions_tool_and_arguments() -> None:
    """switcher_domains prompt should instruct the model to call list_domains with the given flag."""

    result = asyncio.run(domain_tools.mcp.get_prompt('switcher_domains', {'include_collaborations': False}))
    text = _prompt_text(result)

    assert 'list_domains' in text
    assert 'include_collaborations=False' in text
    assert 'no collaborations' in text
