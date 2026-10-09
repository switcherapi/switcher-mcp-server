"""Tests for the get_feature_flag MCP tool."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from switcher_mcp_server.tools import flag_tools


def test_get_feature_flag_shapes_config_response(monkeypatch) -> None:
    """Tool output should normalize the raw config payload into a stable shape."""

    fake_api_client = AsyncMock()
    fake_api_client.get_config_by_key.return_value = {
        'key': 'MY_FLAG',
        'description': 'A sample flag',
        'enabled': True,
        'activated': {'default': True},
        'group': 'Group A',
        'domain': 'domain-1',
        'relay': None,
        'disable_metrics': {'default': False},
        'configStrategy': [],
    }

    monkeypatch.setattr(flag_tools, 'get_api_client', lambda: fake_api_client)

    result = asyncio.run(flag_tools.get_feature_flag('MY_FLAG', 'Main Domain'))

    assert result == {
        'key': 'MY_FLAG',
        'description': 'A sample flag',
        'enabled': True,
        'activated': {'default': True},
        'group': 'Group A',
        'domain': 'domain-1',
        'relay': None,
        'disable_metrics': {'default': False},
        'strategies': [],
    }
    fake_api_client.get_config_by_key.assert_awaited_once_with('MY_FLAG', 'Main Domain', None)


def test_get_feature_flag_passes_environment_through(monkeypatch) -> None:
    """Tool should forward the optional environment parameter to the API client."""

    fake_api_client = AsyncMock()
    fake_api_client.get_config_by_key.return_value = {'key': 'MY_FLAG', 'enabled': False}

    monkeypatch.setattr(flag_tools, 'get_api_client', lambda: fake_api_client)

    asyncio.run(flag_tools.get_feature_flag('MY_FLAG', 'Main Domain', 'production'))

    fake_api_client.get_config_by_key.assert_awaited_once_with('MY_FLAG', 'Main Domain', 'production')


def test_get_feature_flag_requires_key() -> None:
    """Tool should reject empty keys before calling the API client."""

    with pytest.raises(ValueError, match='key is required'):
        asyncio.run(flag_tools.get_feature_flag('', 'Main Domain'))


def test_get_feature_flag_requires_domain() -> None:
    """Tool should reject empty domains before calling the API client."""

    with pytest.raises(ValueError, match='domain is required'):
        asyncio.run(flag_tools.get_feature_flag('MY_FLAG', ''))


def test_get_feature_flag_is_registered_on_the_shared_mcp_server() -> None:
    """Shared MCP server should expose the get_feature_flag tool."""

    registered_tools = asyncio.run(flag_tools.mcp.list_tools())
    tool_names = sorted(tool.name for tool in registered_tools)

    assert 'get_feature_flag' in tool_names


def _prompt_text(result) -> str:
    """Extract the plain text payload from a GetPromptResult's single message."""

    return result.messages[0].content.text


def test_switcher_get_feature_prompt_is_registered_on_the_shared_mcp_server() -> None:
    """Shared MCP server should expose the switcher_get_feature prompt."""

    registered_prompts = asyncio.run(flag_tools.mcp.list_prompts())
    prompt_names = {prompt.name for prompt in registered_prompts}

    assert 'switcher_get_feature' in prompt_names


def test_switcher_get_feature_prompt_without_environment() -> None:
    """Prompt should mention the default environment scope when none is given."""

    result = asyncio.run(flag_tools.mcp.get_prompt('switcher_get_feature', {'key': 'MY_FLAG', 'domain': 'Main Domain'}))
    text = _prompt_text(result)

    assert 'get_feature_flag' in text
    assert "key='MY_FLAG'" in text
    assert "domain='Main Domain'" in text
    assert 'default environment' in text


def test_switcher_get_feature_prompt_with_environment() -> None:
    """Prompt should mention the explicit environment when provided."""

    result = asyncio.run(
        flag_tools.mcp.get_prompt(
            'switcher_get_feature',
            {'key': 'MY_FLAG', 'domain': 'Main Domain', 'environment': 'production'},
        )
    )
    text = _prompt_text(result)

    assert "environment='production'" in text
    assert "environment 'production'" in text
