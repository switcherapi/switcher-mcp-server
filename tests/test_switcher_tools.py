"""Tests for the get_feature_flag MCP tool."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from switcher_mcp_server.api_client import SwitcherApiError
from switcher_mcp_server.tools import switcher_tools


def _fake_client(configuration):
    client = AsyncMock()
    client.resolve_domain_id.return_value = 'domain-1'
    client.graphql.return_value = {'configuration': configuration}
    return client


def _configuration(domain_active=True, group_active=True, config_active=True):
    return {
        'domain': {'id': 'domain-1', 'name': 'Main Domain', 'version': 1, 'activated': domain_active},
        'group': [{'_id': 'g1', 'name': 'Group A', 'activated': group_active}],
        'config': [
            {'_id': 'c1', 'key': 'MY_FLAG', 'description': 'A flag', 'activated': config_active,
             'components': ['app'], 'relay': None},
        ],
        'strategies': [{'_id': 's1', 'strategy': 'VALUE_VALIDATION', 'description': 'Users', 'operation': 'EXIST', 'values': ['a'], 'activated': True}],
    }


def test_get_feature_flag_shapes_graphql_response(monkeypatch) -> None:
    """Tool output should be the GraphQL-native shape with a computed hierarchy_activated."""

    fake_api_client = _fake_client(_configuration())
    monkeypatch.setattr(switcher_tools, 'get_api_client', lambda: fake_api_client)

    result = asyncio.run(switcher_tools.get_feature_flag('MY_FLAG', 'Main Domain'))

    assert result['domain']['id'] == 'domain-1'
    assert result['group'] == {'id': 'g1', 'name': 'Group A', 'description': None, 'activated': True}
    assert result['config']['key'] == 'MY_FLAG'
    assert result['config']['components'] == ['app']
    assert result['strategies'][0]['operation'] == 'EXIST'
    assert result['strategies'][0]['strategy'] == 'VALUE_VALIDATION'
    assert result['has_active_strategies'] is True
    assert result['hierarchy_activated'] is True
    fake_api_client.resolve_domain_id.assert_awaited_once_with('Main Domain')
    query, variables = fake_api_client.graphql.await_args.args
    strategy_block = query.split('strategies {')[1]
    assert 'strategy' in strategy_block
    assert '_id' in strategy_block
    assert variables == {'domain': 'domain-1', 'key': 'MY_FLAG', 'environment': 'default'}


def test_get_feature_flag_passes_environment_through(monkeypatch) -> None:
    """Tool should forward the optional environment parameter to the GraphQL query."""

    fake_api_client = _fake_client(_configuration())
    monkeypatch.setattr(switcher_tools, 'get_api_client', lambda: fake_api_client)

    asyncio.run(switcher_tools.get_feature_flag('MY_FLAG', 'Main Domain', 'production'))

    assert fake_api_client.graphql.await_args.args[1]['environment'] == 'production'


@pytest.mark.parametrize('flags', [(False, True, True), (True, False, True), (True, True, False)])
def test_get_feature_flag_hierarchy_activated_requires_every_level(monkeypatch, flags) -> None:
    """A deactivated domain, group, or config disables the flag."""

    fake_api_client = _fake_client(_configuration(*flags))
    monkeypatch.setattr(switcher_tools, 'get_api_client', lambda: fake_api_client)

    result = asyncio.run(switcher_tools.get_feature_flag('MY_FLAG', 'Main Domain'))

    assert result['hierarchy_activated'] is False


@pytest.mark.parametrize('configuration', [{}, {'domain': {'id': 'domain-1'}, 'group': [], 'config': []}])
def test_get_feature_flag_not_found(monkeypatch, configuration) -> None:
    """Missing group/config (not found or denied) should raise a clear error."""

    fake_api_client = _fake_client(configuration)
    monkeypatch.setattr(switcher_tools, 'get_api_client', lambda: fake_api_client)

    with pytest.raises(SwitcherApiError, match='not found or is not accessible'):
        asyncio.run(switcher_tools.get_feature_flag('MY_FLAG', 'Main Domain'))


def test_get_feature_flag_propagates_domain_resolution_error(monkeypatch) -> None:
    """Domain resolution failures should surface without running the query."""

    fake_api_client = AsyncMock()
    fake_api_client.resolve_domain_id.side_effect = SwitcherApiError('Domain not found', status_code=404)
    monkeypatch.setattr(switcher_tools, 'get_api_client', lambda: fake_api_client)

    with pytest.raises(SwitcherApiError, match='Domain not found'):
        asyncio.run(switcher_tools.get_feature_flag('MY_FLAG', 'Nope'))

    fake_api_client.graphql.assert_not_awaited()

def test_get_feature_flag_requires_key() -> None:
    """Tool should reject empty keys before calling the API client."""

    with pytest.raises(ValueError, match='key is required'):
        asyncio.run(switcher_tools.get_feature_flag('', 'Main Domain'))


def test_get_feature_flag_requires_domain() -> None:
    """Tool should reject empty domains before calling the API client."""

    with pytest.raises(ValueError, match='domain is required'):
        asyncio.run(switcher_tools.get_feature_flag('MY_FLAG', ''))


def test_get_feature_flag_is_registered_on_the_shared_mcp_server() -> None:
    """Shared MCP server should expose the get_feature_flag tool."""

    registered_tools = asyncio.run(switcher_tools.mcp.list_tools())
    tool_names = sorted(tool.name for tool in registered_tools)

    assert 'get_feature_flag' in tool_names


def _prompt_text(result) -> str:
    """Extract the plain text payload from a GetPromptResult's single message."""

    return result.messages[0].content.text


def test_switcher_get_feature_prompt_is_registered_on_the_shared_mcp_server() -> None:
    """Shared MCP server should expose the switcher_get_feature prompt."""

    registered_prompts = asyncio.run(switcher_tools.mcp.list_prompts())
    prompt_names = {prompt.name for prompt in registered_prompts}

    assert 'switcher_get_feature' in prompt_names


def test_switcher_get_feature_prompt_without_environment() -> None:
    """Prompt should mention the default environment scope when none is given."""

    result = asyncio.run(
        switcher_tools.mcp.get_prompt('switcher_get_feature', {'key': 'MY_FLAG', 'domain': 'Main Domain'})
    )
    text = _prompt_text(result)

    assert 'get_feature_flag' in text
    assert "key='MY_FLAG'" in text
    assert "domain='Main Domain'" in text
    assert 'default environment' in text


def test_switcher_get_feature_prompt_with_environment() -> None:
    """Prompt should mention the explicit environment when provided."""

    result = asyncio.run(
        switcher_tools.mcp.get_prompt(
            'switcher_get_feature',
            {'key': 'MY_FLAG', 'domain': 'Main Domain', 'environment': 'production'},
        )
    )
    text = _prompt_text(result)

    assert "environment='production'" in text
    assert "environment 'production'" in text
