"""MCP tools for Switcher environment discovery."""

from __future__ import annotations

from switcher_mcp_server.tools.shared import _get_api_client, mcp


@mcp.tool(description='List environment names for a Switcher domain id returned by list_domains.')
async def list_environments(domain_id: str) -> list[str]:
    """Return the environment names available for a specific Switcher domain."""

    if not domain_id:
        raise ValueError('domain_id is required.')

    api_client = _get_api_client()
    environments = await api_client.list_environments(domain_id)
    return sorted(
        [
            str(environment['name'])
            for environment in environments
            if environment.get('name') is not None
        ],
        key=str.lower,
    )


@mcp.prompt(description="List a Switcher domain's environments.")
def switcher_environments(domain_id: str) -> str:
    """Build a guided message that drives the list_environments tool."""

    return (
        f"Call the list_environments tool with domain_id='{domain_id}'. "
        "List the returned environment names"
    )
