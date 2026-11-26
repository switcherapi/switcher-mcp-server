"""MCP tools for reading Switcher feature flag settings."""

from __future__ import annotations

from typing import Any

from switcher_mcp_server.api_client import SwitcherApiError
from switcher_mcp_server.graphql_queries import CONFIGURATION_BY_GROUP_QUERY, CONFIGURATION_BY_KEY_QUERY
from switcher_mcp_server.tools.shared import get_api_client, mcp

DEFAULT_ENVIRONMENT = 'default'


def _first(value: Any) -> dict[str, Any] | None:
    """Return the first item of a GraphQL list field (or the value itself when it is an object)."""

    if isinstance(value, list):
        return value[0] if value else None

    return value or None


def _shape_domain(domain: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': domain.get('id'),
        'name': domain.get('name'),
        'description': domain.get('description'),
        'version': domain.get('version'),
        'activated': domain.get('activated'),
    }


def _shape_group(group: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': group.get('_id'),
        'name': group.get('name'),
        'description': group.get('description'),
        'activated': group.get('activated'),
    }


def _shape_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': config.get('_id'),
        'key': config.get('key'),
        'description': config.get('description'),
        'activated': config.get('activated'),
        'components': config.get('components'),
        'relay': config.get('relay'),
    }


def _shape_group_response(configuration: dict[str, Any], group_name: str) -> dict[str, Any]:
    """Normalize a group GraphQL payload into the group-flags tool response."""

    domain = _first(configuration.get('domain'))
    group = _first(configuration.get('group'))

    if not domain or not group:
        raise SwitcherApiError(f"Group '{group_name}' was not found or is not accessible.", status_code=404)

    configs = configuration.get('config') or []

    return {
        'domain': _shape_domain(domain),
        'group': _shape_group(group),
        'configs': [
            {**_shape_config(item), 'hierarchy_activated': all(
                level.get('activated') is True for level in (domain, group, item))}
            for item in configs
        ],
    }


def _shape_response(configuration: dict[str, Any], key: str) -> dict[str, Any]:
    """Normalize a GraphQL configuration payload into a stable tool response."""

    domain = _first(configuration.get('domain'))
    group = _first(configuration.get('group'))
    configs = configuration.get('config') or []
    config = next((item for item in configs if item.get('key') == key), None) or _first(configs)

    if not domain or not group or not config:
        raise SwitcherApiError(f"Feature flag '{key}' was not found or is not accessible.", status_code=404)

    strategies = configuration.get('strategies') or []

    return {
        'domain': _shape_domain(domain),
        'group': _shape_group(group),
        'config': _shape_config(config),
        'strategies': strategies,
        'hierarchy_activated': all(item.get('activated') is True for item in (domain, group, config)),
        'has_active_strategies': any(item.get('activated') is True for item in strategies),
    }


@mcp.tool(
    description=(
        'Get a Switcher feature flag settings by key, domain name, and optional environment '
        "(defaults to 'default'). Returns the domain, group, config (description, components, relay), "
        'strategies, hierarchy_activated (true only when domain, group, and config are all activated), and '
        'has_active_strategies. Strategies are NOT evaluated: the final result for a given input may still be '
        'denied by an active strategy.'
    )
)
async def get_feature_flag(key: str, domain: str, environment: str | None = None) -> dict[str, Any]:
    """Return the settings for a Switcher feature flag identified by key and domain."""

    if not key:
        raise ValueError('key is required.')

    if not domain:
        raise ValueError('domain is required.')

    api_client = get_api_client()
    domain_id = await api_client.resolve_domain_id(domain)
    data = await api_client.graphql(
        CONFIGURATION_BY_KEY_QUERY,
        {'domain': domain_id, 'key': key, 'environment': environment or DEFAULT_ENVIRONMENT},
    )
    return _shape_response(data.get('configuration') or {}, key)


@mcp.tool(
    description=(
        'List all feature flags (configs) of a Switcher group by group name, domain name, and optional '
        "environment (defaults to 'default'). Returns the domain, the group, and its configs "
        '(description, components, relay), each with hierarchy_activated (true only when domain, group, and '
        'config are all activated). Strategies are NOT included or evaluated.'
    )
)
async def get_group_flags(group: str, domain: str, environment: str | None = None) -> dict[str, Any]:
    """Return the group settings and all feature flags under it."""

    if not group:
        raise ValueError('group is required.')

    if not domain:
        raise ValueError('domain is required.')

    api_client = get_api_client()
    domain_id = await api_client.resolve_domain_id(domain)
    data = await api_client.graphql(
        CONFIGURATION_BY_GROUP_QUERY,
        {'domain': domain_id, 'group': group, 'environment': environment or DEFAULT_ENVIRONMENT},
    )
    return _shape_group_response(data.get('configuration') or {}, group)


@mcp.prompt(description="List all feature flags of a Switcher group.")
def switcher_get_group_flags(group: str, domain: str, environment: str | None = None) -> str:
    """Build a guided message that drives the get_group_flags tool."""

    call_args = f"group='{group}', domain='{domain}'"
    scope = f"environment '{environment}'" if environment else 'its default environment'
    if environment:
        call_args += f", environment='{environment}'"

    return (
        f'Call the get_group_flags tool with {call_args} to inspect {scope}. '
        'Summarize the group and list its feature flags in a table with columns '
        'key, description, activated, and hierarchy_activated.'
    )


@mcp.prompt(description="Fetch a Switcher feature flag's settings.")
def switcher_get_feature(key: str, domain: str, environment: str | None = None) -> str:
    """Build a guided message that drives the get_feature_flag tool."""

    call_args = f"key='{key}', domain='{domain}'"
    scope = f"environment '{environment}'" if environment else 'its default environment'
    if environment:
        call_args += f", environment='{environment}'"

    return (
        f'Call the get_feature_flag tool with {call_args} to inspect {scope}. '
        'Summarize the returned feature flag settings in a table with columns '
        'domain, group, key, description, activated, and mention hierarchy_activated, '
        'noting that strategies are not evaluated.'
    )
