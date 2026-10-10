"""Tests for Switcher MCP environment tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from switcher_mcp_server.tools import environment_tools


def test_list_environments_returns_sorted_names(monkeypatch) -> None:
    """Environment tool should return clean sorted names."""

    fake_api_client = AsyncMock()
    fake_api_client.list_environments.return_value = [
        {'_id': 'env-2', 'name': 'staging'},
        {'_id': 'env-1', 'name': 'Default'},
    ]

    monkeypatch.setattr(environment_tools, '_get_api_client', lambda: fake_api_client)

    environments = asyncio.run(environment_tools.list_environments('domain-1'))

    assert environments == ['Default', 'staging']


def test_list_environments_validates_input_and_skips_unnamed(monkeypatch) -> None:
    """Empty domain ids are rejected and environments without a name are dropped."""

    with pytest.raises(ValueError, match='domain_id is required'):
        asyncio.run(environment_tools.list_environments(''))

    fake_api_client = AsyncMock()
    fake_api_client.list_environments.return_value = [{'_id': 'e1'}, {'name': 'prod'}]
    monkeypatch.setattr(environment_tools, '_get_api_client', lambda: fake_api_client)

    assert asyncio.run(environment_tools.list_environments('d1')) == ['prod']


def test_tools_are_registered_on_the_shared_mcp_server() -> None:
    """Shared MCP server should expose the list_environments tool."""

    registered_tools = asyncio.run(environment_tools.mcp.list_tools())
    tool_names = {tool.name for tool in registered_tools}

    assert 'list_environments' in tool_names


def test_prompts_are_registered_on_the_shared_mcp_server() -> None:
    """Shared MCP server should expose the switcher_environments prompt."""

    registered_prompts = asyncio.run(environment_tools.mcp.list_prompts())
    prompt_names = {prompt.name for prompt in registered_prompts}

    assert 'switcher_environments' in prompt_names


def _prompt_text(result) -> str:
    """Extract the plain text payload from a GetPromptResult's single message."""

    return result.messages[0].content.text


def test_switcher_environments_prompt_mentions_tool_and_domain() -> None:
    """switcher_environments prompt should instruct the model to call list_environments with the domain id."""

    result = asyncio.run(environment_tools.mcp.get_prompt('switcher_environments', {'domain_id': 'domain-1'}))
    text = _prompt_text(result)

    assert 'list_environments' in text
    assert 'domain-1' in text
