"""MCP tools for reading Switcher feature flag settings."""

from __future__ import annotations

from typing import Any

from switcher_mcp_server.tools.context_tools import get_api_client, mcp


def _shape_response(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw Switcher config payload into a stable tool response."""

    return {
        'key': config.get('key'),
        'description': config.get('description'),
        'enabled': config.get('enabled'),
        'activated': config.get('activated'),
        'group': config.get('group'),
        'domain': config.get('domain'),
        'relay': config.get('relay'),
        'disable_metrics': config.get('disable_metrics'),
        'strategies': config.get('configStrategy'),
    }


@mcp.tool(
    description=(
        'Get a Switcher feature flag settings by key, domain name, and optional environment. '
        'Returns the enabled state, description, strategies, relay config, and metrics flag.'
    )
)
async def get_feature_flag(key: str, domain: str, environment: str | None = None) -> dict[str, Any]:
    """Return the settings for a Switcher feature flag identified by key and domain."""

    if not key:
        raise ValueError('key is required.')

    if not domain:
        raise ValueError('domain is required.')

    api_client = get_api_client()
    config = await api_client.get_config_by_key(key, domain, environment)
    return _shape_response(config)


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
        'key, description, activated.'
    )
