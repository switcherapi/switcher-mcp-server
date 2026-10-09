"""MCP tools for Switcher domain and environment context discovery."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from switcher_mcp_server import __version__
from switcher_mcp_server.api_client import SwitcherApiClient
from switcher_mcp_server.oauth_client import SwitcherOAuthClient

mcp = MCPServer(
    name='switcher-mcp-server',
    title='Switcher MCP Server',
    description='Switcher MCP context tools.',
    version=__version__,
)

_API_CLIENT: SwitcherApiClient | None = None


def get_mcp_server() -> MCPServer[None]:
    """Return the shared MCP server instance for tool registration."""

    return mcp


def get_api_client() -> SwitcherApiClient:
    """Resolve the shared API client used by all registered tool handlers."""

    return _get_api_client()


def _get_api_client() -> SwitcherApiClient:
    """Resolve the API client used by tool handlers."""

    global _API_CLIENT  # pylint: disable=global-statement
    if _API_CLIENT is not None:
        return _API_CLIENT

    oauth_client = SwitcherOAuthClient()
    _API_CLIENT = SwitcherApiClient(
        oauth_client=oauth_client,
        base_url=oauth_client.base_url,
    )
    return _API_CLIENT


def _normalize_domain(domain: dict[str, Any], source: str) -> dict[str, Any]:
    """Normalize a raw Switcher domain payload into a stable tool response."""

    return {
        'id': domain.get('_id'),
        'name': domain.get('name'),
        'description': domain.get('description'),
        'activated': domain.get('activated'),
        'sources': [source],
    }


def _merge_domain(existing: dict[str, Any], source: str) -> None:
    """Merge source metadata into an existing normalized domain entry."""

    existing.setdefault('sources', []).append(source)


@mcp.tool(description='List the authenticated user domains, optionally including team collaborations.')
async def list_domains(include_collaborations: bool = True) -> list[dict[str, Any]]:
    """Return normalized owned and collaborative domains accessible to the user."""

    api_client = _get_api_client()
    normalized_domains: dict[str, dict[str, Any]] = {}

    for domain in await api_client.list_domains():
        domain_identifier = domain.get('_id')
        if domain_identifier is None:
            continue

        domain_id = str(domain_identifier)
        normalized_domains[domain_id] = _normalize_domain(domain, 'owned')

    if include_collaborations:
        for domain in await api_client.list_domain_collaborations():
            domain_identifier = domain.get('_id')
            if domain_identifier is None:
                continue

            domain_id = str(domain_identifier)
            if domain_id in normalized_domains:
                _merge_domain(normalized_domains[domain_id], 'collaboration')
                continue

            normalized_domains[domain_id] = _normalize_domain(domain, 'collaboration')

    return sorted(normalized_domains.values(), key=lambda item: str(item.get('name', '')).lower())


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


@mcp.prompt(description='Discover and summarize the Switcher domains accessible to the authenticated user.')
def switcher_domains(include_collaborations: bool = True) -> str:
    """Build a guided message that drives the list_domains tool and summarizes the result."""

    collaboration_note = (
        'including team collaborations' if include_collaborations else 'owned domains only, no collaborations'
    )
    return (
        f'Call the list_domains tool with include_collaborations={include_collaborations} '
        f'({collaboration_note}). Summarize the returned domains in a table with columns '
        'name, description, and activated.'
    )


@mcp.prompt(description="List a Switcher domain's environments.")
def switcher_environments(domain_id: str) -> str:
    """Build a guided message that drives the list_environments tool."""

    return (
        f"Call the list_environments tool with domain_id='{domain_id}'. "
        "List the returned environment names"
    )
